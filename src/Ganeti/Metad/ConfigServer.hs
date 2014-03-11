{-# LANGUAGE TupleSections #-}
{-| Configuration server for the metadata daemon.

-}

{-

Copyright (C) 2014 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}
module Ganeti.Metad.ConfigServer where

import Control.Arrow (second)
import Control.Concurrent
import Control.Exception (try, finally)
import Control.Monad (unless)
import qualified Data.List as List
import qualified Data.Map as Map
import Text.JSON
import qualified Text.JSON as JSON
import System.FilePath ((</>))
import System.IO.Error (isEOFError)

import Ganeti.Constants as Constants
import Ganeti.Path as Path
import Ganeti.Daemon (DaemonOptions)
import qualified Ganeti.Logging as Logging
import Ganeti.Runtime (GanetiDaemon(..))
import Ganeti.UDSServer (Client, ConnectConfig(..), Server)
import qualified Ganeti.UDSServer as UDSServer

import Ganeti.Metad.Types (InstanceParams)

metadSocket :: IO FilePath
metadSocket =
  do dir <- Path.socketDir
     return $ dir </> "ganeti-metad"

-- | Merges two instance configurations into one.
--
-- In the case where instance IPs (i.e., map keys) are repeated, the
-- old instance configuration is thrown away by 'Map.union' and
-- replaced by the new configuration.  As a result, the old private
-- and secret OS parameters are completely lost.
mergeConfig :: InstanceParams -> InstanceParams -> InstanceParams
mergeConfig cfg1 cfg2 = cfg2 `Map.union` cfg1

-- | Extracts the OS parameters (public, private, secret) from a JSON
-- object.
--
-- This function checks whether the OS parameters are in fact a JSON
-- object.
getOsParams :: String -> String -> JSObject JSValue -> Result (JSObject JSValue)
getOsParams key msg jsonObj =
  case lookup key (fromJSObject jsonObj) of
    Nothing -> Error $ "Could not find " ++ msg ++ " OS parameters"
    Just (JSObject x) -> Ok x
    _ -> Error "OS params is not a JSON object"

getPublicOsParams :: JSObject JSValue -> Result (JSObject JSValue)
getPublicOsParams = getOsParams "osparams" "public"

getPrivateOsParams :: JSObject JSValue -> Result (JSObject JSValue)
getPrivateOsParams = getOsParams "osparams_private" "private"

getSecretOsParams :: JSObject JSValue -> Result (JSObject JSValue)
getSecretOsParams = getOsParams "osparams_secret" "secret"

-- | Finds the IP address of the instance communication NIC in the
-- instance's NICs.
getInstanceCommunicationIp :: JSObject JSValue -> Result String
getInstanceCommunicationIp jsonObj =
  getNics >>= getInstanceCommunicationNic >>= getIp
  where
    getIp nic =
      case lookup "ip" (fromJSObject nic) of
        Nothing -> Error "Could not find instance communication IP"
        Just (JSString ip) -> Ok (JSON.fromJSString ip)
        _ -> Error "Instance communication IP is not a string"

    getInstanceCommunicationNic [] =
      Error "Could not find instance communication NIC"
    getInstanceCommunicationNic (JSObject nic:nics) =
      case lookup "name" (fromJSObject nic) of
        Just (JSString name)
          | Constants.instanceCommunicationNicPrefix
            `List.isPrefixOf` JSON.fromJSString name ->
            Ok nic
        _ -> getInstanceCommunicationNic nics
    getInstanceCommunicationNic _ =
      Error "Found wrong data in instance NICs"

    getNics =
      case lookup "nics" (fromJSObject jsonObj) of
        Nothing -> Error "Could not find OS parameters key 'nics'"
        Just (JSArray nics) -> Ok nics
        _ -> Error "Instance nics is not an array"

-- | Merges the OS parameters (public, private, secret) in a single
-- data structure containing all parameters and their visibility.
--
-- Example:
--   { "os-image": ["http://example.com/disk.img", "public"],
--     "os-password": ["mypassword", "secret"] }
makeInstanceParams
  :: JSObject JSValue -> JSObject JSValue -> JSObject JSValue -> JSValue
makeInstanceParams pub priv sec =
  JSObject . JSON.toJSObject $
    addVisibility "public" pub ++
    addVisibility "private" priv ++
    addVisibility "secret" sec
  where
    key = JSString . JSON.toJSString

    addVisibility param params =
      map (second (JSArray . (:[key param]))) (JSON.fromJSObject params)

-- | Extracts the OS parameters from the instance's parameters and
-- returns a data structure containing all the OS parameters and their
-- visibility indexed by the instance's IP address which is used in
-- the instance communication NIC.
getInstanceParams :: JSValue -> Result (String, InstanceParams)
getInstanceParams json =
    case json of
      JSObject jsonObj -> do
        name <- case lookup "name" (fromJSObject jsonObj) of
                  Nothing -> Error "Could not find instance name"
                  Just (JSString x) -> Ok (JSON.fromJSString x)
                  _ -> Error "Name is not a string"
        ip <- getInstanceCommunicationIp jsonObj
        publicOsParams <- getPublicOsParams jsonObj
        privateOsParams <- getPrivateOsParams jsonObj
        secretOsParams <- getSecretOsParams jsonObj
        let instanceParams =
              makeInstanceParams publicOsParams privateOsParams secretOsParams
        Ok (name, Map.fromList [(ip, instanceParams)])
      _ ->
        Error "Expecting a dictionary"

-- | Update the configuration with the received instance parameters.
updateConfig :: MVar InstanceParams -> String -> IO ()
updateConfig config str =
  case decode str of
    Error err ->
      Logging.logDebug $ show err
    Ok x ->
      case getInstanceParams x of
        Error err ->
          Logging.logError $ "Could not get instance parameters: " ++ err
        Ok (name, instanceParams) -> do
          cfg <- takeMVar config
          let cfg' = mergeConfig cfg instanceParams
          putMVar config cfg'
          Logging.logInfo $
            "Updated instance " ++ show name ++ " configuration"
          Logging.logDebug $ "Instance configuration: " ++ show cfg'

-- | Reads messages from clients and update the configuration
-- according to these messages.
acceptConfig :: MVar InstanceParams -> Client -> IO ()
acceptConfig config client =
  do res <- try $ UDSServer.recvMsg client
     case res of
       Left err -> do
         unless (isEOFError err) .
           Logging.logDebug $ show err
         return ()
       Right str -> do
         Logging.logDebug $ "Received: " ++ str
         updateConfig config str

-- | Loop that accepts clients and dispatches them to an isolated
-- thread that will handle the client's requests.
acceptClients :: MVar InstanceParams -> Server -> IO ()
acceptClients config server =
  do client <- UDSServer.acceptClient server
     _ <- forkIO $ acceptConfig config client
     acceptClients config server

start :: DaemonOptions -> MVar InstanceParams -> IO ()
start _ config =
  do server <- UDSServer.connectServer metadConfig True =<< metadSocket
     finally
       (acceptClients config server)
       (UDSServer.closeServer server)
  where
    metadConfig = ConnectConfig GanetiMetad 60 60

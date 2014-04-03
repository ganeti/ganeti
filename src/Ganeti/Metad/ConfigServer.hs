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

import Control.Concurrent
import Control.Exception (try, finally)
import Control.Monad (unless)
import Text.JSON
import System.FilePath ((</>))
import System.IO.Error (isEOFError)

import Ganeti.Path as Path
import Ganeti.Daemon (DaemonOptions)
import qualified Ganeti.Logging as Logging
import Ganeti.Runtime (GanetiDaemon(..))
import Ganeti.UDSServer (Client, ConnectConfig(..), Server)
import qualified Ganeti.UDSServer as UDSServer

import Ganeti.Metad.Config as Config
import Ganeti.Metad.Types (InstanceParams)

metadSocket :: IO FilePath
metadSocket =
  do dir <- Path.socketDir
     return $ dir </> "ganeti-metad"

-- | Update the configuration with the received instance parameters.
updateConfig :: MVar InstanceParams -> String -> IO ()
updateConfig config str =
  case decode str of
    Error err ->
      Logging.logDebug $ show err
    Ok x ->
      case Config.getInstanceParams x of
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

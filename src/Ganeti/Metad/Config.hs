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
module Ganeti.Metad.Config where

import Control.Arrow (second)
import qualified Data.List as List (isPrefixOf)
import qualified Data.Map as Map
import Text.JSON
import qualified Text.JSON as JSON

import Ganeti.Constants as Constants
import Ganeti.Metad.Types

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
    Just x -> readJSON x

getPublicOsParams :: JSObject JSValue -> Result (JSObject JSValue)
getPublicOsParams = getOsParams "osparams" "public"

getPrivateOsParams :: JSObject JSValue -> Result (JSObject JSValue)
getPrivateOsParams = getOsParams "osparams_private" "private"

getSecretOsParams :: JSObject JSValue -> Result (JSObject JSValue)
getSecretOsParams = getOsParams "osparams_secret" "secret"

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

getOsParamsWithVisibility :: JSValue -> Result JSValue
getOsParamsWithVisibility json =
  do obj <- readJSON json
     publicOsParams <- getPublicOsParams obj
     privateOsParams <- getPrivateOsParams obj
     secretOsParams <- getSecretOsParams obj
     Ok $ makeInstanceParams publicOsParams privateOsParams secretOsParams

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
        Ok (name, Map.fromList [(ip, json)])
      _ ->
        Error "Expecting a dictionary"

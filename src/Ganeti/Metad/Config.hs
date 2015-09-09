{-# LANGUAGE FlexibleContexts #-}

{-

Copyright (C) 2014 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}
module Ganeti.Metad.Config where

import Control.Arrow (second)
import Control.Monad ((>=>), mzero)
import Control.Monad.Trans
import Control.Monad.Trans.Maybe
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
--
-- > { "os-image": ["http://example.com/disk.img", "public"],
-- >   "os-password": ["mypassword", "secret"] }
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
-- instance's NICs. If the corresponding NIC isn't found, 'Nothing' is returned.
getInstanceCommunicationIp :: JSObject JSValue -> Result (Maybe String)
getInstanceCommunicationIp =
    runMaybeT . (getNics >=> getInstanceCommunicationNic >=> getIp)
  where
    getIp :: JSObject JSValue -> MaybeT Result String
    getIp nic =
      case lookup "ip" (fromJSObject nic) of
        Nothing -> failErrorT "Could not find instance communication IP"
        Just (JSString ip) -> return (JSON.fromJSString ip)
        _ -> failErrorT "Instance communication IP is not a string"

    getInstanceCommunicationNic :: [JSValue] -> MaybeT Result (JSObject JSValue)
    getInstanceCommunicationNic [] = mzero -- no communication NIC found
    getInstanceCommunicationNic (JSObject nic : nics) =
      case lookup "name" (fromJSObject nic) of
        Just (JSString name)
          | Constants.instanceCommunicationNicPrefix
            `List.isPrefixOf` JSON.fromJSString name ->
            return nic
        _ -> getInstanceCommunicationNic nics
    getInstanceCommunicationNic (n : _) =
      failErrorT $ "Found wrong data in instance NICs: " ++ show n

    getNics :: JSObject JSValue -> MaybeT Result [JSValue]
    getNics jsonObj =
      case lookup "nics" (fromJSObject jsonObj) of
        Nothing -> failErrorT "Could not find OS parameters key 'nics'"
        Just (JSArray nics) -> return nics
        _ -> failErrorT "Instance nics is not an array"

    -- | A helper function for failing a 'Result' wrapped in a monad
    -- transformer.
    failErrorT :: (MonadTrans t) => String -> t Result a
    failErrorT = lift . JSON.Error

-- | Extracts the OS parameters from the instance's parameters and
-- returns a data structure containing all the OS parameters and their
-- visibility indexed by the instance's IP address which is used in
-- the instance communication NIC.
getInstanceParams :: JSValue -> Result (String, Maybe InstanceParams)
getInstanceParams json =
    case json of
      JSObject jsonObj -> do
        name <- case lookup "name" (fromJSObject jsonObj) of
                  Nothing -> failError "Could not find instance name"
                  Just (JSString x) -> return (JSON.fromJSString x)
                  _ -> failError "Name is not a string"
        m'ip <- getInstanceCommunicationIp jsonObj
        return (name, fmap (\ip -> Map.fromList [(ip, json)]) m'ip)
      _ ->
        failError "Expecting a dictionary"
  where
    failError = JSON.Error

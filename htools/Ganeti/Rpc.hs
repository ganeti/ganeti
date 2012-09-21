{-# LANGUAGE MultiParamTypeClasses, FunctionalDependencies, CPP,
  BangPatterns, TemplateHaskell #-}

{-| Implementation of the RPC client.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.Rpc
  ( RpcCall
  , RpcResult
  , Rpc
  , RpcError(..)
  , ERpcError
  , executeRpcCall

  , rpcCallName
  , rpcCallTimeout
  , rpcCallData
  , rpcCallAcceptOffline

  , rpcResultFill

  , InstanceInfo(..)
  , RpcCallAllInstancesInfo(..)
  , RpcResultAllInstancesInfo(..)

  , RpcCallInstanceList(..)
  , RpcResultInstanceList(..)

  , HvInfo(..)
  , VgInfo(..)
  , RpcCallNodeInfo(..)
  , RpcResultNodeInfo(..)

  , rpcTimeoutFromRaw -- FIXME: Not used anywhere
  ) where

import Control.Arrow (second)
import qualified Text.JSON as J
import Text.JSON.Pretty (pp_value)
import Text.JSON (makeObj)

#ifndef NO_CURL
import Network.Curl
import qualified Ganeti.Path as P
#endif

import qualified Ganeti.Constants as C
import Ganeti.Objects
import Ganeti.THH
import Ganeti.Compat
import Ganeti.JSON

#ifndef NO_CURL
-- | The curl options used for RPC.
curlOpts :: [CurlOption]
curlOpts = [ CurlFollowLocation False
           , CurlCAInfo P.nodedCertFile
           , CurlSSLVerifyHost 0
           , CurlSSLVerifyPeer True
           , CurlSSLCertType "PEM"
           , CurlSSLCert P.nodedCertFile
           , CurlSSLKeyType "PEM"
           , CurlSSLKey P.nodedCertFile
           , CurlConnectTimeout (fromIntegral C.rpcConnectTimeout)
           ]
#endif

-- | Data type for RPC error reporting.
data RpcError
  = CurlDisabledError
  | CurlLayerError Node String
  | JsonDecodeError String
  | RpcResultError String
  | OfflineNodeError Node
  deriving Eq

instance Show RpcError where
  show CurlDisabledError =
    "RPC/curl backend disabled at compile time"
  show (CurlLayerError node code) =
    "Curl error for " ++ nodeName node ++ ", " ++ code
  show (JsonDecodeError msg) =
    "Error while decoding JSON from HTTP response: " ++ msg
  show (RpcResultError msg) =
    "Error reponse received from RPC server: " ++ msg
  show (OfflineNodeError node) =
    "Node " ++ nodeName node ++ " is marked as offline"

type ERpcError = Either RpcError

-- | Basic timeouts for RPC calls.
$(declareIADT "RpcTimeout"
  [ ( "Urgent",    'C.rpcTmoUrgent )
  , ( "Fast",      'C.rpcTmoFast )
  , ( "Normal",    'C.rpcTmoNormal )
  , ( "Slow",      'C.rpcTmoSlow )
  , ( "FourHours", 'C.rpcTmo4hrs )
  , ( "OneDay",    'C.rpcTmo1day )
  ])

-- | A generic class for RPC calls.
class (J.JSON a) => RpcCall a where
  -- | Give the (Python) name of the procedure.
  rpcCallName :: a -> String
  -- | Calculate the timeout value for the call execution.
  rpcCallTimeout :: a -> Int
  -- | Prepare arguments of the call to be send as POST.
  rpcCallData :: Node -> a -> String
  -- | Whether we accept offline nodes when making a call.
  rpcCallAcceptOffline :: a -> Bool

-- | A generic class for RPC results with default implementation.
class (J.JSON a) => RpcResult a where
  -- | Create a result based on the received HTTP response.
  rpcResultFill :: (Monad m) => J.JSValue -> m (ERpcError a)

-- | Generic class that ensures matching RPC call with its respective
-- result.
class (RpcCall a, RpcResult b) => Rpc a b | a -> b

-- | Http Request definition.
data HttpClientRequest = HttpClientRequest
  { requestTimeout :: Int
  , requestUrl :: String
  , requestPostData :: String
  }

-- | Execute the request and return the result as a plain String. When
-- curl reports an error, we propagate it.
executeHttpRequest :: Node -> ERpcError HttpClientRequest
                   -> IO (ERpcError String)

executeHttpRequest _ (Left rpc_err) = return $ Left rpc_err
#ifdef NO_CURL
executeHttpRequest _ _ = return $ Left CurlDisabledError
#else
executeHttpRequest node (Right request) = do
  let reqOpts = [ CurlTimeout (fromIntegral $ requestTimeout request)
                , CurlPostFields [requestPostData request]
                ]
      url = requestUrl request
  -- FIXME: This is very similar to getUrl in Htools/Rapi.hs
  (code, !body) <- curlGetString url $ curlOpts ++ reqOpts
  return $ case code of
             CurlOK -> Right body
             _ -> Left $ CurlLayerError node (show code)
#endif

-- | Prepare url for the HTTP request.
prepareUrl :: (RpcCall a) => Node -> a -> String
prepareUrl node call =
  let node_ip = nodePrimaryIp node
      port = snd C.daemonsPortsGanetiNoded
      path_prefix = "https://" ++ node_ip ++ ":" ++ show port
  in path_prefix ++ "/" ++ rpcCallName call

-- | Create HTTP request for a given node provided it is online,
-- otherwise create empty response.
prepareHttpRequest ::  (RpcCall a) => Node -> a
                   -> ERpcError HttpClientRequest
prepareHttpRequest node call
  | rpcCallAcceptOffline call || not (nodeOffline node) =
      Right HttpClientRequest { requestTimeout = rpcCallTimeout call
                              , requestUrl = prepareUrl node call
                              , requestPostData = rpcCallData node call
                              }
  | otherwise = Left $ OfflineNodeError node

-- | Parse a result based on the received HTTP response.
rpcResultParse :: (Monad m, RpcResult a) => String -> m (ERpcError a)
rpcResultParse res = do
  res' <- fromJResult "Reading JSON response" $ J.decode res
  case res' of
    (True, res'') ->
       rpcResultFill res''
    (False, jerr) -> case jerr of
       J.JSString msg -> return . Left $ RpcResultError (J.fromJSString msg)
       _ -> (return . Left) . JsonDecodeError $ show (pp_value jerr)

-- | Parse the response or propagate the error.
parseHttpResponse :: (Monad m, RpcResult a) => ERpcError String
                  -> m (ERpcError a)
parseHttpResponse (Left err) = return $ Left err
parseHttpResponse (Right response) = rpcResultParse response

-- | Execute RPC call for a sigle node.
executeSingleRpcCall :: (Rpc a b) => Node -> a -> IO (Node, ERpcError b)
executeSingleRpcCall node call = do
  let request = prepareHttpRequest node call
  response <- executeHttpRequest node request
  result <- parseHttpResponse response
  return (node, result)

-- | Execute RPC call for many nodes in parallel.
executeRpcCall :: (Rpc a b) => [Node] -> a -> IO [(Node, ERpcError b)]
executeRpcCall nodes call =
  sequence $ parMap rwhnf (uncurry executeSingleRpcCall)
               (zip nodes $ repeat call)

-- | Helper function that is used to read dictionaries of values.
sanitizeDictResults :: [(String, J.Result a)] -> ERpcError [(String, a)]
sanitizeDictResults [] = Right []
sanitizeDictResults ((_, J.Error err):_) = Left $ JsonDecodeError err
sanitizeDictResults ((name, J.Ok val):xs) =
  case sanitizeDictResults xs of
    Left err -> Left err
    Right res' -> Right $ (name, val):res'

-- * RPC calls and results

-- | AllInstancesInfo
--   Returns information about all running instances on the given nodes.
$(buildObject "RpcCallAllInstancesInfo" "rpcCallAllInstInfo"
  [ simpleField "hypervisors" [t| [Hypervisor] |] ])

$(buildObject "InstanceInfo" "instInfo"
  [ simpleField "memory" [t| Int|]
  , simpleField "state"  [t| String |] -- It depends on hypervisor :(
  , simpleField "vcpus"  [t| Int |]
  , simpleField "time"   [t| Int |]
  ])

$(buildObject "RpcResultAllInstancesInfo" "rpcResAllInstInfo"
  [ simpleField "instances" [t| [(String, InstanceInfo)] |] ])

instance RpcCall RpcCallAllInstancesInfo where
  rpcCallName _ = "all_instances_info"
  rpcCallTimeout _ = rpcTimeoutToRaw Urgent
  rpcCallAcceptOffline _ = False
  rpcCallData _ call = J.encode [rpcCallAllInstInfoHypervisors call]

instance RpcResult RpcResultAllInstancesInfo where
  -- FIXME: Is there a simpler way to do it?
  rpcResultFill res =
    return $ case res of
      J.JSObject res' -> do
        let res'' = map (second J.readJSON) (J.fromJSObject res')
                        :: [(String, J.Result InstanceInfo)]
        case sanitizeDictResults res'' of
          Left err -> Left err
          Right insts -> Right $ RpcResultAllInstancesInfo insts
      _ -> Left $ JsonDecodeError
           ("Expected JSObject, got " ++ show res)

instance Rpc RpcCallAllInstancesInfo RpcResultAllInstancesInfo

-- | InstanceList
-- Returns the list of running instances on the given nodes.
$(buildObject "RpcCallInstanceList" "rpcCallInstList"
  [ simpleField "hypervisors" [t| [Hypervisor] |] ])

$(buildObject "RpcResultInstanceList" "rpcResInstList"
  [ simpleField "instances" [t| [String] |] ])

instance RpcCall RpcCallInstanceList where
  rpcCallName _ = "instance_list"
  rpcCallTimeout _ = rpcTimeoutToRaw Urgent
  rpcCallAcceptOffline _ = False
  rpcCallData _ call = J.encode [rpcCallInstListHypervisors call]

instance RpcResult RpcResultInstanceList where
  rpcResultFill res =
    return $ case J.readJSON res of
      J.Error err -> Left $ JsonDecodeError err
      J.Ok insts -> Right $ RpcResultInstanceList insts

instance Rpc RpcCallInstanceList RpcResultInstanceList

-- | NodeInfo
-- Return node information.
$(buildObject "RpcCallNodeInfo" "rpcCallNodeInfo"
  [ simpleField "volume_groups" [t| [String] |]
  , simpleField "hypervisors" [t| [Hypervisor] |]
  ])

$(buildObject "VgInfo" "vgInfo"
  [ simpleField "name" [t| String |]
  , optionalField $ simpleField "vg_free" [t| Int |]
  , optionalField $ simpleField "vg_size" [t| Int |]
  ])

-- | We only provide common fields as described in hv_base.py.
$(buildObject "HvInfo" "hvInfo"
  [ simpleField "memory_total" [t| Int |]
  , simpleField "memory_free" [t| Int |]
  , simpleField "memory_dom0" [t| Int |]
  , simpleField "cpu_total" [t| Int |]
  , simpleField "cpu_nodes" [t| Int |]
  , simpleField "cpu_sockets" [t| Int |]
  ])

$(buildObject "RpcResultNodeInfo" "rpcResNodeInfo"
  [ simpleField "boot_id" [t| String |]
  , simpleField "vg_info" [t| [VgInfo] |]
  , simpleField "hv_info" [t| [HvInfo] |]
  ])

instance RpcCall RpcCallNodeInfo where
  rpcCallName _ = "node_info"
  rpcCallTimeout _ = rpcTimeoutToRaw Urgent
  rpcCallAcceptOffline _ = False
  rpcCallData _ call = J.encode ( rpcCallNodeInfoVolumeGroups call
                                , rpcCallNodeInfoHypervisors call
                                )

instance RpcResult RpcResultNodeInfo where
  rpcResultFill res =
    return $ case J.readJSON res of
      J.Error err -> Left $ JsonDecodeError err
      J.Ok (boot_id, vg_info, hv_info) ->
          Right $ RpcResultNodeInfo boot_id vg_info hv_info

instance Rpc RpcCallNodeInfo RpcResultNodeInfo

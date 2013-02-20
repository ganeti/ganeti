{-# LANGUAGE MultiParamTypeClasses, FunctionalDependencies,
  BangPatterns, TemplateHaskell #-}

{-| Implementation of the RPC client.

-}

{-

Copyright (C) 2012, 2013 Google Inc.

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
  , Rpc
  , RpcError(..)
  , ERpcError
  , explainRpcError
  , executeRpcCall

  , rpcCallName
  , rpcCallTimeout
  , rpcCallData
  , rpcCallAcceptOffline

  , rpcResultFill

  , InstanceInfo(..)
  , RpcCallInstanceInfo(..)
  , RpcResultInstanceInfo(..)

  , RpcCallAllInstancesInfo(..)
  , RpcResultAllInstancesInfo(..)

  , RpcCallInstanceList(..)
  , RpcResultInstanceList(..)

  , HvInfo(..)
  , VgInfo(..)
  , RpcCallNodeInfo(..)
  , RpcResultNodeInfo(..)

  , RpcCallVersion(..)
  , RpcResultVersion(..)

  , StorageField(..)
  , RpcCallStorageList(..)
  , RpcResultStorageList(..)

  , RpcCallTestDelay(..)
  , RpcResultTestDelay(..)

  , rpcTimeoutFromRaw -- FIXME: Not used anywhere
  ) where

import Control.Arrow (second)
import qualified Data.Map as Map
import Data.Maybe (fromMaybe)
import qualified Text.JSON as J
import Text.JSON.Pretty (pp_value)

import Network.Curl
import qualified Ganeti.Path as P

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Objects
import Ganeti.THH
import Ganeti.Types
import Ganeti.Curl.Multi
import Ganeti.Utils

-- * Base RPC functionality and types

-- | The curl options used for RPC.
curlOpts :: [CurlOption]
curlOpts = [ CurlFollowLocation False
           , CurlSSLVerifyHost 0
           , CurlSSLVerifyPeer True
           , CurlSSLCertType "PEM"
           , CurlSSLKeyType "PEM"
           , CurlConnectTimeout (fromIntegral C.rpcConnectTimeout)
           ]

-- | Data type for RPC error reporting.
data RpcError
  = CurlLayerError String
  | JsonDecodeError String
  | RpcResultError String
  | OfflineNodeError
  deriving (Show, Eq)

-- | Provide explanation to RPC errors.
explainRpcError :: RpcError -> String
explainRpcError (CurlLayerError code) =
    "Curl error:" ++ code
explainRpcError (JsonDecodeError msg) =
    "Error while decoding JSON from HTTP response: " ++ msg
explainRpcError (RpcResultError msg) =
    "Error reponse received from RPC server: " ++ msg
explainRpcError OfflineNodeError =
    "Node is marked offline"

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

-- | Generic class that ensures matching RPC call with its respective
-- result.
class (RpcCall a, J.JSON b) => Rpc a b  | a -> b, b -> a where
  -- | Create a result based on the received HTTP response.
  rpcResultFill :: a -> J.JSValue -> ERpcError b

-- | Http Request definition.
data HttpClientRequest = HttpClientRequest
  { requestUrl  :: String       -- ^ The actual URL for the node endpoint
  , requestData :: String       -- ^ The arguments for the call
  , requestOpts :: [CurlOption] -- ^ The various curl options
  }

-- | Prepare url for the HTTP request.
prepareUrl :: (RpcCall a) => Node -> a -> String
prepareUrl node call =
  let node_ip = nodePrimaryIp node
      port = snd C.daemonsPortsGanetiNoded
      path_prefix = "https://" ++ node_ip ++ ":" ++ show port
  in path_prefix ++ "/" ++ rpcCallName call

-- | Create HTTP request for a given node provided it is online,
-- otherwise create empty response.
prepareHttpRequest :: (RpcCall a) => [CurlOption] -> Node -> a
                   -> ERpcError HttpClientRequest
prepareHttpRequest opts node call
  | rpcCallAcceptOffline call || not (nodeOffline node) =
      Right HttpClientRequest { requestUrl  = prepareUrl node call
                              , requestData = rpcCallData node call
                              , requestOpts = opts ++ curlOpts
                              }
  | otherwise = Left OfflineNodeError

-- | Parse an HTTP reply.
parseHttpReply :: (Rpc a b) =>
                  a -> ERpcError (CurlCode, String) -> ERpcError b
parseHttpReply _ (Left e) = Left e
parseHttpReply call (Right (CurlOK, body)) = parseHttpResponse call body
parseHttpReply _ (Right (code, err)) =
  Left . CurlLayerError $ "code: " ++ show code ++ ", explanation: " ++ err

-- | Parse a result based on the received HTTP response.
parseHttpResponse :: (Rpc a b) => a -> String -> ERpcError b
parseHttpResponse call res =
  case J.decode res of
    J.Error val -> Left $ JsonDecodeError val
    J.Ok (True, res'') -> rpcResultFill call res''
    J.Ok (False, jerr) -> case jerr of
       J.JSString msg -> Left $ RpcResultError (J.fromJSString msg)
       _ -> Left . JsonDecodeError $ show (pp_value jerr)

-- | Execute RPC call for many nodes in parallel.
executeRpcCall :: (Rpc a b) => [Node] -> a -> IO [(Node, ERpcError b)]
executeRpcCall nodes call = do
  cert_file <- P.nodedCertFile
  let opts = [ CurlTimeout (fromIntegral $ rpcCallTimeout call)
             , CurlSSLCert cert_file
             , CurlSSLKey cert_file
             , CurlCAInfo cert_file
             ]
      opts_urls = map (\n ->
                         case prepareHttpRequest opts n call of
                           Left v -> Left v
                           Right request ->
                             Right (CurlPostFields [requestData request]:
                                    requestOpts request,
                                    requestUrl request)
                      ) nodes
  -- split the opts_urls list; we don't want to pass the
  -- failed-already nodes to Curl
  let (lefts, rights, trail) = splitEithers opts_urls
  results <- execMultiCall rights
  results' <- case recombineEithers lefts results trail of
                Bad msg -> error msg
                Ok r -> return r
  -- now parse the replies
  let results'' = map (parseHttpReply call) results'
  return $ zip nodes results''

-- | Helper function that is used to read dictionaries of values.
sanitizeDictResults :: [(String, J.Result a)] -> ERpcError [(String, a)]
sanitizeDictResults =
  foldr sanitize1 (Right [])
  where
    sanitize1 _ (Left e) = Left e
    sanitize1 (_, J.Error e) _ = Left $ JsonDecodeError e
    sanitize1 (name, J.Ok v) (Right res) = Right $ (name, v) : res

-- | Helper function to tranform JSON Result to Either RpcError b.
-- Note: For now we really only use it for b s.t. Rpc c b for some c
fromJResultToRes :: J.Result a -> (a -> b) -> ERpcError b
fromJResultToRes (J.Error v) _ = Left $ JsonDecodeError v
fromJResultToRes (J.Ok v) f = Right $ f v

-- | Helper function transforming JSValue to Rpc result type.
fromJSValueToRes :: (J.JSON a) => J.JSValue -> (a -> b) -> ERpcError b
fromJSValueToRes val = fromJResultToRes (J.readJSON val)

-- * RPC calls and results

-- ** Instance info

-- | InstanceInfo
--   Returns information about a single instance.

$(buildObject "RpcCallInstanceInfo" "rpcCallInstInfo"
  [ simpleField "instance" [t| String |]
  , simpleField "hname" [t| Hypervisor |]
  ])

$(buildObject "InstanceInfo" "instInfo"
  [ simpleField "memory" [t| Int|]
  , simpleField "state"  [t| String |] -- It depends on hypervisor :(
  , simpleField "vcpus"  [t| Int |]
  , simpleField "time"   [t| Int |]
  ])

-- This is optional here because the result may be empty if instance is
-- not on a node - and this is not considered an error.
$(buildObject "RpcResultInstanceInfo" "rpcResInstInfo"
  [ optionalField $ simpleField "inst_info" [t| InstanceInfo |]])

instance RpcCall RpcCallInstanceInfo where
  rpcCallName _          = "instance_info"
  rpcCallTimeout _       = rpcTimeoutToRaw Urgent
  rpcCallAcceptOffline _ = False
  rpcCallData _ call     = J.encode
    ( rpcCallInstInfoInstance call
    , rpcCallInstInfoHname call
    )

instance Rpc RpcCallInstanceInfo RpcResultInstanceInfo where
  rpcResultFill _ res =
    case res of
      J.JSObject res' ->
        case J.fromJSObject res' of
          [] -> Right $ RpcResultInstanceInfo Nothing
          _ -> fromJSValueToRes res (RpcResultInstanceInfo . Just)
      _ -> Left $ JsonDecodeError
           ("Expected JSObject, got " ++ show (pp_value res))

-- ** AllInstancesInfo

-- | AllInstancesInfo
--   Returns information about all running instances on the given nodes
$(buildObject "RpcCallAllInstancesInfo" "rpcCallAllInstInfo"
  [ simpleField "hypervisors" [t| [Hypervisor] |] ])

$(buildObject "RpcResultAllInstancesInfo" "rpcResAllInstInfo"
  [ simpleField "instances" [t| [(String, InstanceInfo)] |] ])

instance RpcCall RpcCallAllInstancesInfo where
  rpcCallName _          = "all_instances_info"
  rpcCallTimeout _       = rpcTimeoutToRaw Urgent
  rpcCallAcceptOffline _ = False
  rpcCallData _ call     = J.encode [rpcCallAllInstInfoHypervisors call]

instance Rpc RpcCallAllInstancesInfo RpcResultAllInstancesInfo where
  -- FIXME: Is there a simpler way to do it?
  rpcResultFill _ res =
    case res of
      J.JSObject res' ->
        let res'' = map (second J.readJSON) (J.fromJSObject res')
                        :: [(String, J.Result InstanceInfo)] in
        case sanitizeDictResults res'' of
          Left err -> Left err
          Right insts -> Right $ RpcResultAllInstancesInfo insts
      _ -> Left $ JsonDecodeError
           ("Expected JSObject, got " ++ show (pp_value res))

-- ** InstanceList

-- | InstanceList
-- Returns the list of running instances on the given nodes.
$(buildObject "RpcCallInstanceList" "rpcCallInstList"
  [ simpleField "hypervisors" [t| [Hypervisor] |] ])

$(buildObject "RpcResultInstanceList" "rpcResInstList"
  [ simpleField "instances" [t| [String] |] ])

instance RpcCall RpcCallInstanceList where
  rpcCallName _          = "instance_list"
  rpcCallTimeout _       = rpcTimeoutToRaw Urgent
  rpcCallAcceptOffline _ = False
  rpcCallData _ call     = J.encode [rpcCallInstListHypervisors call]

instance Rpc RpcCallInstanceList RpcResultInstanceList where
  rpcResultFill _ res = fromJSValueToRes res RpcResultInstanceList

-- ** NodeInfo

-- | NodeInfo
-- Return node information.
$(buildObject "RpcCallNodeInfo" "rpcCallNodeInfo"
  [ simpleField "volume_groups" [t| [String] |]
  , simpleField "hypervisors" [t| [Hypervisor] |]
  , simpleField "exclusive_storage" [t| Map.Map String Bool |]
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
  rpcCallName _          = "node_info"
  rpcCallTimeout _       = rpcTimeoutToRaw Urgent
  rpcCallAcceptOffline _ = False
  rpcCallData n call     = J.encode
    ( rpcCallNodeInfoVolumeGroups call
    , rpcCallNodeInfoHypervisors call
    , fromMaybe (error $ "Programmer error: missing parameter for node named "
                         ++ nodeName n)
                $ Map.lookup (nodeName n) (rpcCallNodeInfoExclusiveStorage call)
    )

instance Rpc RpcCallNodeInfo RpcResultNodeInfo where
  rpcResultFill _ res =
    fromJSValueToRes res (\(b, vg, hv) -> RpcResultNodeInfo b vg hv)

-- ** Version

-- | Version
-- Query node version.
-- Note: We can't use THH as it does not know what to do with empty dict
data RpcCallVersion = RpcCallVersion {}
  deriving (Show, Eq)

instance J.JSON RpcCallVersion where
  showJSON _ = J.JSNull
  readJSON J.JSNull = return RpcCallVersion
  readJSON _ = fail "Unable to read RpcCallVersion"

$(buildObject "RpcResultVersion" "rpcResultVersion"
  [ simpleField "version" [t| Int |]
  ])

instance RpcCall RpcCallVersion where
  rpcCallName _          = "version"
  rpcCallTimeout _       = rpcTimeoutToRaw Urgent
  rpcCallAcceptOffline _ = True
  rpcCallData _          = J.encode

instance Rpc RpcCallVersion RpcResultVersion where
  rpcResultFill _ res = fromJSValueToRes res RpcResultVersion

-- ** StorageList

-- | StorageList

-- FIXME: This may be moved to Objects
$(declareSADT "StorageField"
  [ ( "SFUsed",        'C.sfUsed)
  , ( "SFName",        'C.sfName)
  , ( "SFAllocatable", 'C.sfAllocatable)
  , ( "SFFree",        'C.sfFree)
  , ( "SFSize",        'C.sfSize)
  ])
$(makeJSONInstance ''StorageField)

$(buildObject "RpcCallStorageList" "rpcCallStorageList"
  [ simpleField "su_name" [t| StorageType |]
  , simpleField "su_args" [t| [String] |]
  , simpleField "name"    [t| String |]
  , simpleField "fields"  [t| [StorageField] |]
  ])

-- FIXME: The resulting JSValues should have types appropriate for their
-- StorageField value: Used -> Bool, Name -> String etc
$(buildObject "RpcResultStorageList" "rpcResStorageList"
  [ simpleField "storage" [t| [[(StorageField, J.JSValue)]] |] ])

instance RpcCall RpcCallStorageList where
  rpcCallName _          = "storage_list"
  rpcCallTimeout _       = rpcTimeoutToRaw Normal
  rpcCallAcceptOffline _ = False
  rpcCallData _ call     = J.encode
    ( rpcCallStorageListSuName call
    , rpcCallStorageListSuArgs call
    , rpcCallStorageListName call
    , rpcCallStorageListFields call
    )

instance Rpc RpcCallStorageList RpcResultStorageList where
  rpcResultFill call res =
    let sfields = rpcCallStorageListFields call in
    fromJSValueToRes res (RpcResultStorageList . map (zip sfields))

-- ** TestDelay


-- | Call definition for test delay.
$(buildObject "RpcCallTestDelay" "rpcCallTestDelay"
  [ simpleField "duration" [t| Double |]
  ])

-- | Result definition for test delay.
data RpcResultTestDelay = RpcResultTestDelay
                          deriving Show

-- | Custom JSON instance for null result.
instance J.JSON RpcResultTestDelay where
  showJSON _        = J.JSNull
  readJSON J.JSNull = return RpcResultTestDelay
  readJSON _        = fail "Unable to read RpcResultTestDelay"

instance RpcCall RpcCallTestDelay where
  rpcCallName _          = "test_delay"
  rpcCallTimeout         = ceiling . (+ 5) . rpcCallTestDelayDuration
  rpcCallAcceptOffline _ = False
  rpcCallData _ call     = J.encode [rpcCallTestDelayDuration call]

instance Rpc RpcCallTestDelay RpcResultTestDelay where
  rpcResultFill _ res = fromJSValueToRes res id

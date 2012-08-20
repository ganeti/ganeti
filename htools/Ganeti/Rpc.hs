{-# LANGUAGE MultiParamTypeClasses, FunctionalDependencies, CPP,
  BangPatterns #-}

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
  , executeRpcCall

  , rpcCallName
  , rpcCallTimeout
  , rpcCallData
  , rpcCallAcceptOffline

  , rpcResultFill
  ) where

import qualified Text.JSON as J

#ifndef NO_CURL
import Network.Curl
#endif

import qualified Ganeti.Constants as C
import Ganeti.Objects
import Ganeti.HTools.Compat

#ifndef NO_CURL
-- | The curl options used for RPC.
curlOpts :: [CurlOption]
curlOpts = [ CurlFollowLocation False
           , CurlCAInfo C.nodedCertFile
           , CurlSSLVerifyHost 0
           , CurlSSLVerifyPeer True
           , CurlSSLCertType "PEM"
           , CurlSSLCert C.nodedCertFile
           , CurlSSLKeyType "PEM"
           , CurlSSLKey C.nodedCertFile
           , CurlConnectTimeout (fromIntegral C.rpcConnectTimeout)
           ]
#endif

-- | Data type for RPC error reporting.
data RpcError
  = CurlDisabledError
  | CurlLayerError Node String
  | JsonDecodeError String
  | OfflineNodeError Node
  deriving Eq

instance Show RpcError where
  show CurlDisabledError =
    "RPC/curl backend disabled at compile time"
  show (CurlLayerError node code) =
    "Curl error for " ++ nodeName node ++ ", error " ++ code
  show (JsonDecodeError msg) =
    "Error while decoding JSON from HTTP response " ++ msg
  show (OfflineNodeError node) =
    "Node " ++ nodeName node ++ " is marked as offline"

rpcErrorJsonReport :: (Monad m) => J.Result a -> m (Either RpcError a)
rpcErrorJsonReport (J.Error x) = return $ Left $ JsonDecodeError x
rpcErrorJsonReport (J.Ok x) = return $ Right x

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

  rpcCallData _ = J.encode

-- | A generic class for RPC results with default implementation.
class (J.JSON a) => RpcResult a where
  -- | Create a result based on the received HTTP response.
  rpcResultFill :: (Monad m) => String -> m (Either RpcError a)

  rpcResultFill res = rpcErrorJsonReport $  J.decode res

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
executeHttpRequest :: Node -> Either RpcError HttpClientRequest
                   -> IO (Either RpcError String)

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
  case code of
    CurlOK -> return $ Right body
    _ -> return $ Left $ CurlLayerError node (show code)
#endif

-- | Prepare url for the HTTP request.
prepareUrl :: (RpcCall a) => Node -> a -> String
prepareUrl node call =
  let node_ip = nodePrimaryIp node
      port = snd C.daemonsPortsGanetiNoded
      path_prefix = "https://" ++ (node_ip) ++ ":" ++ (show port) in
  path_prefix ++ "/" ++ rpcCallName call

-- | Create HTTP request for a given node provided it is online,
-- otherwise create empty response.
prepareHttpRequest ::  (RpcCall a) => Node -> a
                   -> Either RpcError HttpClientRequest
prepareHttpRequest node call
  | rpcCallAcceptOffline call ||
    (not $ nodeOffline node) =
      Right $ HttpClientRequest { requestTimeout = rpcCallTimeout call
                                , requestUrl = prepareUrl node call
                                , requestPostData = rpcCallData node call
                                }
  | otherwise = Left $ OfflineNodeError node

-- | Parse the response or propagate the error.
parseHttpResponse :: (Monad m, RpcResult a) => Either RpcError String
                  -> m (Either RpcError a)
parseHttpResponse (Left err) = return $ Left err
parseHttpResponse (Right response) = rpcResultFill response

-- | Execute RPC call for a sigle node.
executeSingleRpcCall :: (Rpc a b) => Node -> a -> IO (Node, Either RpcError b)
executeSingleRpcCall node call = do
  let request = prepareHttpRequest node call
  response <- executeHttpRequest node request
  result <- parseHttpResponse response
  return (node, result)

-- | Execute RPC call for many nodes in parallel.
executeRpcCall :: (Rpc a b) => [Node] -> a -> IO [(Node, Either RpcError b)]
executeRpcCall nodes call =
  sequence $ parMap rwhnf (uncurry executeSingleRpcCall)
               (zip nodes $ repeat call)

{-# LANGUAGE MultiParamTypeClasses, FunctionalDependencies #-}

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

  , rpcCallName
  , rpcCallTimeout
  , rpcCallData
  , rpcCallAcceptOffline

  , rpcResultFill
  ) where

import qualified Text.JSON as J

import Ganeti.Objects

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

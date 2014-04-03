{-# LANGUAGE TemplateHaskell, FunctionalDependencies, FlexibleContexts #-}
-- {-# OPTIONS_GHC -fno-warn-warnings-deprecations #-}

{-| Creates a client out of list of RPC server components.

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

module Ganeti.THH.HsRPC
  ( RpcClientMonad
  , runRpcClient
  , mkRpcCall
  , mkRpcCalls
  ) where

import Control.Applicative
import Control.Monad
import Control.Monad.Base
import Control.Monad.Error
import Control.Monad.Reader
import Language.Haskell.TH
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.JSON (fromJResultE)
import Ganeti.THH.Types
import Ganeti.UDSServer


-- * The monad for RPC clients

-- | The monad for all client RPC functions.
-- Given a client value, it runs the RPC call in IO and either retrieves the
-- result or the error.
newtype RpcClientMonad a =
  RpcClientMonad { runRpcClientMonad :: ReaderT Client ResultG a }

instance Functor RpcClientMonad where
  fmap f = RpcClientMonad . fmap f . runRpcClientMonad

instance Applicative RpcClientMonad where
  pure = RpcClientMonad . pure
  (RpcClientMonad f) <*> (RpcClientMonad k) = RpcClientMonad (f <*> k)

instance Monad RpcClientMonad where
  return = RpcClientMonad . return
  (RpcClientMonad k) >>= f = RpcClientMonad (k >>= runRpcClientMonad . f)

instance MonadBase IO RpcClientMonad where
  liftBase = RpcClientMonad . liftBase

instance MonadIO RpcClientMonad where
  liftIO = RpcClientMonad . liftIO

instance MonadError GanetiException RpcClientMonad where
  throwError = RpcClientMonad . throwError
  catchError (RpcClientMonad k) h =
    RpcClientMonad (catchError k (runRpcClientMonad . h))

-- * The TH functions to construct RPC client functions from RPC server ones

-- | Given a client run a given client RPC action.
runRpcClient :: (MonadBase IO m, MonadError GanetiException m)
             => RpcClientMonad a -> Client -> m a
runRpcClient = (toErrorBase .) . runReaderT . runRpcClientMonad

callMethod :: (J.JSON r, J.JSON args) => String -> args -> RpcClientMonad r
callMethod method args = do
  client <- RpcClientMonad ask
  let request = buildCall method (J.showJSON args)
  liftIO $ sendMsg client request
  response <- liftIO $ recvMsg client
  toError $ parseResponse response
            >>= fromJResultE "Parsing RPC JSON response" . J.readJSON

-- | Given a server RPC function (such as from WConfd.Core), creates
-- the corresponding client function. The monad of the result type of the
-- given function is replaced by 'RpcClientMonad' and the new function
-- is implemented to issue a RPC call to the server.
mkRpcCall :: Name -> Q [Dec]
mkRpcCall name = do
  let bname = nameBase name
      fname = mkName bname  -- the name of the generated function
  (args, rtype) <- funArgs <$> typeOfFun name
  rarg <- argumentType rtype
  let ftype = foldr (\a t -> AppT (AppT ArrowT a) t)
                    (AppT (ConT ''RpcClientMonad) rarg) args
  body <- [| $(curryN $ length args) (callMethod $(stringE bname)) |]
  return [ SigD fname ftype
         , ValD (VarP fname) (NormalB body) []
         ]

-- Given a list of server RPC functions creates the corresponding client
-- RPC functions.
--
-- See 'mkRpcCall'
mkRpcCalls :: [Name] -> Q [Dec]
mkRpcCalls = liftM concat . mapM mkRpcCall

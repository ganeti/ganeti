{-# LANGUAGE TemplateHaskell, FunctionalDependencies, FlexibleContexts, CPP,
             TypeFamilies, UndecidableInstances #-}
-- {-# OPTIONS_GHC -fno-warn-warnings-deprecations #-}

{-| Creates a client out of list of RPC server components.

-}

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

module Ganeti.THH.HsRPC
  ( RpcClientMonad
  , runRpcClient
  , mkRpcCall
  , mkRpcCalls
  ) where

-- The following macro is just a temporary solution for 2.12 and 2.13.
-- Since 2.14 cabal creates proper macros for all dependencies.
#define MIN_VERSION_monad_control(maj,min,rev) \
  (((maj)<MONAD_CONTROL_MAJOR)|| \
   (((maj)==MONAD_CONTROL_MAJOR)&&((min)<=MONAD_CONTROL_MINOR))|| \
   (((maj)==MONAD_CONTROL_MAJOR)&&((min)==MONAD_CONTROL_MINOR)&& \
    ((rev)<=MONAD_CONTROL_REV)))

import Control.Applicative
import Control.Monad
import Control.Monad.Base
import Control.Monad.Error
import Control.Monad.Reader
import Control.Monad.Trans.Control
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

instance MonadBaseControl IO RpcClientMonad where
#if MIN_VERSION_monad_control(1,0,0)
-- Needs Undecidable instances
  type StM RpcClientMonad b = StM (ReaderT Client ResultG) b
  liftBaseWith f = RpcClientMonad . liftBaseWith
                   $ \r -> f (r . runRpcClientMonad)
  restoreM = RpcClientMonad . restoreM
#else
  newtype StM RpcClientMonad b = StMRpcClientMonad
    { runStMRpcClientMonad :: StM (ReaderT Client ResultG) b }
  liftBaseWith f = RpcClientMonad . liftBaseWith
                   $ \r -> f (liftM StMRpcClientMonad . r . runRpcClientMonad)
  restoreM = RpcClientMonad . restoreM . runStMRpcClientMonad
#endif

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

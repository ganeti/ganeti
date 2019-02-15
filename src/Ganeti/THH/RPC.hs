{-# LANGUAGE TemplateHaskell, ExistentialQuantification #-}

{-| Implements Template Haskell generation of RPC server components from Haskell
functions.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.THH.RPC
  ( Request(..)
  , RpcServer
  , dispatch
  , mkRpcM
  ) where

import Control.Applicative
import Control.Arrow ((&&&))
import Control.Monad
import Control.Monad.Error.Class
import Data.Map (Map)
import qualified Data.Map as Map
import Language.Haskell.TH
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.JSON (fromJResultE, fromJVal)
import Ganeti.THH.Types
import qualified Ganeti.UDSServer as US

data RpcFn m = forall i o . (J.JSON i, J.JSON o) => RpcFn (i -> m o)

type RpcServer m = US.Handler Request m J.JSValue

-- | A RPC request consiting of a method and its argument(s).
data Request = Request { rMethod :: String, rArgs :: J.JSValue }
  deriving (Eq, Ord, Show)

decodeRequest :: J.JSValue -> J.JSValue -> Result Request
decodeRequest method args = Request <$> fromJVal method <*> pure args


dispatch :: (Monad m)
         => Map String (RpcFn (ResultT GanetiException m)) -> RpcServer m
dispatch fs =
  US.Handler { US.hParse         = decodeRequest
             , US.hInputLogShort = rMethod
             , US.hInputLogLong  = rMethod
             , US.hExec          = liftToHandler . exec
             }
  where
    orError :: (MonadError e m, Error e) => Maybe a -> e -> m a
    orError m e = maybe (throwError e) return m

    exec (Request m as) = do
      (RpcFn f) <- orError (Map.lookup m fs)
                           (strMsg $ "No such method: " ++ m)
      i <- fromJResultE "RPC input" . J.readJSON $ as
      o <- f i -- lift $ f i
      return $ J.showJSON o

    liftToHandler :: (Monad m)
                  => ResultT GanetiException m J.JSValue
                  -> US.HandlerResult m J.JSValue
    liftToHandler = liftM ((,) True) . runResultT

-- | Converts a function into the appropriate @RpcFn m@ expression.
-- The function's result must be monadic.
toRpcFn :: Name -> Q Exp
toRpcFn name = [| RpcFn $( uncurryVar name ) |]

-- | Convert a list of named expressions into an expression containing a list
-- of name/expression pairs.
rpcFnsList :: [(String, Q Exp)] -> Q Exp
rpcFnsList = listE . map (\(name, expr) -> tupE [stringE name, expr])

-- | Takes a list of function names and creates a RPC handler that delegates
-- calls to them.
--
-- The functions must conform to
-- @(J.JSON i, J.JSON o) => i -> ResultT GanetiException m o@. The @m@
-- monads types of all the functions must unify.
--
-- The result expression is of type @RpcServer m@.
mkRpcM
    :: [Name]     -- ^ the names of functions to include
    -> Q Exp
mkRpcM names = [| dispatch . Map.fromList $
                        $( rpcFnsList . map (nameBase &&& toRpcFn) $ names ) |]

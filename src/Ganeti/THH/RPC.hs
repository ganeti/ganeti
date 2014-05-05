{-# LANGUAGE TemplateHaskell, ExistentialQuantification #-}

{-| Implements Template Haskell generation of RPC server components from Haskell
functions.

-}

{-

Copyright (C) 2013 Google Inc.

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
import Ganeti.JSON
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

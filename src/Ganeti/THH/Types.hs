{-# LANGUAGE TemplateHaskell, DeriveFunctor #-}

{-| Utility Template Haskell functions for working with types.

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

module Ganeti.THH.Types
  ( typeOfFun
  , funArgs
  , tupleArgs
  , argumentType
  , uncurryVarType
  , uncurryVar
  , curryN
  , OneTuple(..)
  ) where

import Control.Arrow (first)
import Control.Monad (liftM, replicateM)
import Language.Haskell.TH
import qualified Text.JSON as J

-- | This fills the gap between @()@ and @(,)@, providing a wrapper for
-- 1-element tuples. It's needed for RPC, where arguments for a function are
-- sent as a list of values, and therefore for 1-argument functions we need
-- this wrapper, which packs/unpacks 1-element lists.
newtype OneTuple a = OneTuple { getOneTuple :: a }
  deriving (Eq, Ord, Show, Functor)
-- The value is stored in @JSON@ as a 1-element list.
instance J.JSON a => J.JSON (OneTuple a) where
  showJSON (OneTuple a) = J.JSArray [J.showJSON a]
  readJSON (J.JSArray [x]) = liftM OneTuple (J.readJSON x)
  readJSON _               = J.Error "Unable to read 1 tuple"

-- | Returns the type of a function. If the given name doesn't correspond to a
-- function, fails.
typeOfFun :: Name -> Q Type
typeOfFun name = reify name >>= args
  where
    args :: Info -> Q Type
    args (VarI _ tp _ _) = return tp
    args _               = fail $ "Not a function: " ++ show name

-- | Splits a function type into the types of its arguments and the result.
funArgs :: Type -> ([Type], Type)
funArgs = first reverse . f []
  where
    f ts (ForallT _ _ x)            = f ts x
    f ts (AppT (AppT ArrowT t) x)   = f (t:ts) x
    f ts x                          = (ts, x)

tupleArgs :: Type -> Maybe [Type]
tupleArgs = fmap reverse . f []
  where
    f ts (TupleT _)                = Just ts
    f ts (AppT (AppT ArrowT x) t)  = f (t:ts) x
    f _  _                         = Nothing

-- | Given a type of the form @m a@, this function extracts @a@.
-- If the given type is of another form, it fails with an error message.
argumentType :: Type -> Q Type
argumentType (AppT _ t) = return t
argumentType t          = fail $ "Not a type of the form 'm a': " ++ show t

-- | Generic 'uncurry' that counts the number of function arguments in a type
-- and constructs the appropriate uncurry function into @i -> o@.
-- It the type has no arguments, it's converted into @() -> o@.
uncurryVarType :: Type -> Q Exp
uncurryVarType = uncurryN . length . fst . funArgs
  where
    uncurryN 0 = do
      f <- newName "f"
      return $ LamE [VarP f, TupP []] (VarE f)
    uncurryN 1 = [| (. getOneTuple) |]
    uncurryN n = do
      f <- newName "f"
      ps <- replicateM n (newName "x")
      return $ LamE [VarP f, TupP $ map VarP ps]
                 (foldl AppE (VarE f) $ map VarE ps)

-- | Creates an uncurried version of a function.
-- If the function has no arguments, it's converted into @() -> o@.
uncurryVar :: Name -> Q Exp
uncurryVar name = do
  t <- typeOfFun name
  appE (uncurryVarType t) (varE name)

-- | Generic 'curry' that constructs a curring function of a given arity.
curryN :: Int -> Q Exp
curryN 0 = [| ($ ()) |]
curryN 1 = [| (. OneTuple) |]
curryN n = do
  f <- newName "f"
  ps <- replicateM n (newName "x")
  return $ LamE (VarP f : map VarP ps)
             (AppE (VarE f) (TupE $ map VarE ps))

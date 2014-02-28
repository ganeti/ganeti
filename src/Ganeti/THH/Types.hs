{-# LANGUAGE TemplateHaskell #-}

{-| Utility Template Haskell functions for working with types.

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

module Ganeti.THH.Types
  ( typeOfFun
  , funArgs
  , tupleArgs
  , uncurryVarType
  , uncurryVar
  , OneTuple(..)
  ) where

import Control.Arrow (first)
import Control.Monad (liftM)
import Language.Haskell.TH
import qualified Text.JSON as J

-- | This fills the gap between @()@ and @(,)@, providing a wrapper for
-- 1-element tuples. It's needed for RPC, where arguments for a function are
-- sent as a list of values, and therefore for 1-argument functions we need
-- this wrapper, which packs/unpacks 1-element lists.
newtype OneTuple a = OneTuple { getOneTuple :: a }
  deriving (Eq, Ord, Show)
instance Functor OneTuple where
  fmap f (OneTuple x) = OneTuple (f x)
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
      ps <- mapM newName (replicate n "x")
      return $ LamE [VarP f, TupP $ map VarP ps]
                 (foldl AppE (VarE f) $ map VarE ps)

-- | Creates an uncurried version of a function.
-- If the function has no arguments, it's converted into @() -> o@.
uncurryVar :: Name -> Q Exp
uncurryVar name = do
  t <- typeOfFun name
  appE (uncurryVarType t) (varE name)

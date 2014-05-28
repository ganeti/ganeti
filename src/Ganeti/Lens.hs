{-# LANGUAGE RankNTypes #-}

{-| Provides all lens-related functions.

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

module Ganeti.Lens
  ( module Control.Lens
  , lensWith
  , makeCustomLenses
  , makeCustomLenses'
  , traverseOf2
  , atSet
  ) where

import Control.Applicative ((<$>))
import Control.Lens
import Control.Monad
import Data.Functor.Compose (Compose(..))
import qualified Data.Set as S
import Language.Haskell.TH

-- | Creates an optimized lens where the setter also gets the original value
-- from the getter.
lensWith :: (s -> a) -> (s -> a -> b -> t) -> Lens s t a b
lensWith sa sbt f s = uncurry (sbt s) <$> (\a -> fmap ((,) a) (f a)) (sa s)

lensFieldName :: String -> String
lensFieldName = (++ "L")

-- | Internal helper method for constructing partial set of lenses.
makeCustomLensesFiltered :: (String -> Bool) -> Name -> Q [Dec]
makeCustomLensesFiltered f = makeLensesWith customRules
  where
    customRules :: LensRules
    customRules = set lensField (fmap lensFieldName . mfilter f . Just)
                      defaultRules

-- | Create lenses for all fields of a given data type.
makeCustomLenses :: Name -> Q [Dec]
makeCustomLenses = makeCustomLensesFiltered (const True)

-- | Create lenses for some fields of a given data type.
makeCustomLenses' :: Name -> [Name] -> Q [Dec]
makeCustomLenses' name lst = makeCustomLensesFiltered f name
  where
    allowed = S.fromList . map nameBase $ lst
    f = flip S.member allowed

-- | Traverses over a composition of two functors.
-- Most often the @g@ functor is @(,) r@ and 'traverseOf2' is used to
-- traverse an effectful computation that also returns an additional output
-- value.
traverseOf2 :: Over (->) (Compose f g) s t a b
            -> (a -> f (g b)) -> s -> f (g t)
traverseOf2 k f = getCompose . traverseOf k (Compose . f)

-- | A helper lens over sets.
-- While a similar lens exists in the package (as @Lens' Set (Maybe ())@@),
-- it's available only in most recent versions.
-- And using @Bool@ instead of @Maybe ()@ is more convenient.
atSet :: (Ord a) => a -> Lens' (S.Set a) Bool
atSet k = lensWith (S.member k) f
  where
    f s True False = S.delete k s
    f s False True = S.insert k s
    f s _ _        = s

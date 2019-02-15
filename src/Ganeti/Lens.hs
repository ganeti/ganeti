{-# LANGUAGE RankNTypes, CPP #-}

{-| Provides all lens-related functions.

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

module Ganeti.Lens
  ( module Control.Lens
  , lensWith
  , makeCustomLenses
  , makeCustomLenses'
  , traverseOf2
  , mapMOf2
  , atSet
  ) where

import Control.Applicative ((<$>), WrappedMonad(..))
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
    customRules = set lensField nameFun lensRules
#if MIN_VERSION_lens(4,5,0)
    nameFun :: Name -> [Name] -> Name -> [DefName]
    nameFun _ _ = liftM (TopName . mkName) . nameFilter . nameBase
#elif MIN_VERSION_lens(4,4,0)
    nameFun :: [Name] -> Name -> [DefName]
    nameFun _ = liftM (TopName . mkName) . nameFilter . nameBase
#else
    nameFun :: String -> Maybe String
    nameFun = nameFilter
#endif
    nameFilter :: (MonadPlus m) => String -> m String
    nameFilter = liftM lensFieldName . mfilter f . return

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

-- | Traverses over a composition of a monad and a functor.
-- See 'traverseOf2'.
mapMOf2 :: Over (->) (Compose (WrappedMonad m) g) s t a b
        -> (a -> m (g b)) -> s -> m (g t)
mapMOf2 k f = unwrapMonad . traverseOf2 k (WrapMonad . f)

-- | A helper lens over sets.
-- While a similar lens exists in the package (as @Lens' Set (Maybe ())@),
-- it's available only in most recent versions.
-- And using @Bool@ instead of @Maybe ()@ is more convenient.
atSet :: (Ord a) => a -> Lens' (S.Set a) Bool
atSet k = lensWith (S.member k) f
  where
    f s True False = S.delete k s
    f s False True = S.insert k s
    f s _ _        = s

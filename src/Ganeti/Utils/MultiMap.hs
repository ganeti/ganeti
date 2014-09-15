{-# LANGUAGE RankNTypes, TypeFamilies #-}

{-| Implements multi-maps - maps that map keys to sets of values

This module uses the standard naming convention as other collection-like
libraries and is meant to be imported qualified.

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

module Ganeti.Utils.MultiMap
  ( MultiMap()
  , multiMap
  , multiMapL
  , multiMapValueL
  , null
  , findValue
  , elem
  , lookup
  , member
  , insert
  , fromList
  , delete
  , deleteAll
  , values
  ) where

import Prelude hiding (lookup, null, elem)

import Control.Monad
import qualified Data.Foldable as F
import qualified Data.Map as M
import Data.Maybe (fromMaybe, isJust)
import Data.Monoid
import qualified Data.Set as S
import qualified Text.JSON as J

import Ganeti.Lens

-- | A multi-map that contains multiple values for a single key.
-- It doesn't distinguish non-existent keys and keys with the empty
-- set as the value.
newtype MultiMap k v = MultiMap { getMultiMap :: M.Map k (S.Set v) }
  deriving (Eq, Ord, Show)

instance (Ord v, Ord k) => Monoid (MultiMap k v) where
  mempty = MultiMap M.empty
  mappend (MultiMap x) (MultiMap y) = MultiMap $ M.unionWith S.union x y

instance F.Foldable (MultiMap k) where
  foldMap f = F.foldMap (F.foldMap f) . getMultiMap

instance (J.JSON k, Ord k, J.JSON v, Ord v) => J.JSON (MultiMap k v) where
  showJSON = J.showJSON . getMultiMap
  readJSON = liftM MultiMap . J.readJSON

-- | Creates a multi-map from a map of sets.
multiMap :: (Ord k, Ord v) => M.Map k (S.Set v) -> MultiMap k v
multiMap = MultiMap . M.filter (not . S.null)

-- | A 'Lens' that allows to access a set under a given key in a multi-map.
multiMapL :: (Ord k, Ord v) => k -> Lens' (MultiMap k v) (S.Set v)
multiMapL k f = fmap MultiMap
                 . at k (fmap (mfilter (not . S.null) . Just)
                         . f . fromMaybe S.empty)
                 . getMultiMap
{-# INLINE multiMapL #-}

-- | Return the set corresponding to a given key.
lookup :: (Ord k, Ord v) => k -> MultiMap k v -> S.Set v
lookup = view . multiMapL

-- | Tests if the given key has a non-empty set of values.
member :: (Ord k, Ord v) => k -> MultiMap k v -> Bool
member = (S.null .) . lookup

-- | Tries to find a key corresponding to a given value.
findValue :: (Ord k, Ord v) => v -> MultiMap k v -> Maybe k
findValue v = fmap fst . F.find (S.member v . snd) . M.toList . getMultiMap

-- | Returns 'True' iff a given value is present in a set of some key.
elem :: (Ord k, Ord v) => v -> MultiMap k v -> Bool
elem = (isJust .) . findValue

null :: MultiMap k v -> Bool
null = M.null . getMultiMap

insert :: (Ord k, Ord v) => k -> v -> MultiMap k v -> MultiMap k v
insert k v = set (multiMapValueL k v) True

fromList :: (Ord k, Ord v) => [(k, v)] -> MultiMap k v
fromList = foldr (uncurry insert) mempty

delete :: (Ord k, Ord v) => k -> v -> MultiMap k v -> MultiMap k v
delete k v = set (multiMapValueL k v) False

deleteAll :: (Ord k, Ord v) => k -> MultiMap k v -> MultiMap k v
deleteAll k = set (multiMapL k) S.empty

values :: (Ord k, Ord v) => MultiMap k v -> S.Set v
values =  F.fold . getMultiMap

-- | A 'Lens' that allows to access a given value/key pair in a multi-map.
--
-- It is similar to the 'At' instance, but uses more convenient 'Bool'
-- instead of 'Maybe ()' and a pair key/value.
multiMapValueL :: (Ord k, Ord v) => k -> v -> Lens' (MultiMap k v) Bool
multiMapValueL k v = multiMapL k . atSet v
{-# INLINE multiMapValueL #-}

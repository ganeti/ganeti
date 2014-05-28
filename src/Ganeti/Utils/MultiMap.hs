{-# LANGUAGE RankNTypes, TypeFamilies #-}

{-| Implements multi-maps - maps that map keys to sets of values

This module uses the standard naming convention as other collection-like
libraries and is meant to be imported qualified.

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

module Ganeti.Utils.MultiMap
  ( MultiMap()
  , multiMapL
  , multiMapValueL
  , null
  , findValue
  , elem
  , lookup
  , member
  , insert
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

{-| Module abstracting the peer map implementation.

This is abstracted separately since the speed of peermap updates can
be a significant part of the total runtime, and as such changing the
implementation should be easy in case it's needed.

-}

{-

Copyright (C) 2009 Google Inc.

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

module Ganeti.HTools.PeerMap
    ( PeerMap
    , Key
    , Elem
    , empty
    , accumArray
    , Ganeti.HTools.PeerMap.find
    , add
    , remove
    , maxElem
    ) where

import Data.Maybe (fromMaybe)
import Data.List
import Data.Ord (comparing)

import Ganeti.HTools.Types

-- * Type definitions

-- | Our key type.
type Key = Ndx

-- | Our element type.

type Elem = Int

-- | The definition of a peer map.
type PeerMap = [(Key, Elem)]

-- * Initialization functions

-- | Create a new empty map.
empty :: PeerMap
empty = []

-- | Our reverse-compare function.
pmCompare :: (Key, Elem) -> (Key, Elem) -> Ordering
pmCompare a b = comparing snd b a

-- | Add or update (via a custom function) an element.
addWith :: (Elem -> Elem -> Elem) -> Key -> Elem -> PeerMap -> PeerMap
addWith fn k v lst =
    case lookup k lst of
      Nothing -> insertBy pmCompare (k, v) lst
      Just o -> insertBy pmCompare (k, fn o v) (remove k lst)

-- | Create a PeerMap from an association list, with possible duplicates.
accumArray :: (Elem -> Elem -> Elem) -- ^ function used to merge the elements
              -> [(Key, Elem)]       -- ^ source data
              -> PeerMap             -- ^ results
accumArray _  [] = empty
accumArray fn ((k, v):xs) = addWith fn k v $ accumArray fn xs

-- * Basic operations

-- | Returns either the value for a key or zero if not found.
find :: Key -> PeerMap -> Elem
find k = fromMaybe 0 . lookup k

-- | Add an element to a peermap, overwriting the previous value.
add :: Key -> Elem -> PeerMap -> PeerMap
add = addWith (flip const)

-- | Remove an element from a peermap.
remove :: Key -> PeerMap -> PeerMap
remove _ [] = []
remove k ((x@(x', _)):xs) = if k == x'
                            then xs
                            else x:remove k xs

-- | Find the maximum element.
--
-- Since this is a sorted list, we just get the value at the head of
-- the list, or zero for a null list
maxElem :: PeerMap -> Elem
maxElem (x:_) = snd x
maxElem _ = 0

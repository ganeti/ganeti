{-| A data structure for measuring how many of a number of available slots are
taken.

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

module Ganeti.SlotMap
  ( Slot(..)
  , SlotMap
  , CountMap
  , toCountMap
  , isOverfull
  , occupySlots
  , hasSlotsFor
  ) where


import Data.Map (Map)
import qualified Data.Map as Map

{-# ANN module "HLint: ignore Avoid lambda" #-} -- to not suggest (`Slot` 0)


-- | A resource with [limit] available units and [occupied] of them taken.
data Slot = Slot
  { slotOccupied :: Int
  , slotLimit    :: Int
  } deriving (Eq, Ord, Show)


-- | A set of keys of type @a@ and how many slots are available and (to be)
-- occupied per key.
--
-- Some keys can be overfull (more slots occupied than available).
type SlotMap a = Map a Slot


-- | A set of keys of type @a@ and how many there are of each.
type CountMap a = Map a Int


-- | Turns a `SlotMap` into a `CountMap` by throwing away the limits.
toCountMap :: SlotMap a -> CountMap a
toCountMap = Map.map slotOccupied


-- | Whether any more slots are occupied than available.
isOverfull :: SlotMap a -> Bool
isOverfull m = or [ occup > limit | Slot occup limit <- Map.elems m ]


-- | Fill slots of a `SlotMap`s by adding the given counts.
-- Keys with counts that don't appear in the `SlotMap` get a limit of 0.
occupySlots :: (Ord a) => SlotMap a -> CountMap a -> SlotMap a
occupySlots sm counts = Map.unionWith
                          (\(Slot o l) (Slot n _) -> Slot (o + n) l)
                          sm
                          (Map.map (\n -> Slot n 0) counts)


-- | Whether the `SlotMap` has enough slots free to accomodate the given
-- counts.
--
-- The `SlotMap` is allowed to be overfull in some keys; this function
-- still returns True as long as as adding the counts to the `SlotMap` would
-- not *create or increase* overfull keys.
--
-- Adding counts > 0 for a key which is not in the `SlotMap` does create
-- overfull keys.
hasSlotsFor :: (Ord a) => SlotMap a -> CountMap a -> Bool
slotMap `hasSlotsFor` counts =
  let relevantSlots = slotMap `Map.intersection` counts
  in not $ isOverfull (relevantSlots `occupySlots` counts)

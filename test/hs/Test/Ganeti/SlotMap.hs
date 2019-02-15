{-# LANGUAGE TemplateHaskell, ScopedTypeVariables #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for the SlotMap.

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

module Test.Ganeti.SlotMap
  ( testSlotMap
  , genSlotLimit
  , genTestKey
  , overfullKeys
  ) where

import Prelude hiding (all)

import Control.Applicative
import Control.Monad
import Data.Foldable (all)
import qualified Data.Map as Map
import Data.Map (Map, member, keys, keysSet)
import Data.Set (Set, size, union)
import qualified Data.Set as Set
import Data.Traversable (traverse)
import Test.HUnit
import Test.QuickCheck

import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper
import Test.Ganeti.Types ()

import Ganeti.SlotMap

{-# ANN module "HLint: ignore Use camelCase" #-}


-- | Generates a number typical for the limit of a `Slot`.
-- Useful for constructing resource bounds when not directly constructing
-- the relevant `Slot`s.
genSlotLimit :: Gen Int
genSlotLimit = frequency [ (9, choose (1, 5))
                         , (1, choose (1, 100))
                         ] -- Don't create huge slot limits.


instance Arbitrary Slot where
  arbitrary = do
    limit <- genSlotLimit
    occ <- choose (0, limit * 2)
    return $ Slot occ limit


-- | Generates a number typical for the occupied count of a `Slot`.
-- Useful for constructing `CountMap`s.
genSlotCount :: Gen Int
genSlotCount = slotOccupied <$> arbitrary


-- | Takes a slot and resamples its `slotOccupied` count to fit the limit.
resampleFittingSlot :: Slot -> Gen Slot
resampleFittingSlot (Slot _ limit) = do
  occ <- choose (0, limit)
  return $ Slot occ limit


-- | What we use as key for testing `SlotMap`s.
type TestKey = String


-- | Generates short strings used as `SlotMap` keys.
--
-- We limit ourselves to a small set of key strings with high probability to
-- increase the chance that `SlotMap`s actually have more than one slot taken.
genTestKey :: Gen TestKey
genTestKey = frequency [ (9, elements ["a", "b", "c", "d", "e"])
                       , (1, genPrintableAsciiString)
                       ]


-- | Generates small lists.
listSizeGen :: Gen Int
listSizeGen = frequency [ (9, choose (1, 5))
                        , (1, choose (1, 100))
                        ]


-- | Generates a `SlotMap` given a generator for the keys (see `genTestKey`).
genSlotMap :: (Ord a) => Gen a -> Gen (SlotMap a)
genSlotMap keyGen = do
  n <- listSizeGen  -- don't create huge `SlotMap`s
  Map.fromList <$> vectorOf n ((,) <$> keyGen <*> arbitrary)


-- | Generates a `CountMap` given a generator for the keys (see `genTestKey`).
genCountMap :: (Ord a) => Gen a -> Gen (CountMap a)
genCountMap keyGen = do
  n <- listSizeGen  -- don't create huge `CountMap`s
  Map.fromList <$> vectorOf n ((,) <$> keyGen <*> genSlotCount)


-- | Tells which keys of a `SlotMap` are overfull.
overfullKeys :: (Ord a) => SlotMap a -> Set a
overfullKeys sm =
  Set.fromList [ a | (a, Slot occ limit) <- Map.toList sm, occ > limit ]


-- | Generates a `SlotMap` for which all slots are within their limits.
genFittingSlotMap :: (Ord a) => Gen a -> Gen (SlotMap a)
genFittingSlotMap keyGen = do
  -- Generate a SlotMap, then resample all slots to be fitting.
  slotMap <- traverse resampleFittingSlot =<< genSlotMap keyGen
  when (isOverfull slotMap) $ error "BUG: FittingSlotMap Gen is wrong"
  return slotMap


-- * Test cases

case_isOverfull :: Assertion
case_isOverfull = do

  assertBool "overfull"
    . isOverfull $ Map.fromList [("buck", Slot 3 2)]

  assertBool "not overfull"
    . not . isOverfull $ Map.fromList [("buck", Slot 2 2)]

  assertBool "empty"
    . not . isOverfull $ (Map.fromList [] :: SlotMap TestKey)


case_occupySlots_examples :: Assertion
case_occupySlots_examples = do
  let a n = ("a", Slot n 2)
  let b n = ("b", Slot n 4)

  let sm = Map.fromList [a 1, b 2]
      cm = Map.fromList [("a", 1), ("b", 1), ("c", 5)]

  assertEqual "fitting occupySlots"
    (sm `occupySlots` cm)
    (Map.fromList [a 2, b 3, ("c", Slot 5 0)])


-- | Union of the keys of two maps.
keyUnion :: (Ord a) => Map a b -> Map a c -> Set a
keyUnion a b = keysSet a `union` keysSet b


-- | Tests properties of `SlotMap`s being filled up.
prop_occupySlots :: Property
prop_occupySlots =
  forAll arbitrary $ \(sm :: SlotMap Int, cm :: CountMap Int) ->
    let smOcc = sm `occupySlots` cm
    in conjoin
         [ counterexample "input keys are preserved" $
             all (`member` smOcc) (keyUnion sm cm)
         , counterexample "all keys must come from the input keys" $
             all (`Set.member` keyUnion sm cm) (keys smOcc)
         ]


-- | Tests for whether there's still space for a job given its rate
-- limits.
case_hasSlotsFor_examples :: Assertion
case_hasSlotsFor_examples = do
  let a n = ("a", Slot n 2)
  let b n = ("b", Slot n 4)
  let c n = ("c", Slot n 8)

  let sm = Map.fromList [a 1, b 2]

  assertBool "fits" $
    sm `hasSlotsFor` Map.fromList [("a", 1), ("b", 1)]

  assertBool "doesn't fit"
    . not $ sm `hasSlotsFor` Map.fromList [("a", 1), ("b", 3)]

  let smOverfull = Map.fromList [a 1, b 2, c 10]

  assertBool "fits (untouched keys overfull)" $
    isOverfull smOverfull
      && smOverfull `hasSlotsFor` Map.fromList [("a", 1), ("b", 1)]

  assertBool "empty fitting" $
    Map.empty `hasSlotsFor` (Map.empty :: CountMap TestKey)

  assertBool "empty not fitting"
    . not $ Map.empty `hasSlotsFor` Map.fromList [("a", 1), ("b", 100)]

  assertBool "empty not fitting"
    . not $ Map.empty `hasSlotsFor` Map.fromList [("a", 1)]


-- | Tests properties of `hasSlotsFor` on `SlotMap`s that are known to
-- respect their limits.
prop_hasSlotsFor_fitting :: Property
prop_hasSlotsFor_fitting =
  forAll (genFittingSlotMap genTestKey) $ \sm ->
  forAll (genCountMap genTestKey) $ \cm ->
    sm `hasSlotsFor` cm ==? not (isOverfull $ sm `occupySlots` cm)


-- | Tests properties of `hasSlotsFor`, irrespective of whether the
-- input `SlotMap`s respect their limits or not.
prop_hasSlotsFor :: Property
prop_hasSlotsFor =
  let -- Generates `SlotMap`s for combining.
      genMaps = resize 10 $ do  -- We don't need very large SlotMaps.
        sm1 <- genSlotMap genTestKey
        -- We need to make sm2 smaller to make `hasSlots` below more
        -- likely (otherwise the LHS of ==> is always false).
        sm2 <- sized $ \n -> resize (n `div` 3) (genSlotMap genTestKey)
        -- We also want to test (sm1, sm1); we have to make it more
        -- likely for it to ever happen.
        frequency [ (1, return (sm1, sm1))
                  , (9, return (sm1, sm2)) ]

  in forAll genMaps $ \(sm1, sm2) ->
      let fits             = sm1 `hasSlotsFor` toCountMap sm2
          smOcc            = sm1 `occupySlots` toCountMap sm2
          oldOverfullBucks = overfullKeys sm1
          newOverfullBucks = overfullKeys smOcc
      in conjoin
           [ counterexample "if there's enough extra space, then the new\
                            \ overfull keys must be as before" $
             fits ==> (newOverfullBucks ==? oldOverfullBucks)
           -- Note that the other way around does not hold:
           --   (newOverfullBucks == oldOverfullBucks) ==> fits
           , counterexample "joining SlotMaps must not change the number of\
                            \ overfull keys (but may change their slot\
                            \ counts"
               . property $ size newOverfullBucks >= size oldOverfullBucks
           ]


testSuite "SlotMap"
            [ 'case_isOverfull
            , 'case_occupySlots_examples
            , 'prop_occupySlots
            , 'case_hasSlotsFor_examples
            , 'prop_hasSlotsFor_fitting
            , 'prop_hasSlotsFor
            ]

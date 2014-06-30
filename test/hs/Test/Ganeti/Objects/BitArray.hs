{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for bit arrays

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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

module Test.Ganeti.Objects.BitArray
  ( testObjects_BitArray
  , genBitArray
  ) where

import Test.QuickCheck

import Control.Applicative
import Control.Monad

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.Objects.BitArray as BA

-- * Arbitrary instances

instance Arbitrary BitArray where
  arbitrary = fromList <$> arbitrary

genBitArray :: Int -> Gen BitArray
genBitArray = liftA fromList . vector

prop_BitArray_serialisation :: BitArray -> Property
prop_BitArray_serialisation = testSerialisation

prop_BitArray_foldr :: [Bool] -> Property
prop_BitArray_foldr bs =
  BA.foldr (((:) .) . (,)) [] (fromList bs) ==? zip bs [0..]

prop_BitArray_fromToList :: BitArray -> Property
prop_BitArray_fromToList bs =
  BA.fromList (BA.toList bs) ==? bs

prop_BitArray_and :: [Bool] -> [Bool] -> Property
prop_BitArray_and xs ys =
  (BA.fromList xs -&- BA.fromList ys) ==? BA.fromList (zipWith (&&) xs ys)

prop_BitArray_or :: [Bool] -> [Bool] -> Property
prop_BitArray_or xs ys =
  let xsl = length xs
      ysl = length ys
      l = max xsl ysl
      comb = zipWith (||) (xs ++ replicate (l - xsl) False)
                          (ys ++ replicate (l - ysl) False)
  in (BA.fromList xs -|- BA.fromList ys) ==? BA.fromList comb

-- | Check that the counts of 1 bits holds.
prop_BitArray_counts :: Property
prop_BitArray_counts = do
    n <- choose (0, 3)
    ones <- replicateM n (lst True)
    zrs <- replicateM n (lst False)
    start <- lst False
    let count = sum . map length $ ones
        bs = start ++ concat (zipWith (++) ones zrs)
    count1 (BA.fromList bs) ==? count
  where
    lst x = (`replicate` x) `liftM` choose (0, 2)

-- | Check that the counts of free and occupied bits add up.
prop_BitArray_countsSum :: BitArray -> Property
prop_BitArray_countsSum a =
  count0 a + count1 a ==? size a

testSuite "Objects_BitArray"
  [ 'prop_BitArray_serialisation
  , 'prop_BitArray_foldr
  , 'prop_BitArray_fromToList
  , 'prop_BitArray_and
  , 'prop_BitArray_or
  , 'prop_BitArray_counts
  , 'prop_BitArray_countsSum
  ]

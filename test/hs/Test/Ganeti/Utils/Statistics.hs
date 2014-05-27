{-# LANGUAGE TemplateHaskell #-}

{-| Unit tests for Ganeti statistics utils.

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

module Test.Ganeti.Utils.Statistics (testUtils_Statistics) where

import Test.QuickCheck

import Test.Ganeti.TestHelper

import Ganeti.Utils (stdDev)
import Ganeti.Utils.Statistics

-- | Test the update function for standard deviations against the naive
-- implementation.
prop_stddev_update :: Property
prop_stddev_update =
  forAll (choose (0, 6) >>= flip vectorOf (choose (0, 1))) $ \xs ->
  forAll (choose (0, 1)) $ \a ->
  forAll (choose (0, 1)) $ \b ->
  forAll (choose (1, 6) >>= flip vectorOf (choose (0, 1))) $ \ys ->
  let original = xs ++ [a] ++ ys
      modified = xs ++ [b] ++ ys
      with_update = getStatisticValue
                    $ updateStatistics (getStdDevStatistics original) (a,b)
      direct = stdDev modified
  in printTestCase ("Value computed by update " ++ show with_update
                    ++ " differs too much from correct value " ++ show direct)
                   (abs (with_update - direct) < 1e-12)

testSuite "Utils/Statistics"
  [ 'prop_stddev_update
  ]

{-# LANGUAGE TemplateHaskell #-}

{-| Unit tests for Ganeti statistics utils.

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

module Test.Ganeti.Utils.Statistics (testUtils_Statistics) where

import Test.QuickCheck (Property, forAll, choose, vectorOf)

import Test.Ganeti.TestCommon
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
      with_update =
        getStatisticValue
        $ updateStatistics (getStdDevStatistics $ map SimpleNumber original)
                           (SimpleNumber a, SimpleNumber b)
      direct = stdDev modified
  in counterexample ("Value computed by update " ++ show with_update
                     ++ " differs too much from correct value " ++ show direct)
                    (abs (with_update - direct) < 1e-10)

testSuite "Utils/Statistics"
  [ 'prop_stddev_update
  ]

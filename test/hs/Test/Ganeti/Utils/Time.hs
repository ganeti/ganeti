{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for time utilities

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

module Test.Ganeti.Utils.Time
  ( testUtils_Time
  ) where

import Ganeti.Utils.Time
        (TimeDiff(TimeDiff), noTimeDiff,
         addToClockTime, diffClockTimes, clockTimeToString)
import System.Time (ClockTime(TOD))

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon


prop_clockTimeToString :: Integer -> Integer -> Property
prop_clockTimeToString ts pico =
  clockTimeToString (TOD ts pico) ==? show ts

genPicoseconds :: Gen Integer
genPicoseconds = choose (0, 999999999999)

genTimeDiff :: Gen TimeDiff
genTimeDiff = TimeDiff <$> arbitrary <*> genPicoseconds

genClockTime :: Gen ClockTime
genClockTime = TOD <$> choose (946681200, 2082754800) <*> genPicoseconds

prop_addToClockTime_identity :: Property
prop_addToClockTime_identity = forAll genClockTime addToClockTime_identity

addToClockTime_identity :: ClockTime -> Property
addToClockTime_identity a =
  addToClockTime noTimeDiff a ==? a

{- |
Verify our work-around for ghc bug #2519.
Taking `diffClockTimes` form `System.Time`, this test fails with an exception.
-}
prop_timediffAdd :: Property
prop_timediffAdd =
  forAll genClockTime $ \a ->
  forAll genClockTime $ \b ->
  forAll genClockTime $ \c -> timediffAdd a b c

timediffAdd :: ClockTime -> ClockTime -> ClockTime -> Property
timediffAdd a b c =
  let fwd = diffClockTimes a b
      back = diffClockTimes b a
  in addToClockTime fwd (addToClockTime back c) ==? c

prop_timediffAddCommutative :: Property
prop_timediffAddCommutative =
  forAll genTimeDiff $ \a ->
  forAll genTimeDiff $ \b ->
  forAll genClockTime $ \c -> timediffAddCommutative a b c

timediffAddCommutative :: TimeDiff -> TimeDiff -> ClockTime -> Property
timediffAddCommutative a b c =
  addToClockTime a (addToClockTime b c)
  ==?
  addToClockTime b (addToClockTime a c)


testSuite "Utils/Time"
  [ 'prop_clockTimeToString
  , 'prop_addToClockTime_identity
  , 'prop_timediffAdd
  , 'prop_timediffAddCommutative
  ]

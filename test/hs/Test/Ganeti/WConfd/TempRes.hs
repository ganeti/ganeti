{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Tests for temporary configuration resources allocation

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

module Test.Ganeti.WConfd.TempRes (testWConfd_TempRes) where

import Control.Applicative

import Test.QuickCheck

import Test.Ganeti.Objects ()
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper

import Test.Ganeti.Locking.Locks () -- the JSON ClientId instance
import Test.Ganeti.Utils.MultiMap ()

import Ganeti.WConfd.TempRes

-- * Instances

instance Arbitrary IPv4ResAction where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary IPv4Reservation where
  arbitrary = IPv4Res <$> arbitrary <*> arbitrary <*> arbitrary

instance (Arbitrary k, Ord k, Arbitrary v, Ord v)
         => Arbitrary (TempRes k v) where
  arbitrary = mkTempRes <$> arbitrary

instance Arbitrary TempResState where
  arbitrary = TempResState <$> genMap arbitrary (genMap arbitrary arbitrary)
                           <*> arbitrary
                           <*> arbitrary
                           <*> arbitrary
                           <*> arbitrary

-- * Tests

prop_IPv4Reservation_serialisation :: IPv4Reservation -> Property
prop_IPv4Reservation_serialisation = testSerialisation

prop_TempRes_serialisation :: TempRes Int Int -> Property
prop_TempRes_serialisation = testSerialisation

-- * The tests combined

testSuite "WConfd/TempRes"
 [ 'prop_IPv4Reservation_serialisation
 , 'prop_TempRes_serialisation
 ]

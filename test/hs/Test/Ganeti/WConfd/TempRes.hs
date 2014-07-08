{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Tests for temporary configuration resources allocation

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

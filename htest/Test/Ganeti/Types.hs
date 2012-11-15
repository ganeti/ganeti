{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for 'Ganeti.Types'.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Test.Ganeti.Types
  ( testTypes
  , AllocPolicy(..)
  , DiskTemplate(..)
  , InstanceStatus(..)
  , NonEmpty(..)
  ) where

import Test.QuickCheck as QuickCheck hiding (Result)
import Test.HUnit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.BasicTypes
import Ganeti.Types as Types

-- * Arbitrary instance

instance (Arbitrary a, Ord a, Num a, Show a) =>
  Arbitrary (Types.Positive a) where
  arbitrary = do
    (QuickCheck.Positive i) <- arbitrary
    Types.mkPositive i

$(genArbitrary ''AllocPolicy)

$(genArbitrary ''DiskTemplate)

$(genArbitrary ''InstanceStatus)

instance (Arbitrary a) => Arbitrary (Types.NonEmpty a) where
  arbitrary = do
    QuickCheck.NonEmpty lst <- arbitrary
    Types.mkNonEmpty lst

prop_AllocPolicy_serialisation :: AllocPolicy -> Property
prop_AllocPolicy_serialisation = testSerialisation

prop_DiskTemplate_serialisation :: DiskTemplate -> Property
prop_DiskTemplate_serialisation = testSerialisation

prop_InstanceStatus_serialisation :: InstanceStatus -> Property
prop_InstanceStatus_serialisation = testSerialisation

-- | Tests building non-negative numbers.
prop_NonNeg_pass :: QuickCheck.NonNegative Int -> Property
prop_NonNeg_pass (QuickCheck.NonNegative i) =
  case mkNonNegative i of
    Bad msg -> failTest $ "Fail to build non-negative: " ++ msg
    Ok nn -> fromNonNegative nn ==? i

-- | Tests building non-negative numbers.
prop_NonNeg_fail :: QuickCheck.Positive Int -> Property
prop_NonNeg_fail (QuickCheck.Positive i) =
  case mkNonNegative (negate i)::Result (Types.NonNegative Int) of
    Bad _ -> passTest
    Ok nn -> failTest $ "Built non-negative number '" ++ show nn ++
             "' from negative value " ++ show i

-- | Tests building positive numbers.
prop_Positive_pass :: QuickCheck.Positive Int -> Property
prop_Positive_pass (QuickCheck.Positive i) =
  case mkPositive i of
    Bad msg -> failTest $ "Fail to build positive: " ++ msg
    Ok nn -> fromPositive nn ==? i

-- | Tests building positive numbers.
prop_Positive_fail :: QuickCheck.NonNegative Int -> Property
prop_Positive_fail (QuickCheck.NonNegative i) =
  case mkPositive (negate i)::Result (Types.Positive Int) of
    Bad _ -> passTest
    Ok nn -> failTest $ "Built positive number '" ++ show nn ++
             "' from negative or zero value " ++ show i

-- | Tests building non-empty lists.
prop_NonEmpty_pass :: QuickCheck.NonEmptyList [Char] -> Property
prop_NonEmpty_pass (QuickCheck.NonEmpty xs) =
  case mkNonEmpty xs of
    Bad msg -> failTest $ "Fail to build non-empty list: " ++ msg
    Ok nn -> fromNonEmpty nn ==? xs

-- | Tests building positive numbers.
case_NonEmpty_fail :: Assertion
case_NonEmpty_fail = do
  assertEqual "building non-empty list from an empty list"
    (Bad "Received empty value for non-empty list") (mkNonEmpty ([]::[Int]))

testSuite "Types"
  [ 'prop_AllocPolicy_serialisation
  , 'prop_DiskTemplate_serialisation
  , 'prop_InstanceStatus_serialisation
  , 'prop_NonNeg_pass
  , 'prop_NonNeg_fail
  , 'prop_Positive_pass
  , 'prop_Positive_fail
  , 'prop_NonEmpty_pass
  , 'case_NonEmpty_fail
  ]

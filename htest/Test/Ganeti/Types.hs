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
  , Hypervisor(..)
  ) where

import Data.List (sort)
import Test.QuickCheck as QuickCheck hiding (Result)
import Test.HUnit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Types as Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitrary instance

instance (Arbitrary a, Ord a, Num a, Show a) =>
  Arbitrary (Types.Positive a) where
  arbitrary = do
    (QuickCheck.Positive i) <- arbitrary
    Types.mkPositive i

$(genArbitrary ''AllocPolicy)

$(genArbitrary ''DiskTemplate)

$(genArbitrary ''InstanceStatus)

$(genArbitrary ''MigrationMode)

$(genArbitrary ''VerifyOptionalChecks)

$(genArbitrary ''DdmSimple)

$(genArbitrary ''CVErrorCode)

$(genArbitrary ''Hypervisor)

$(genArbitrary ''StorageType)

instance (Arbitrary a) => Arbitrary (Types.NonEmpty a) where
  arbitrary = do
    QuickCheck.NonEmpty lst <- arbitrary
    Types.mkNonEmpty lst

-- * Properties

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
prop_NonEmpty_pass :: QuickCheck.NonEmptyList String -> Property
prop_NonEmpty_pass (QuickCheck.NonEmpty xs) =
  case mkNonEmpty xs of
    Bad msg -> failTest $ "Fail to build non-empty list: " ++ msg
    Ok nn -> fromNonEmpty nn ==? xs

-- | Tests building positive numbers.
case_NonEmpty_fail :: Assertion
case_NonEmpty_fail =
  assertEqual "building non-empty list from an empty list"
    (Bad "Received empty value for non-empty list") (mkNonEmpty ([]::[Int]))

-- | Tests migration mode serialisation.
prop_MigrationMode_serialisation :: MigrationMode -> Property
prop_MigrationMode_serialisation = testSerialisation

-- | Tests verify optional checks serialisation.
prop_VerifyOptionalChecks_serialisation :: VerifyOptionalChecks -> Property
prop_VerifyOptionalChecks_serialisation = testSerialisation

-- | Tests 'DdmSimple' serialisation.
prop_DdmSimple_serialisation :: DdmSimple -> Property
prop_DdmSimple_serialisation = testSerialisation

-- | Tests 'CVErrorCode' serialisation.
prop_CVErrorCode_serialisation :: CVErrorCode -> Property
prop_CVErrorCode_serialisation = testSerialisation

-- | Tests equivalence with Python, based on Constants.hs code.
case_CVErrorCode_pyequiv :: Assertion
case_CVErrorCode_pyequiv = do
  let all_py_codes = sort C.cvAllEcodesStrings
      all_hs_codes = sort $ map Types.cVErrorCodeToRaw [minBound..maxBound]
  assertEqual "for CVErrorCode equivalence" all_py_codes all_hs_codes

-- | Test 'Hypervisor' serialisation.
prop_Hypervisor_serialisation :: Hypervisor -> Property
prop_Hypervisor_serialisation = testSerialisation

-- | Test 'StorageType' serialisation.
prop_StorageType_serialisation :: StorageType -> Property
prop_StorageType_serialisation = testSerialisation

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
  , 'prop_MigrationMode_serialisation
  , 'prop_VerifyOptionalChecks_serialisation
  , 'prop_DdmSimple_serialisation
  , 'prop_CVErrorCode_serialisation
  , 'case_CVErrorCode_pyequiv
  , 'prop_Hypervisor_serialisation
  , 'prop_StorageType_serialisation
  ]

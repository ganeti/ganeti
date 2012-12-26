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
  , JobId(..)
  ) where

import Data.List (sort)
import Test.QuickCheck as QuickCheck hiding (Result)
import Test.HUnit
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Types as Types
import Ganeti.JSON

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitrary instance

instance (Arbitrary a, Ord a, Num a, Show a) =>
  Arbitrary (Types.Positive a) where
  arbitrary = do
    (QuickCheck.Positive i) <- arbitrary
    Types.mkPositive i

instance (Arbitrary a, Ord a, Num a, Show a) =>
  Arbitrary (Types.NonNegative a) where
  arbitrary = do
    (QuickCheck.NonNegative i) <- arbitrary
    Types.mkNonNegative i

instance (Arbitrary a, Ord a, Num a, Show a) =>
  Arbitrary (Types.Negative a) where
  arbitrary = do
    (QuickCheck.Positive i) <- arbitrary
    Types.mkNegative $ negate i

instance (Arbitrary a) => Arbitrary (Types.NonEmpty a) where
  arbitrary = do
    QuickCheck.NonEmpty lst <- arbitrary
    Types.mkNonEmpty lst

$(genArbitrary ''AllocPolicy)

$(genArbitrary ''DiskTemplate)

$(genArbitrary ''InstanceStatus)

$(genArbitrary ''MigrationMode)

$(genArbitrary ''VerifyOptionalChecks)

$(genArbitrary ''DdmSimple)

$(genArbitrary ''DdmFull)

$(genArbitrary ''CVErrorCode)

$(genArbitrary ''Hypervisor)

$(genArbitrary ''OobCommand)

$(genArbitrary ''StorageType)

$(genArbitrary ''NodeEvacMode)

$(genArbitrary ''FileDriver)

$(genArbitrary ''InstCreateMode)

$(genArbitrary ''RebootType)

$(genArbitrary ''ExportMode)

$(genArbitrary ''IAllocatorTestDir)

$(genArbitrary ''IAllocatorMode)

$(genArbitrary ''NetworkType)

$(genArbitrary ''NICMode)

$(genArbitrary ''JobStatus)

$(genArbitrary ''FinalizedJobStatus)

instance Arbitrary JobId where
  arbitrary = do
    (Positive i) <- arbitrary
    makeJobId i

$(genArbitrary ''JobIdDep)

$(genArbitrary ''JobDependency)

$(genArbitrary ''OpSubmitPriority)

$(genArbitrary ''OpStatus)

$(genArbitrary ''ELogType)

-- * Properties

prop_AllocPolicy_serialisation :: AllocPolicy -> Property
prop_AllocPolicy_serialisation = testSerialisation

-- | Test 'AllocPolicy' ordering is as expected.
case_AllocPolicy_order :: Assertion
case_AllocPolicy_order =
  assertEqual "sort order" [ Types.AllocPreferred
                           , Types.AllocLastResort
                           , Types.AllocUnallocable
                           ] [minBound..maxBound]

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

-- | Tests building negative numbers.
prop_Neg_pass :: QuickCheck.Positive Int -> Property
prop_Neg_pass (QuickCheck.Positive i) =
  case mkNegative i' of
    Bad msg -> failTest $ "Fail to build negative: " ++ msg
    Ok nn -> fromNegative nn ==? i'
  where i' = negate i

-- | Tests building negative numbers.
prop_Neg_fail :: QuickCheck.NonNegative Int -> Property
prop_Neg_fail (QuickCheck.NonNegative i) =
  case mkNegative i::Result (Types.Negative Int) of
    Bad _ -> passTest
    Ok nn -> failTest $ "Built negative number '" ++ show nn ++
             "' from non-negative value " ++ show i

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

-- | Tests 'DdmFull' serialisation.
prop_DdmFull_serialisation :: DdmFull -> Property
prop_DdmFull_serialisation = testSerialisation

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

-- | Test 'OobCommand' serialisation.
prop_OobCommand_serialisation :: OobCommand -> Property
prop_OobCommand_serialisation = testSerialisation

-- | Test 'StorageType' serialisation.
prop_StorageType_serialisation :: StorageType -> Property
prop_StorageType_serialisation = testSerialisation

-- | Test 'NodeEvacMode' serialisation.
prop_NodeEvacMode_serialisation :: NodeEvacMode -> Property
prop_NodeEvacMode_serialisation = testSerialisation

-- | Test 'FileDriver' serialisation.
prop_FileDriver_serialisation :: FileDriver -> Property
prop_FileDriver_serialisation = testSerialisation

-- | Test 'InstCreate' serialisation.
prop_InstCreateMode_serialisation :: InstCreateMode -> Property
prop_InstCreateMode_serialisation = testSerialisation

-- | Test 'RebootType' serialisation.
prop_RebootType_serialisation :: RebootType -> Property
prop_RebootType_serialisation = testSerialisation

-- | Test 'ExportMode' serialisation.
prop_ExportMode_serialisation :: ExportMode -> Property
prop_ExportMode_serialisation = testSerialisation

-- | Test 'IAllocatorTestDir' serialisation.
prop_IAllocatorTestDir_serialisation :: IAllocatorTestDir -> Property
prop_IAllocatorTestDir_serialisation = testSerialisation

-- | Test 'IAllocatorMode' serialisation.
prop_IAllocatorMode_serialisation :: IAllocatorMode -> Property
prop_IAllocatorMode_serialisation = testSerialisation

-- | Tests equivalence with Python, based on Constants.hs code.
case_IAllocatorMode_pyequiv :: Assertion
case_IAllocatorMode_pyequiv = do
  let all_py_codes = sort C.validIallocatorModes
      all_hs_codes = sort $ map Types.iAllocatorModeToRaw [minBound..maxBound]
  assertEqual "for IAllocatorMode equivalence" all_py_codes all_hs_codes

-- | Test 'NetworkType' serialisation.
prop_NetworkType_serialisation :: NetworkType -> Property
prop_NetworkType_serialisation = testSerialisation

-- | Tests equivalence with Python, based on Constants.hs code.
case_NetworkType_pyequiv :: Assertion
case_NetworkType_pyequiv = do
  let all_py_codes = sort C.networkValidTypes
      all_hs_codes = sort $ map Types.networkTypeToRaw [minBound..maxBound]
  assertEqual "for NetworkType equivalence" all_py_codes all_hs_codes

-- | Test 'NICMode' serialisation.
prop_NICMode_serialisation :: NICMode -> Property
prop_NICMode_serialisation = testSerialisation

-- | Test 'OpStatus' serialisation.
prop_OpStatus_serialization :: OpStatus -> Property
prop_OpStatus_serialization = testSerialisation

-- | Test 'JobStatus' serialisation.
prop_JobStatus_serialization :: JobStatus -> Property
prop_JobStatus_serialization = testSerialisation

-- | Test 'JobStatus' ordering is as expected.
case_JobStatus_order :: Assertion
case_JobStatus_order =
  assertEqual "sort order" [ Types.JOB_STATUS_QUEUED
                           , Types.JOB_STATUS_WAITING
                           , Types.JOB_STATUS_CANCELING
                           , Types.JOB_STATUS_RUNNING
                           , Types.JOB_STATUS_CANCELED
                           , Types.JOB_STATUS_SUCCESS
                           , Types.JOB_STATUS_ERROR
                           ] [minBound..maxBound]

-- | Tests equivalence with Python, based on Constants.hs code.
case_NICMode_pyequiv :: Assertion
case_NICMode_pyequiv = do
  let all_py_codes = sort C.nicValidModes
      all_hs_codes = sort $ map Types.nICModeToRaw [minBound..maxBound]
  assertEqual "for NICMode equivalence" all_py_codes all_hs_codes

-- | Test 'FinalizedJobStatus' serialisation.
prop_FinalizedJobStatus_serialisation :: FinalizedJobStatus -> Property
prop_FinalizedJobStatus_serialisation = testSerialisation

-- | Tests equivalence with Python, based on Constants.hs code.
case_FinalizedJobStatus_pyequiv :: Assertion
case_FinalizedJobStatus_pyequiv = do
  let all_py_codes = sort C.jobsFinalized
      all_hs_codes = sort $ map Types.finalizedJobStatusToRaw
                            [minBound..maxBound]
  assertEqual "for FinalizedJobStatus equivalence" all_py_codes all_hs_codes

-- | Tests JobId serialisation (both from string and ints).
prop_JobId_serialisation :: JobId -> Property
prop_JobId_serialisation jid =
  conjoin [ testSerialisation jid
          , (J.readJSON . J.showJSON . show $ fromJobId jid) ==? J.Ok jid
          , case (fromJVal . J.showJSON . negate $
                  fromJobId jid)::Result JobId of
              Bad _ -> passTest
              Ok jid' -> failTest $ "Parsed negative job id as id " ++
                         show (fromJobId jid')
          ]

-- | Tests that fractional job IDs are not accepted.
prop_JobId_fractional :: Property
prop_JobId_fractional =
  forAll (arbitrary `suchThat`
          (\d -> fromIntegral (truncate d::Int) /= d)) $ \d ->
  case J.readJSON (J.showJSON (d::Double)) of
    J.Error _ -> passTest
    J.Ok jid -> failTest $ "Parsed fractional value " ++ show d ++
                " as job id " ++ show (fromJobId jid)

-- | Tests that a job ID is not parseable from \"bad\" JSON values.
case_JobId_BadTypes :: Assertion
case_JobId_BadTypes = do
  let helper jsval = case J.readJSON jsval of
                       J.Error _ -> return ()
                       J.Ok jid -> assertFailure $ "Parsed " ++ show jsval
                                   ++ " as job id " ++ show (fromJobId jid)
  helper J.JSNull
  helper (J.JSBool True)
  helper (J.JSBool False)
  helper (J.JSArray [])

-- | Test 'JobDependency' serialisation.
prop_JobDependency_serialisation :: JobDependency -> Property
prop_JobDependency_serialisation = testSerialisation

-- | Test 'OpSubmitPriority' serialisation.
prop_OpSubmitPriority_serialisation :: OpSubmitPriority -> Property
prop_OpSubmitPriority_serialisation = testSerialisation

-- | Test 'ELogType' serialisation.
prop_ELogType_serialisation :: ELogType -> Property
prop_ELogType_serialisation = testSerialisation

testSuite "Types"
  [ 'prop_AllocPolicy_serialisation
  , 'case_AllocPolicy_order
  , 'prop_DiskTemplate_serialisation
  , 'prop_InstanceStatus_serialisation
  , 'prop_NonNeg_pass
  , 'prop_NonNeg_fail
  , 'prop_Positive_pass
  , 'prop_Positive_fail
  , 'prop_Neg_pass
  , 'prop_Neg_fail
  , 'prop_NonEmpty_pass
  , 'case_NonEmpty_fail
  , 'prop_MigrationMode_serialisation
  , 'prop_VerifyOptionalChecks_serialisation
  , 'prop_DdmSimple_serialisation
  , 'prop_DdmFull_serialisation
  , 'prop_CVErrorCode_serialisation
  , 'case_CVErrorCode_pyequiv
  , 'prop_Hypervisor_serialisation
  , 'prop_OobCommand_serialisation
  , 'prop_StorageType_serialisation
  , 'prop_NodeEvacMode_serialisation
  , 'prop_FileDriver_serialisation
  , 'prop_InstCreateMode_serialisation
  , 'prop_RebootType_serialisation
  , 'prop_ExportMode_serialisation
  , 'prop_IAllocatorTestDir_serialisation
  , 'prop_IAllocatorMode_serialisation
  , 'case_IAllocatorMode_pyequiv
  , 'prop_NetworkType_serialisation
  , 'case_NetworkType_pyequiv
  , 'prop_NICMode_serialisation
  , 'prop_OpStatus_serialization
  , 'prop_JobStatus_serialization
  , 'case_JobStatus_order
  , 'case_NICMode_pyequiv
  , 'prop_FinalizedJobStatus_serialisation
  , 'case_FinalizedJobStatus_pyequiv
  , 'prop_JobId_serialisation
  , 'prop_JobId_fractional
  , 'case_JobId_BadTypes
  , 'prop_JobDependency_serialisation
  , 'prop_OpSubmitPriority_serialisation
  , 'prop_ELogType_serialisation
  ]

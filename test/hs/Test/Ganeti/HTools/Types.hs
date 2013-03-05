{-# LANGUAGE TemplateHaskell, FlexibleInstances, TypeSynonymInstances #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

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

module Test.Ganeti.HTools.Types
  ( testHTools_Types
  , Types.AllocPolicy(..)
  , Types.DiskTemplate(..)
  , Types.FailMode(..)
  , Types.EvacMode(..)
  , Types.ISpec(..)
  , Types.IPolicy(..)
  , nullIPolicy
  ) where

import Test.QuickCheck hiding (Result)
import Test.HUnit

import Control.Applicative
import Data.List (sort)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools
import Test.Ganeti.Types (allDiskTemplates)

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import qualified Ganeti.HTools.Types as Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Helpers

-- * Arbitrary instance

$(genArbitrary ''Types.FailMode)

$(genArbitrary ''Types.EvacMode)

instance Arbitrary a => Arbitrary (Types.OpResult a) where
  arbitrary = arbitrary >>= \c ->
              if c
                then Ok  <$> arbitrary
                else Bad <$> arbitrary

instance Arbitrary Types.ISpec where
  arbitrary = do
    mem_s <- arbitrary::Gen (NonNegative Int)
    dsk_c <- arbitrary::Gen (NonNegative Int)
    dsk_s <- arbitrary::Gen (NonNegative Int)
    cpu_c <- arbitrary::Gen (NonNegative Int)
    nic_c <- arbitrary::Gen (NonNegative Int)
    su    <- arbitrary::Gen (NonNegative Int)
    return Types.ISpec { Types.iSpecMemorySize = fromIntegral mem_s
                       , Types.iSpecCpuCount   = fromIntegral cpu_c
                       , Types.iSpecDiskSize   = fromIntegral dsk_s
                       , Types.iSpecDiskCount  = fromIntegral dsk_c
                       , Types.iSpecNicCount   = fromIntegral nic_c
                       , Types.iSpecSpindleUse = fromIntegral su
                       }

-- | Generates an ispec bigger than the given one.
genBiggerISpec :: Types.ISpec -> Gen Types.ISpec
genBiggerISpec imin = do
  mem_s <- choose (Types.iSpecMemorySize imin, maxBound)
  dsk_c <- choose (Types.iSpecDiskCount imin, maxBound)
  dsk_s <- choose (Types.iSpecDiskSize imin, maxBound)
  cpu_c <- choose (Types.iSpecCpuCount imin, maxBound)
  nic_c <- choose (Types.iSpecNicCount imin, maxBound)
  su    <- choose (Types.iSpecSpindleUse imin, maxBound)
  return Types.ISpec { Types.iSpecMemorySize = fromIntegral mem_s
                     , Types.iSpecCpuCount   = fromIntegral cpu_c
                     , Types.iSpecDiskSize   = fromIntegral dsk_s
                     , Types.iSpecDiskCount  = fromIntegral dsk_c
                     , Types.iSpecNicCount   = fromIntegral nic_c
                     , Types.iSpecSpindleUse = fromIntegral su
                     }

instance Arbitrary Types.IPolicy where
  arbitrary = do
    imin <- arbitrary
    istd <- genBiggerISpec imin
    imax <- genBiggerISpec istd
    num_tmpl <- choose (0, length allDiskTemplates)
    dts  <- genUniquesList num_tmpl arbitrary
    vcpu_ratio <- choose (1.0, maxVcpuRatio)
    spindle_ratio <- choose (1.0, maxSpindleRatio)
    return Types.IPolicy { Types.iPolicyMinSpec = imin
                         , Types.iPolicyStdSpec = istd
                         , Types.iPolicyMaxSpec = imax
                         , Types.iPolicyDiskTemplates = dts
                         , Types.iPolicyVcpuRatio = vcpu_ratio
                         , Types.iPolicySpindleRatio = spindle_ratio
                         }

-- * Test cases

prop_ISpec_serialisation :: Types.ISpec -> Property
prop_ISpec_serialisation = testSerialisation

prop_IPolicy_serialisation :: Types.IPolicy -> Property
prop_IPolicy_serialisation = testSerialisation

prop_EvacMode_serialisation :: Types.EvacMode -> Property
prop_EvacMode_serialisation = testSerialisation

prop_opToResult :: Types.OpResult Int -> Property
prop_opToResult op =
  case op of
    Bad _ -> printTestCase ("expected bad but got " ++ show r) $ isBad r
    Ok v  -> case r of
               Bad msg -> failTest ("expected Ok but got Bad " ++ msg)
               Ok v' -> v ==? v'
  where r = Types.opToResult op

prop_eitherToResult :: Either String Int -> Bool
prop_eitherToResult ei =
  case ei of
    Left _ -> isBad r
    Right v -> case r of
                 Bad _ -> False
                 Ok v' -> v == v'
    where r = eitherToResult ei

-- | Test 'AutoRepairType' ordering is as expected and consistent with Python
-- codebase.
case_AutoRepairType_sort :: Assertion
case_AutoRepairType_sort = do
  let expected = [ Types.ArFixStorage
                 , Types.ArMigrate
                 , Types.ArFailover
                 , Types.ArReinstall
                 ]
      all_hs_raw = map Types.autoRepairTypeToRaw [minBound..maxBound]
  assertEqual "Haskell order" expected [minBound..maxBound]
  assertEqual "consistent with Python" C.autoRepairAllTypes all_hs_raw

-- | Test 'AutoRepairResult' type is equivalent with Python codebase.
case_AutoRepairResult_pyequiv :: Assertion
case_AutoRepairResult_pyequiv = do
  let all_py_results = sort C.autoRepairAllResults
      all_hs_results = sort $
                       map Types.autoRepairResultToRaw [minBound..maxBound]
  assertEqual "for AutoRepairResult equivalence" all_py_results all_hs_results

testSuite "HTools/Types"
            [ 'prop_ISpec_serialisation
            , 'prop_IPolicy_serialisation
            , 'prop_EvacMode_serialisation
            , 'prop_opToResult
            , 'prop_eitherToResult
            , 'case_AutoRepairType_sort
            , 'case_AutoRepairResult_pyequiv
            ]

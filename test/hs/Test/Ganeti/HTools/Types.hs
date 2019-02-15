{-# LANGUAGE TemplateHaskell, FlexibleInstances, TypeSynonymInstances #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Test.Ganeti.HTools.Types
  ( testHTools_Types
  , Types.AllocPolicy(..)
  , Types.DiskTemplate(..)
  , Types.FailMode(..)
  , Types.ISpec(..)
  , Types.IPolicy(..)
  , nullIPolicy
  ) where

import Test.QuickCheck hiding (Result)
import Test.HUnit

import Control.Applicative
import Control.Monad (replicateM)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools
import Test.Ganeti.Types (allDiskTemplates)

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.ConstantUtils
import qualified Ganeti.HTools.Types as Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Helpers

-- * Arbitrary instance

$(genArbitrary ''Types.FailMode)

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
    return Types.ISpec { Types.iSpecMemorySize = fromEnum mem_s
                       , Types.iSpecCpuCount   = fromEnum cpu_c
                       , Types.iSpecDiskSize   = fromEnum dsk_s
                       , Types.iSpecDiskCount  = fromEnum dsk_c
                       , Types.iSpecNicCount   = fromEnum nic_c
                       , Types.iSpecSpindleUse = fromEnum su
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
  return Types.ISpec { Types.iSpecMemorySize = fromEnum mem_s
                     , Types.iSpecCpuCount   = fromEnum cpu_c
                     , Types.iSpecDiskSize   = fromEnum dsk_s
                     , Types.iSpecDiskCount  = fromEnum dsk_c
                     , Types.iSpecNicCount   = fromEnum nic_c
                     , Types.iSpecSpindleUse = fromEnum su
                     }

genMinMaxISpecs :: Gen Types.MinMaxISpecs
genMinMaxISpecs = do
  imin <- arbitrary
  imax <- genBiggerISpec imin
  return Types.MinMaxISpecs { Types.minMaxISpecsMinSpec = imin
                             , Types.minMaxISpecsMaxSpec = imax
                             }

instance Arbitrary Types.MinMaxISpecs where
  arbitrary = genMinMaxISpecs

genMinMaxStdISpecs :: Gen (Types.MinMaxISpecs, Types.ISpec)
genMinMaxStdISpecs = do
  imin <- arbitrary
  istd <- genBiggerISpec imin
  imax <- genBiggerISpec istd
  return (Types.MinMaxISpecs { Types.minMaxISpecsMinSpec = imin
                             , Types.minMaxISpecsMaxSpec = imax
                             },
          istd)

genIPolicySpecs :: Gen ([Types.MinMaxISpecs], Types.ISpec)
genIPolicySpecs = do
  num_mm <- choose (1, 6) -- 6 is just an arbitrary limit
  std_compl <- choose (1, num_mm)
  mm_head <- replicateM (std_compl - 1) genMinMaxISpecs
  (mm_middle, istd) <- genMinMaxStdISpecs
  mm_tail <- replicateM (num_mm - std_compl) genMinMaxISpecs
  return (mm_head ++ (mm_middle : mm_tail), istd)


instance Arbitrary Types.IPolicy where
  arbitrary = do
    (iminmax, istd) <- genIPolicySpecs
    num_tmpl <- choose (0, length allDiskTemplates)
    dts  <- genUniquesList num_tmpl arbitrary
    vcpu_ratio <- choose (1.0, maxVcpuRatio)
    spindle_ratio <- choose (1.0, maxSpindleRatio)
    return Types.IPolicy { Types.iPolicyMinMaxISpecs = iminmax
                         , Types.iPolicyStdSpec = istd
                         , Types.iPolicyDiskTemplates = dts
                         , Types.iPolicyVcpuRatio = vcpu_ratio
                         , Types.iPolicySpindleRatio = spindle_ratio
                         }

-- * Test cases

prop_ISpec_serialisation :: Types.ISpec -> Property
prop_ISpec_serialisation = testSerialisation

prop_IPolicy_serialisation :: Types.IPolicy -> Property
prop_IPolicy_serialisation = testSerialisation

prop_opToResult :: Types.OpResult Int -> Property
prop_opToResult op =
  case op of
    Bad _ -> counterexample ("expected bad but got " ++ show r) $ isBad r
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
    where r = eitherToResult ei :: Result Int

-- | Test 'AutoRepairType' ordering is as expected and consistent with Python
-- codebase.
case_AutoRepairType_sort :: Assertion
case_AutoRepairType_sort = do
  let expected = [ Types.ArFixStorage
                 , Types.ArMigrate
                 , Types.ArFailover
                 , Types.ArReinstall
                 ]
      all_hs_raw = mkSet $ map Types.autoRepairTypeToRaw [minBound..maxBound]
  assertEqual "Haskell order" expected [minBound..maxBound]
  assertEqual "consistent with Python" C.autoRepairAllTypes all_hs_raw

-- | Test 'AutoRepairResult' type is equivalent with Python codebase.
case_AutoRepairResult_pyequiv :: Assertion
case_AutoRepairResult_pyequiv = do
  let all_py_results = C.autoRepairAllResults
      all_hs_results = mkSet $
                       map Types.autoRepairResultToRaw [minBound..maxBound]
  assertEqual "for AutoRepairResult equivalence" all_py_results all_hs_results

testSuite "HTools/Types"
            [ 'prop_ISpec_serialisation
            , 'prop_IPolicy_serialisation
            , 'prop_opToResult
            , 'prop_eitherToResult
            , 'case_AutoRepairType_sort
            , 'case_AutoRepairResult_pyequiv
            ]

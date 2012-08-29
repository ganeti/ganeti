{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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
  ( testTypes
  , Types.AllocPolicy(..)
  , Types.DiskTemplate(..)
  , Types.FailMode(..)
  , Types.EvacMode(..)
  , Types.OpResult(..)
  , Types.ISpec(..)
  , Types.IPolicy(..)
  , nullIPolicy
  ) where

import Test.QuickCheck

import Control.Applicative
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools

import qualified Ganeti.HTools.Types as Types

-- * Helpers

-- | All disk templates (used later)
allDiskTemplates :: [Types.DiskTemplate]
allDiskTemplates = [minBound..maxBound]

-- * Arbitrary instance

instance Arbitrary Types.AllocPolicy where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Types.DiskTemplate where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Types.FailMode where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Types.EvacMode where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary a => Arbitrary (Types.OpResult a) where
  arbitrary = arbitrary >>= \c ->
              if c
                then Types.OpGood <$> arbitrary
                else Types.OpFail <$> arbitrary

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
    dts  <- genUniquesList num_tmpl
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

prop_Types_AllocPolicy_serialisation :: Types.AllocPolicy -> Property
prop_Types_AllocPolicy_serialisation apol =
  case J.readJSON (J.showJSON apol) of
    J.Ok p -> p ==? apol
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_DiskTemplate_serialisation :: Types.DiskTemplate -> Property
prop_Types_DiskTemplate_serialisation dt =
  case J.readJSON (J.showJSON dt) of
    J.Ok p -> p ==? dt
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_ISpec_serialisation :: Types.ISpec -> Property
prop_Types_ISpec_serialisation ispec =
  case J.readJSON (J.showJSON ispec) of
    J.Ok p -> p ==? ispec
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_IPolicy_serialisation :: Types.IPolicy -> Property
prop_Types_IPolicy_serialisation ipol =
  case J.readJSON (J.showJSON ipol) of
    J.Ok p -> p ==? ipol
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_EvacMode_serialisation :: Types.EvacMode -> Property
prop_Types_EvacMode_serialisation em =
  case J.readJSON (J.showJSON em) of
    J.Ok p -> p ==? em
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_opToResult :: Types.OpResult Int -> Bool
prop_Types_opToResult op =
  case op of
    Types.OpFail _ -> Types.isBad r
    Types.OpGood v -> case r of
                        Types.Bad _ -> False
                        Types.Ok v' -> v == v'
  where r = Types.opToResult op

prop_Types_eitherToResult :: Either String Int -> Bool
prop_Types_eitherToResult ei =
  case ei of
    Left _ -> Types.isBad r
    Right v -> case r of
                 Types.Bad _ -> False
                 Types.Ok v' -> v == v'
    where r = Types.eitherToResult ei

testSuite "Types"
            [ 'prop_Types_AllocPolicy_serialisation
            , 'prop_Types_DiskTemplate_serialisation
            , 'prop_Types_ISpec_serialisation
            , 'prop_Types_IPolicy_serialisation
            , 'prop_Types_EvacMode_serialisation
            , 'prop_Types_opToResult
            , 'prop_Types_eitherToResult
            ]

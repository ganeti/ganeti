{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for the LV Parser -}

{-

Copyright (C) 2013 Google Inc.

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

module Test.Ganeti.Storage.Lvm.LVParser (testStorage_Lvm_LVParser) where

import Test.QuickCheck as QuickCheck hiding (Result)
import Test.HUnit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Control.Applicative ((<$>), (<*>))
import Data.List (intercalate)

import Ganeti.Storage.Lvm.LVParser
import Ganeti.Storage.Lvm.Types

{-# ANN module "HLint: ignore Use camelCase" #-}


-- | Test parsing a LV @lvs@ output.
case_lvs_lv :: Assertion
case_lvs_lv = testParser lvParser "lvs_lv.txt"
  [ LVInfo "nhasjL-cnZi-uqLS-WRLj-tkXI-nvCB-n0o2lj"
      "df9ff3f6-a833-48ff-8bd5-bff2eaeab759.disk0_data" "-wi-ao" (negate 1)
      (negate 1) 253 0 1073741824 1
      "originstname+instance1.example.com" ""
      "uZgXit-eiRr-vRqe-xpEo-e9nU-mTuR-9nfVIU" "xenvg" "linear" 0 0 1073741824
      "" "/dev/sda5:0-15" "/dev/sda5(0)" Nothing
  , LVInfo "5fW5mE-SBSs-GSU0-KZDg-hnwb-sZOC-zZt736"
      "df9ff3f6-a833-48ff-8bd5-bff2eaeab759.disk0_meta" "-wi-ao" (negate 1)
      (negate 1) 253 1 134217728 1
      "originstname+instance1.example.com" ""
      "uZgXit-eiRr-vRqe-xpEo-e9nU-mTuR-9nfVIU" "xenvg" "linear" 0 0 134217728 ""
      "/dev/sda5:16-17" "/dev/sda5(16)" Nothing
  ]

-- | Serialize a LVInfo in the same format that is output by @lvs@.
-- The "instance" field is not serialized because it's not provided by @lvs@
-- so it is not part of this test.
serializeLVInfo :: LVInfo -> String
serializeLVInfo l = intercalate ";"
  [ lviUuid l
  , lviName l
  , lviAttr l
  , show $ lviMajor l
  , show $ lviMinor l
  , show $ lviKernelMajor l
  , show $ lviKernelMinor l
  , show (lviSize l) ++ "B"
  , show $ lviSegCount l
  , lviTags l
  , lviModules l
  , lviVgUuid l
  , lviVgName l
  , lviSegtype l
  , show (lviSegStart l) ++ "B"
  , show $ lviSegStartPe l
  , show (lviSegSize l) ++ "B"
  , lviSegTags l
  , lviSegPeRanges l
  , lviDevices l
  ] ++ "\n"

-- | Serialize a list of LVInfo in the same format that is output by @lvs@.
serializeLVInfos :: [LVInfo] -> String
serializeLVInfos = concatMap serializeLVInfo

-- | Arbitrary instance for LVInfo.
-- The instance is always Nothing because it is not part of the parsed data:
-- it is added afterwards from a different source.
instance Arbitrary LVInfo where
  arbitrary =
    LVInfo
      <$> genUUID        -- uuid
      <*> genName        -- name
      <*> genName        -- attr
      <*> arbitrary      -- major
      <*> arbitrary      -- minor
      <*> arbitrary      -- kernel_major
      <*> arbitrary      -- kernel_minor
      <*> genNonNegative -- size
      <*> arbitrary      -- seg_cont
      <*> genName        -- tags
      <*> genName        -- modules
      <*> genUUID        -- vg_uuid
      <*> genName        -- vg_name
      <*> genName        -- segtype
      <*> genNonNegative -- seg_start
      <*> arbitrary      -- seg_start_pe
      <*> genNonNegative -- seg_size
      <*> genName        -- seg_tags
      <*> genName        -- seg_pe_ranges
      <*> genName        -- devices
      <*> return Nothing -- instance

-- | Test if a randomly generated LV lvs output is properly parsed.
prop_parse_lvs_lv :: [LVInfo] -> Property
prop_parse_lvs_lv expected =
  genPropParser lvParser (serializeLVInfos expected) expected

testSuite "Storage/Lvm/LVParser"
          [ 'case_lvs_lv,
            'prop_parse_lvs_lv
          ]

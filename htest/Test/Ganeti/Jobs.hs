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

module Test.Ganeti.Jobs (testJobs) where

import Test.QuickCheck

import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.Jobs as Jobs

-- * Arbitrary instances

instance Arbitrary Jobs.OpStatus where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Jobs.JobStatus where
  arbitrary = elements [minBound..maxBound]

-- * Test cases

-- | Check that (queued) job\/opcode status serialization is idempotent.
prop_OpStatus_serialization :: Jobs.OpStatus -> Property
prop_OpStatus_serialization os =
  case J.readJSON (J.showJSON os) of
    J.Error e -> failTest $ "Cannot deserialise: " ++ e
    J.Ok os' -> os ==? os'

prop_JobStatus_serialization :: Jobs.JobStatus -> Property
prop_JobStatus_serialization js =
  case J.readJSON (J.showJSON js) of
    J.Error e -> failTest $ "Cannot deserialise: " ++ e
    J.Ok js' -> js ==? js'

testSuite "Jobs"
            [ 'prop_OpStatus_serialization
            , 'prop_JobStatus_serialization
            ]

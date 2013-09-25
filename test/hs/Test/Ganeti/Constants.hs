{-# LANGUAGE TemplateHaskell #-}
{-| Unittests for constants

-}

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

module Test.Ganeti.Constants (testConstants) where

import Test.HUnit (Assertion)
import qualified Test.HUnit as HUnit

import qualified Ganeti.Constants as Constants
import qualified Ganeti.ConstantUtils as ConstantUtils
import qualified Test.Ganeti.TestHelper as TestHelper

{-# ANN module "HLint: ignore Use camelCase" #-}

case_buildVersion :: Assertion
case_buildVersion = do
  HUnit.assertBool "Config major lower-bound violation"
                   (Constants.configMajor >= 0)
  HUnit.assertBool "Config major upper-bound violation"
                   (Constants.configMajor <= 99)
  HUnit.assertBool "Config minor lower-bound violation"
                   (Constants.configMinor >= 0)
  HUnit.assertBool "Config minor upper-bound violation"
                   (Constants.configMinor <= 99)
  HUnit.assertBool "Config revision lower-bound violation"
                   (Constants.configRevision >= 0)
  HUnit.assertBool "Config revision upper-bound violation"
                   (Constants.configRevision <= 9999)
  HUnit.assertBool "Config version lower-bound violation"
                   (Constants.configVersion >= 0)
  HUnit.assertBool "Config version upper-bound violation"
                   (Constants.configVersion <= 99999999)
  HUnit.assertEqual "Build version"
                    (ConstantUtils.buildVersion 0 0 0) 0
  HUnit.assertEqual "Build version"
                    (ConstantUtils.buildVersion 10 10 1010) 10101010
  HUnit.assertEqual "Build version"
                    (ConstantUtils.buildVersion 12 34 5678) 12345678
  HUnit.assertEqual "Build version"
                    (ConstantUtils.buildVersion 99 99 9999) 99999999
  HUnit.assertEqual "Build version"
                    (ConstantUtils.buildVersion
                     Constants.configMajor
                     Constants.configMinor
                     Constants.configRevision) Constants.configVersion
  HUnit.assertEqual "Build version"
                    (ConstantUtils.buildVersion
                     Constants.configMajor
                     Constants.configMinor
                     Constants.configRevision) Constants.protocolVersion

TestHelper.testSuite "Constants"
  [ 'case_buildVersion
  ]

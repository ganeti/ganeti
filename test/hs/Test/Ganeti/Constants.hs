{-# LANGUAGE TemplateHaskell #-}
{-| Unittests for constants

-}

{-

Copyright (C) 2013 Google Inc.
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

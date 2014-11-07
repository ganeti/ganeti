{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

module Test.Ganeti.Ssconf (testSsconf) where

import Test.QuickCheck
import qualified Test.HUnit as HUnit

import Data.List
import qualified Data.Map as M

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.Ssconf as Ssconf
import qualified Ganeti.Types as Types

-- * Ssconf tests

$(genArbitrary ''Ssconf.SSKey)

instance Arbitrary Ssconf.SSConf where
  arbitrary = fmap (Ssconf.SSConf . M.fromList) arbitrary

-- * Reading SSConf

prop_filename :: Ssconf.SSKey -> Property
prop_filename key =
  counterexample "Key doesn't start with correct prefix" $
    Ssconf.sSFilePrefix `isPrefixOf` Ssconf.keyToFilename "" key

caseParseNodesVmCapable :: HUnit.Assertion
caseParseNodesVmCapable = do
  let str = "node1.example.com=True\nnode2.example.com=False"
      result = Ssconf.parseNodesVmCapable str
      expected = return
        [ ("node1.example.com", True)
        , ("node2.example.com", False)
        ]
  HUnit.assertEqual "Mismatch in parsed and expected result" expected result

caseParseHypervisorList :: HUnit.Assertion
caseParseHypervisorList = do
  let result = Ssconf.parseHypervisorList "kvm\nxen-pvm\nxen-hvm"
      expected = return [Types.Kvm, Types.XenPvm, Types.XenHvm]
  HUnit.assertEqual "Mismatch in parsed and expected result" expected result

caseParseEnabledUserShutdown :: HUnit.Assertion
caseParseEnabledUserShutdown = do
  let result1 = Ssconf.parseEnabledUserShutdown "True"
      result2 = Ssconf.parseEnabledUserShutdown "False"
  HUnit.assertEqual "Mismatch in parsed and expected result"
    (return True) result1
  HUnit.assertEqual "Mismatch in parsed and expected result"
    (return False) result2

-- * Creating and writing SSConf

-- | Verify that for SSConf we have readJSON . showJSON = Ok.
prop_ReadShow :: Ssconf.SSConf -> Property
prop_ReadShow = testSerialisation

testSuite "Ssconf"
  [ 'prop_filename
  , 'caseParseNodesVmCapable
  , 'caseParseHypervisorList
  , 'caseParseEnabledUserShutdown
  , 'prop_ReadShow
  ]

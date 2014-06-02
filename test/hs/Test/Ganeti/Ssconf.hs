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

module Test.Ganeti.Ssconf (testSsconf) where

import Test.QuickCheck
import qualified Test.HUnit as HUnit

import Data.List

import Test.Ganeti.TestHelper

import qualified Ganeti.Ssconf as Ssconf
import qualified Ganeti.Types as Types

-- * Ssconf tests

$(genArbitrary ''Ssconf.SSKey)

prop_filename :: Ssconf.SSKey -> Property
prop_filename key =
  printTestCase "Key doesn't start with correct prefix" $
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

testSuite "Ssconf"
  [ 'prop_filename
  , 'caseParseNodesVmCapable
  , 'caseParseHypervisorList
  , 'caseParseEnabledUserShutdown
  ]

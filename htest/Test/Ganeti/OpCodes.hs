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

module Test.Ganeti.OpCodes
  ( testOpCodes
  , OpCodes.OpCode(..)
  ) where

import qualified Test.HUnit as HUnit
import Test.QuickCheck

import Control.Applicative
import Data.List
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.Constants as C
import qualified Ganeti.OpCodes as OpCodes

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitrary instances

$(genArbitrary ''OpCodes.TagObject)

$(genArbitrary ''OpCodes.ReplaceDisksMode)

instance Arbitrary OpCodes.DiskIndex where
  arbitrary = choose (0, C.maxDisks - 1) >>= OpCodes.mkDiskIndex

instance Arbitrary OpCodes.OpCode where
  arbitrary = do
    op_id <- elements OpCodes.allOpIDs
    case op_id of
      "OP_TEST_DELAY" ->
        OpCodes.OpTestDelay <$> arbitrary <*> arbitrary
                 <*> resize maxNodes (listOf getFQDN)
      "OP_INSTANCE_REPLACE_DISKS" ->
        OpCodes.OpInstanceReplaceDisks <$> getFQDN <*> getMaybe getFQDN <*>
          arbitrary <*> resize C.maxDisks arbitrary <*> getMaybe getName
      "OP_INSTANCE_FAILOVER" ->
        OpCodes.OpInstanceFailover <$> getFQDN <*> arbitrary <*>
          getMaybe getFQDN
      "OP_INSTANCE_MIGRATE" ->
        OpCodes.OpInstanceMigrate <$> getFQDN <*> arbitrary <*>
          arbitrary <*> arbitrary <*> getMaybe getFQDN
      "OP_TAGS_SET" ->
        OpCodes.OpTagsSet <$> arbitrary <*> genTags <*> getMaybe getFQDN
      "OP_TAGS_DEL" ->
        OpCodes.OpTagsSet <$> arbitrary <*> genTags <*> getMaybe getFQDN
      _ -> fail "Wrong opcode"

-- * Test cases

-- | Check that opcode serialization is idempotent.
prop_serialization :: OpCodes.OpCode -> Property
prop_serialization = testSerialisation

-- | Check that Python and Haskell defined the same opcode list.
case_AllDefined :: HUnit.Assertion
case_AllDefined = do
  py_stdout <- runPython "from ganeti import opcodes\n\
                         \print '\\n'.join(opcodes.OP_MAPPING.keys())" "" >>=
               checkPythonResult
  let py_ops = sort $ lines py_stdout
      hs_ops = OpCodes.allOpIDs
      -- extra_py = py_ops \\ hs_ops
      extra_hs = hs_ops \\ py_ops
  -- FIXME: uncomment when we have parity
  -- HUnit.assertBool ("OpCodes missing from Haskell code:\n" ++
  --                  unlines extra_py) (null extra_py)
  HUnit.assertBool ("Extra OpCodes in the Haskell code code:\n" ++
                    unlines extra_hs) (null extra_hs)

-- | Custom HUnit test case that forks a Python process and checks
-- correspondence between Haskell-generated OpCodes and their Python
-- decoded, validated and re-encoded version.
--
-- Note that we have a strange beast here: since launching Python is
-- expensive, we don't do this via a usual QuickProperty, since that's
-- slow (I've tested it, and it's indeed quite slow). Rather, we use a
-- single HUnit assertion, and in it we manually use QuickCheck to
-- generate 500 opcodes times the number of defined opcodes, which
-- then we pass in bulk to Python. The drawbacks to this method are
-- two fold: we cannot control the number of generated opcodes, since
-- HUnit assertions don't get access to the test options, and for the
-- same reason we can't run a repeatable seed. We should probably find
-- a better way to do this, for example by having a
-- separately-launched Python process (if not running the tests would
-- be skipped).
case_py_compat :: HUnit.Assertion
case_py_compat = do
  let num_opcodes = length OpCodes.allOpIDs * 500
  sample_opcodes <- sample' (vectorOf num_opcodes
                             (arbitrary::Gen OpCodes.OpCode))
  let opcodes = head sample_opcodes
      serialized = J.encode opcodes
  py_stdout <-
     runPython "from ganeti import opcodes\n\
               \import sys\n\
               \from ganeti import serializer\n\
               \op_data = serializer.Load(sys.stdin.read())\n\
               \decoded = [opcodes.OpCode.LoadOpCode(o) for o in op_data]\n\
               \for op in decoded:\n\
               \  op.Validate(True)\n\
               \encoded = [op.__getstate__() for op in decoded]\n\
               \print serializer.Dump(encoded)" serialized
     >>= checkPythonResult
  let deserialised = J.decode py_stdout::J.Result [OpCodes.OpCode]
  decoded <- case deserialised of
               J.Ok ops -> return ops
               J.Error msg ->
                 HUnit.assertFailure ("Unable to decode opcodes: " ++ msg)
                 -- this already raised an expection, but we need it
                 -- for proper types
                 >> fail "Unable to decode opcodes"
  HUnit.assertEqual "Mismatch in number of returned opcodes"
    (length opcodes) (length decoded)
  mapM_ (uncurry (HUnit.assertEqual "Different result after encoding/decoding")
        ) $ zip opcodes decoded

testSuite "OpCodes"
            [ 'prop_serialization
            , 'case_AllDefined
            , 'case_py_compat
            ]

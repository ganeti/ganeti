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
import qualified Data.Map as Map
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Types ()
import Test.Ganeti.Query.Language

import qualified Ganeti.Constants as C
import qualified Ganeti.OpCodes as OpCodes
import Ganeti.Types
import Ganeti.OpParams
import Ganeti.JSON

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitrary instances

instance Arbitrary OpCodes.TagObject where
  arbitrary = oneof [ OpCodes.TagInstance <$> getFQDN
                    , OpCodes.TagNode     <$> getFQDN
                    , OpCodes.TagGroup    <$> getFQDN
                    , pure OpCodes.TagCluster
                    ]

$(genArbitrary ''OpCodes.ReplaceDisksMode)

instance Arbitrary OpCodes.DiskIndex where
  arbitrary = choose (0, C.maxDisks - 1) >>= OpCodes.mkDiskIndex

instance Arbitrary INicParams where
  arbitrary = INicParams <$> getMaybe genNameNE <*> getMaybe getName <*>
              getMaybe genNameNE <*> getMaybe genNameNE

instance Arbitrary OpCodes.OpCode where
  arbitrary = do
    op_id <- elements OpCodes.allOpIDs
    case op_id of
      "OP_TEST_DELAY" ->
        OpCodes.OpTestDelay <$> arbitrary <*> arbitrary
                 <*> genNodeNames
      "OP_INSTANCE_REPLACE_DISKS" ->
        OpCodes.OpInstanceReplaceDisks <$> getFQDN <*>
          getMaybe genNodeNameNE <*> arbitrary <*> genDiskIndices <*>
          getMaybe genNameNE
      "OP_INSTANCE_FAILOVER" ->
        OpCodes.OpInstanceFailover <$> getFQDN <*> arbitrary <*>
          getMaybe genNodeNameNE
      "OP_INSTANCE_MIGRATE" ->
        OpCodes.OpInstanceMigrate <$> getFQDN <*> arbitrary <*>
          arbitrary <*> arbitrary <*> getMaybe genNodeNameNE
      "OP_TAGS_SET" ->
        OpCodes.OpTagsSet <$> arbitrary <*> genTags
      "OP_TAGS_DEL" ->
        OpCodes.OpTagsSet <$> arbitrary <*> genTags
      "OP_CLUSTER_POST_INIT" -> pure OpCodes.OpClusterPostInit
      "OP_CLUSTER_DESTROY" -> pure OpCodes.OpClusterDestroy
      "OP_CLUSTER_QUERY" -> pure OpCodes.OpClusterQuery
      "OP_CLUSTER_VERIFY" ->
        OpCodes.OpClusterVerify <$> arbitrary <*> arbitrary <*>
          genSet Nothing <*> genSet Nothing <*> arbitrary <*>
          getMaybe genNameNE
      "OP_CLUSTER_VERIFY_CONFIG" ->
        OpCodes.OpClusterVerifyConfig <$> arbitrary <*> arbitrary <*>
          genSet Nothing <*> arbitrary
      "OP_CLUSTER_VERIFY_GROUP" ->
        OpCodes.OpClusterVerifyGroup <$> genNameNE <*> arbitrary <*>
          arbitrary <*> genSet Nothing <*> genSet Nothing <*> arbitrary
      "OP_CLUSTER_VERIFY_DISKS" -> pure OpCodes.OpClusterVerifyDisks
      "OP_GROUP_VERIFY_DISKS" ->
        OpCodes.OpGroupVerifyDisks <$> genNameNE
      "OP_CLUSTER_REPAIR_DISK_SIZES" ->
        OpCodes.OpClusterRepairDiskSizes <$>
          resize maxNodes (listOf (getFQDN >>= mkNonEmpty))
      "OP_CLUSTER_CONFIG_QUERY" ->
        OpCodes.OpClusterConfigQuery <$> genFieldsNE
      "OP_CLUSTER_RENAME" ->
        OpCodes.OpClusterRename <$> (getName >>= mkNonEmpty)
      "OP_CLUSTER_SET_PARAMS" ->
        OpCodes.OpClusterSetParams <$> emptyMUD <*> emptyMUD <*>
          arbitrary <*> getMaybe (listOf1 arbitrary >>= mkNonEmpty) <*>
          getMaybe genEmptyContainer <*> emptyMUD <*>
          getMaybe genEmptyContainer <*> getMaybe genEmptyContainer <*>
          getMaybe genEmptyContainer <*> getMaybe arbitrary <*>
          arbitrary <*> arbitrary <*> arbitrary <*>
          arbitrary <*> arbitrary <*> arbitrary <*>
          emptyMUD <*> emptyMUD <*> arbitrary <*>
          arbitrary <*> arbitrary <*> arbitrary <*>
          arbitrary <*> arbitrary <*> arbitrary
      "OP_CLUSTER_REDIST_CONF" -> pure OpCodes.OpClusterRedistConf
      "OP_CLUSTER_ACTIVATE_MASTER_IP" ->
        pure OpCodes.OpClusterActivateMasterIp
      "OP_CLUSTER_DEACTIVATE_MASTER_IP" ->
        pure OpCodes.OpClusterDeactivateMasterIp
      "OP_QUERY" ->
        OpCodes.OpQuery <$> arbitrary <*> arbitrary <*> arbitrary <*> genFilter
      "OP_QUERY_FIELDS" ->
        OpCodes.OpQueryFields <$> arbitrary <*> arbitrary
      "OP_OOB_COMMAND" ->
        OpCodes.OpOobCommand <$> genNodeNamesNE <*> arbitrary <*>
          arbitrary <*> arbitrary <*> (arbitrary `suchThat` (>0))
      "OP_NODE_REMOVE" -> OpCodes.OpNodeRemove <$> (getFQDN >>= mkNonEmpty)
      "OP_NODE_ADD" ->
        OpCodes.OpNodeAdd <$> genNodeNameNE <*> emptyMUD <*> emptyMUD <*>
          getMaybe getName <*> getMaybe genNameNE <*> arbitrary <*>
          getMaybe genNameNE <*> arbitrary <*> arbitrary <*> emptyMUD
      "OP_NODE_QUERY" ->
        OpCodes.OpNodeQuery <$> arbitrary <*> arbitrary <*> arbitrary
      "OP_NODE_QUERYVOLS" ->
        OpCodes.OpNodeQueryvols <$> arbitrary <*> genNodeNamesNE
      "OP_NODE_QUERY_STORAGE" ->
        OpCodes.OpNodeQueryStorage <$> arbitrary <*> arbitrary <*>
          genNodeNamesNE <*> genNameNE
      "OP_NODE_MODIFY_STORAGE" ->
        OpCodes.OpNodeModifyStorage <$> genNodeNameNE <*> arbitrary <*>
          genNameNE <*> pure emptyJSObject
      "OP_REPAIR_NODE_STORAGE" ->
        OpCodes.OpRepairNodeStorage <$> genNodeNameNE <*> arbitrary <*>
          genNameNE <*> arbitrary
      "OP_NODE_SET_PARAMS" ->
        OpCodes.OpNodeSetParams <$> genNodeNameNE <*> arbitrary <*>
          emptyMUD <*> emptyMUD <*> arbitrary <*> arbitrary <*> arbitrary <*>
          arbitrary <*> arbitrary <*> arbitrary <*> getMaybe genNameNE <*>
          emptyMUD
      "OP_NODE_POWERCYCLE" ->
        OpCodes.OpNodePowercycle <$> genNodeNameNE <*> arbitrary
      "OP_NODE_MIGRATE" ->
        OpCodes.OpNodeMigrate <$> genNodeNameNE <*> arbitrary <*>
          arbitrary <*> getMaybe genNodeNameNE <*> arbitrary <*>
          arbitrary <*> getMaybe genNameNE
      "OP_NODE_EVACUATE" ->
        OpCodes.OpNodeEvacuate <$> arbitrary <*> genNodeNameNE <*>
          getMaybe genNodeNameNE <*> getMaybe genNameNE <*> arbitrary
      _ -> fail $ "Undefined arbitrary for opcode " ++ op_id

-- * Helper functions

-- | Empty JSObject.
emptyJSObject :: J.JSObject J.JSValue
emptyJSObject = J.toJSObject []

-- | Empty maybe unchecked dictionary.
emptyMUD :: Gen (Maybe (J.JSObject J.JSValue))
emptyMUD = getMaybe $ pure emptyJSObject

-- | Generates an empty container.
genEmptyContainer :: (Ord a) => Gen (GenericContainer a b)
genEmptyContainer = pure . GenericContainer $ Map.fromList []

-- | Generates list of disk indices.
genDiskIndices :: Gen [DiskIndex]
genDiskIndices = do
  cnt <- choose (0, C.maxDisks)
  genUniquesList cnt

-- | Generates a list of node names.
genNodeNames :: Gen [String]
genNodeNames = resize maxNodes (listOf getFQDN)

-- | Generates a list of node names in non-empty string type.
genNodeNamesNE :: Gen [NonEmptyString]
genNodeNamesNE = genNodeNames >>= mapM (mkNonEmpty)

-- | Gets a node name in non-empty type.
genNodeNameNE :: Gen NonEmptyString
genNodeNameNE = getFQDN >>= mkNonEmpty

-- | Gets a name (non-fqdn) in non-empty type.
genNameNE :: Gen NonEmptyString
genNameNE = getName >>= mkNonEmpty

-- | Returns a list of non-empty fields.
genFieldsNE :: Gen [NonEmptyString]
genFieldsNE = getFields >>= mapM mkNonEmpty

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

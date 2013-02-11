{-# LANGUAGE TemplateHaskell, TypeSynonymInstances, FlexibleInstances #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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

module Test.Ganeti.Objects
  ( testObjects
  , Node(..)
  , genEmptyCluster
  , genValidNetwork
  , genBitStringMaxLen
  ) where

import Test.QuickCheck
import qualified Test.HUnit as HUnit

import Control.Applicative
import Control.Monad
import Data.Char
import qualified Data.Map as Map
import qualified Data.Set as Set
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Types ()

import qualified Ganeti.Constants as C
import Ganeti.Network
import Ganeti.Objects as Objects
import Ganeti.JSON
import Ganeti.Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitrary instances

$(genArbitrary ''PartialNDParams)

instance Arbitrary Node where
  arbitrary = Node <$> genFQDN <*> genFQDN <*> genFQDN
              <*> arbitrary <*> arbitrary <*> arbitrary <*> genFQDN
              <*> arbitrary <*> arbitrary <*> arbitrary <*> arbitrary
              <*> arbitrary <*> arbitrary <*> genFQDN <*> arbitrary
              <*> (Set.fromList <$> genTags)

$(genArbitrary ''BlockDriver)

$(genArbitrary ''DiskMode)

instance Arbitrary DiskLogicalId where
  arbitrary = oneof [ LIDPlain <$> arbitrary <*> arbitrary
                    , LIDDrbd8 <$> genFQDN <*> genFQDN <*> arbitrary
                               <*> arbitrary <*> arbitrary <*> arbitrary
                    , LIDFile  <$> arbitrary <*> arbitrary
                    , LIDBlockDev <$> arbitrary <*> arbitrary
                    , LIDRados <$> arbitrary <*> arbitrary
                    ]

-- | 'Disk' 'arbitrary' instance. Since we don't test disk hierarchy
-- properties, we only generate disks with no children (FIXME), as
-- generating recursive datastructures is a bit more work.
instance Arbitrary Disk where
  arbitrary = Disk <$> arbitrary <*> pure [] <*> arbitrary
                   <*> arbitrary <*> arbitrary

-- FIXME: we should generate proper values, >=0, etc., but this is
-- hard for partial ones, where all must be wrapped in a 'Maybe'
$(genArbitrary ''PartialBeParams)

$(genArbitrary ''AdminState)

$(genArbitrary ''PartialNicParams)

$(genArbitrary ''PartialNic)

instance Arbitrary Instance where
  arbitrary =
    Instance
      <$> genFQDN <*> genFQDN <*> genFQDN -- OS name, but...
      <*> arbitrary
      -- FIXME: add non-empty hvparams when they're a proper type
      <*> pure (GenericContainer Map.empty) <*> arbitrary
      -- ... and for OSParams
      <*> pure (GenericContainer Map.empty) <*> arbitrary <*> arbitrary
      <*> arbitrary <*> arbitrary <*> arbitrary
      -- ts
      <*> arbitrary <*> arbitrary
      -- uuid
      <*> arbitrary
      -- serial
      <*> arbitrary
      -- tags
      <*> (Set.fromList <$> genTags)

-- | FIXME: This generates completely random data, without normal
-- validation rules.
$(genArbitrary ''PartialISpecParams)

-- | FIXME: This generates completely random data, without normal
-- validation rules.
$(genArbitrary ''PartialIPolicy)

$(genArbitrary ''FilledISpecParams)
$(genArbitrary ''FilledIPolicy)
$(genArbitrary ''IpFamily)
$(genArbitrary ''FilledNDParams)
$(genArbitrary ''FilledNicParams)
$(genArbitrary ''FilledBeParams)

-- | No real arbitrary instance for 'ClusterHvParams' yet.
instance Arbitrary ClusterHvParams where
  arbitrary = return $ GenericContainer Map.empty

-- | No real arbitrary instance for 'OsHvParams' yet.
instance Arbitrary OsHvParams where
  arbitrary = return $ GenericContainer Map.empty

instance Arbitrary ClusterNicParams where
  arbitrary = (GenericContainer . Map.singleton C.ppDefault) <$> arbitrary

instance Arbitrary OsParams where
  arbitrary = (GenericContainer . Map.fromList) <$> arbitrary

instance Arbitrary ClusterOsParams where
  arbitrary = (GenericContainer . Map.fromList) <$> arbitrary

instance Arbitrary ClusterBeParams where
  arbitrary = (GenericContainer . Map.fromList) <$> arbitrary

instance Arbitrary TagSet where
  arbitrary = Set.fromList <$> genTags

$(genArbitrary ''Cluster)

instance Arbitrary Network where
  arbitrary = genValidNetwork

-- | Generates a network instance with minimum netmasks of /24. Generating
-- bigger networks slows down the tests, because long bit strings are generated
-- for the reservations.
genValidNetwork :: Gen Objects.Network
genValidNetwork = do
  -- generate netmask for the IPv4 network
  netmask <- choose (24::Int, 30)
  name <- genName >>= mkNonEmpty
  mac_prefix <- genMaybe genName
  net <- genIp4NetWithNetmask netmask
  net6 <- genMaybe genIp6Net
  gateway <- genMaybe genIp4AddrStr
  gateway6 <- genMaybe genIp6Addr
  res <- liftM Just (genBitString $ netmask2NumHosts netmask)
  ext_res <- liftM Just (genBitString $ netmask2NumHosts netmask)
  let n = Network name mac_prefix net net6 gateway
          gateway6 res ext_res 0 Set.empty
  return n

-- | Generate an arbitrary string consisting of '0' and '1' of the given length.
genBitString :: Int -> Gen String
genBitString len = vectorOf len (elements "01")

-- | Generate an arbitrary string consisting of '0' and '1' of the maximum given
-- length.
genBitStringMaxLen :: Int -> Gen String
genBitStringMaxLen maxLen = choose (0, maxLen) >>= genBitString

-- | Generator for config data with an empty cluster (no instances),
-- with N defined nodes.
genEmptyCluster :: Int -> Gen ConfigData
genEmptyCluster ncount = do
  nodes <- vector ncount
  version <- arbitrary
  let guuid = "00"
      nodes' = zipWith (\n idx ->
                          let newname = nodeName n ++ "-" ++ show idx
                          in (newname, n { nodeGroup = guuid,
                                           nodeName = newname}))
               nodes [(1::Int)..]
      nodemap = Map.fromList nodes'
      contnodes = if Map.size nodemap /= ncount
                    then error ("Inconsistent node map, duplicates in" ++
                                " node name list? Names: " ++
                                show (map fst nodes'))
                    else GenericContainer nodemap
      continsts = GenericContainer Map.empty
  grp <- arbitrary
  let contgroups = GenericContainer $ Map.singleton guuid grp
  serial <- arbitrary
  cluster <- resize 8 arbitrary
  let c = ConfigData version cluster contnodes contgroups continsts serial
  return c

-- * Test properties

-- | Tests that fillDict behaves correctly
prop_fillDict :: [(Int, Int)] -> [(Int, Int)] -> Property
prop_fillDict defaults custom =
  let d_map = Map.fromList defaults
      d_keys = map fst defaults
      c_map = Map.fromList custom
      c_keys = map fst custom
  in conjoin [ printTestCase "Empty custom filling"
               (fillDict d_map Map.empty [] == d_map)
             , printTestCase "Empty defaults filling"
               (fillDict Map.empty c_map [] == c_map)
             , printTestCase "Delete all keys"
               (fillDict d_map c_map (d_keys++c_keys) == Map.empty)
             ]

-- | Test that the serialisation of 'DiskLogicalId', which is
-- implemented manually, is idempotent. Since we don't have a
-- standalone JSON instance for DiskLogicalId (it's a data type that
-- expands over two fields in a JSObject), we test this by actially
-- testing entire Disk serialisations. So this tests two things at
-- once, basically.
prop_Disk_serialisation :: Disk -> Property
prop_Disk_serialisation = testSerialisation

-- | Check that node serialisation is idempotent.
prop_Node_serialisation :: Node -> Property
prop_Node_serialisation = testSerialisation

-- | Check that instance serialisation is idempotent.
prop_Inst_serialisation :: Instance -> Property
prop_Inst_serialisation = testSerialisation

-- | Check that network serialisation is idempotent.
prop_Network_serialisation :: Network -> Property
prop_Network_serialisation = testSerialisation

-- | Check config serialisation.
prop_Config_serialisation :: Property
prop_Config_serialisation =
  forAll (choose (0, maxNodes `div` 4) >>= genEmptyCluster) testSerialisation

-- | Custom HUnit test to check the correspondence between Haskell-generated
-- networks and their Python decoded, validated and re-encoded version.
-- For the technical background of this unit test, check the documentation
-- of "case_py_compat_types" of test/hs/Test/Ganeti/Opcodes.hs
case_py_compat_networks :: HUnit.Assertion
case_py_compat_networks = do
  let num_networks = 500::Int
  networks <- genSample (vectorOf num_networks genValidNetwork)
  let networks_with_properties = map getNetworkProperties networks
      serialized = J.encode networks
  -- check for non-ASCII fields, usually due to 'arbitrary :: String'
  mapM_ (\net -> when (any (not . isAscii) (J.encode net)) .
                 HUnit.assertFailure $
                 "Network has non-ASCII fields: " ++ show net
        ) networks
  py_stdout <-
    runPython "from ganeti import network\n\
              \from ganeti import objects\n\
              \from ganeti import serializer\n\
              \import sys\n\
              \net_data = serializer.Load(sys.stdin.read())\n\
              \decoded = [objects.Network.FromDict(n) for n in net_data]\n\
              \encoded = []\n\
              \for net in decoded:\n\
              \  a = network.AddressPool(net)\n\
              \  encoded.append((a.GetFreeCount(), a.GetReservedCount(), \\\n\
              \    net.ToDict()))\n\
              \print serializer.Dump(encoded)" serialized
    >>= checkPythonResult
  let deserialised = J.decode py_stdout::J.Result [(Int, Int, Network)]
  decoded <- case deserialised of
               J.Ok ops -> return ops
               J.Error msg ->
                 HUnit.assertFailure ("Unable to decode networks: " ++ msg)
                 -- this already raised an expection, but we need it
                 -- for proper types
                 >> fail "Unable to decode networks"
  HUnit.assertEqual "Mismatch in number of returned networks"
    (length decoded) (length networks_with_properties)
  mapM_ (uncurry (HUnit.assertEqual "Different result after encoding/decoding")
        ) $ zip decoded networks_with_properties

-- | Creates a tuple of the given network combined with some of its properties
-- to be compared against the same properties generated by the python code.
getNetworkProperties :: Network -> (Int, Int, Network)
getNetworkProperties net =
  let maybePool = createAddressPool net
  in  case maybePool of
           (Just pool) -> (getFreeCount pool, getReservedCount pool, net)
           Nothing -> (-1, -1, net)

-- | Tests the compatibility between Haskell-serialized node groups and their
-- python-decoded and encoded version.
case_py_compat_nodegroups :: HUnit.Assertion
case_py_compat_nodegroups = do
  let num_groups = 500::Int
  groups <- genSample (vectorOf num_groups genNodeGroup)
  let serialized = J.encode groups
  -- check for non-ASCII fields, usually due to 'arbitrary :: String'
  mapM_ (\group -> when (any (not . isAscii) (J.encode group)) .
                 HUnit.assertFailure $
                 "Node group has non-ASCII fields: " ++ show group
        ) groups
  py_stdout <-
    runPython "from ganeti import objects\n\
              \from ganeti import serializer\n\
              \import sys\n\
              \group_data = serializer.Load(sys.stdin.read())\n\
              \decoded = [objects.NodeGroup.FromDict(g) for g in group_data]\n\
              \encoded = [g.ToDict() for g in decoded]\n\
              \print serializer.Dump(encoded)" serialized
    >>= checkPythonResult
  let deserialised = J.decode py_stdout::J.Result [NodeGroup]
  decoded <- case deserialised of
               J.Ok ops -> return ops
               J.Error msg ->
                 HUnit.assertFailure ("Unable to decode node groups: " ++ msg)
                 -- this already raised an expection, but we need it
                 -- for proper types
                 >> fail "Unable to decode node groups"
  HUnit.assertEqual "Mismatch in number of returned node groups"
    (length decoded) (length groups)
  mapM_ (uncurry (HUnit.assertEqual "Different result after encoding/decoding")
        ) $ zip decoded groups

-- | Generates a node group with up to 3 networks.
-- | FIXME: This generates still somewhat completely random data, without normal
-- validation rules.
genNodeGroup :: Gen NodeGroup
genNodeGroup = do
  name <- genFQDN
  members <- pure []
  ndparams <- arbitrary
  alloc_policy <- arbitrary
  ipolicy <- arbitrary
  diskparams <- pure (GenericContainer Map.empty)
  num_networks <- choose (0, 3)
  net_uuid_list <- vectorOf num_networks (arbitrary::Gen String)
  nic_param_list <- vectorOf num_networks (arbitrary::Gen PartialNicParams)
  net_map <- pure (GenericContainer . Map.fromList $
    zip net_uuid_list nic_param_list)
  -- timestamp fields
  ctime <- arbitrary
  mtime <- arbitrary
  uuid <- arbitrary
  serial <- arbitrary
  tags <- Set.fromList <$> genTags
  let group = NodeGroup name members ndparams alloc_policy ipolicy diskparams
              net_map ctime mtime uuid serial tags
  return group

instance Arbitrary NodeGroup where
  arbitrary = genNodeGroup

testSuite "Objects"
  [ 'prop_fillDict
  , 'prop_Disk_serialisation
  , 'prop_Inst_serialisation
  , 'prop_Network_serialisation
  , 'prop_Node_serialisation
  , 'prop_Config_serialisation
  , 'case_py_compat_networks
  , 'case_py_compat_nodegroups
  ]

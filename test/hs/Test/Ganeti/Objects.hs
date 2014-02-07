{-# LANGUAGE TemplateHaskell, TypeSynonymInstances, FlexibleInstances,
  OverloadedStrings #-}
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
  , genConfigDataWithNetworks
  , genDisk
  , genDiskWithChildren
  , genEmptyCluster
  , genInst
  , genInstWithNets
  , genValidNetwork
  , genBitStringMaxLen
  ) where

import Test.QuickCheck
import qualified Test.HUnit as HUnit

import Control.Applicative
import Control.Monad
import Data.Char
import qualified Data.List as List
import qualified Data.Map as Map
import Data.Maybe (fromMaybe)
import qualified Data.Set as Set
import GHC.Exts (IsString(..))
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Types ()

import qualified Ganeti.Constants as C
import Ganeti.Network
import Ganeti.Objects as Objects
import Ganeti.JSON
import Ganeti.Types

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
                   <*> arbitrary <*> arbitrary <*> arbitrary
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
      -- name
      <$> genFQDN
      -- primary node
      <*> genFQDN
      -- OS
      <*> genFQDN
      -- hypervisor
      <*> arbitrary
      -- hvparams
      -- FIXME: add non-empty hvparams when they're a proper type
      <*> pure (GenericContainer Map.empty)
      -- beparams
      <*> arbitrary
      -- osparams
      <*> pure (GenericContainer Map.empty)
      -- admin_state
      <*> arbitrary
      -- nics
      <*> arbitrary
      -- disks
      <*> vectorOf 5 genDisk
      -- disk template
      <*> arbitrary
      -- disks active
      <*> arbitrary
      -- network port
      <*> arbitrary
      -- ts
      <*> arbitrary <*> arbitrary
      -- uuid
      <*> arbitrary
      -- serial
      <*> arbitrary
      -- tags
      <*> (Set.fromList <$> genTags)

-- | Generates an instance that is connected to the given networks
-- and possibly some other networks
genInstWithNets :: [String] -> Gen Instance
genInstWithNets nets = do
  plain_inst <- arbitrary
  enhanceInstWithNets plain_inst nets

-- | Generates an instance that is connected to some networks
genInst :: Gen Instance
genInst = genInstWithNets []

-- | Enhances a given instance with network information, by connecting it to the
-- given networks and possibly some other networks
enhanceInstWithNets :: Instance -> [String] -> Gen Instance
enhanceInstWithNets inst nets = do
  mac <- arbitrary
  ip <- arbitrary
  nicparams <- arbitrary
  name <- arbitrary
  uuid <- arbitrary
  -- generate some more networks than the given ones
  num_more_nets <- choose (0,3)
  more_nets <- vectorOf num_more_nets genName
  let genNic net = PartialNic mac ip nicparams net name uuid
      partial_nics = map (genNic . Just)
                         (List.nub (nets ++ more_nets))
      new_inst = inst { instNics = partial_nics }
  return new_inst

genDiskWithChildren :: Int -> Gen Disk
genDiskWithChildren num_children = do
  logicalid <- arbitrary
  children <- vectorOf num_children (genDiskWithChildren 0)
  ivname <- genName
  size <- arbitrary
  mode <- arbitrary
  name <- genMaybe genName
  spindles <- arbitrary
  uuid <- genName
  let disk = Disk logicalid children ivname size mode name spindles uuid
  return disk

genDisk :: Gen Disk
genDisk = genDiskWithChildren 3

-- | FIXME: This generates completely random data, without normal
-- validation rules.
$(genArbitrary ''PartialISpecParams)

-- | FIXME: This generates completely random data, without normal
-- validation rules.
$(genArbitrary ''PartialIPolicy)

$(genArbitrary ''FilledISpecParams)
$(genArbitrary ''MinMaxISpecs)
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

instance Arbitrary IAllocatorParams where
  arbitrary = return $ GenericContainer Map.empty

$(genArbitrary ''Cluster)

instance Arbitrary Network where
  arbitrary = genValidNetwork

-- | Generates a network instance with minimum netmasks of /24. Generating
-- bigger networks slows down the tests, because long bit strings are generated
-- for the reservations.
genValidNetwork :: Gen Objects.Network
genValidNetwork = do
  -- generate netmask for the IPv4 network
  netmask <- fromIntegral <$> choose (24::Int, 30)
  name <- genName >>= mkNonEmpty
  mac_prefix <- genMaybe genName
  net <- arbitrary
  net6 <- genMaybe genIp6Net
  gateway <- genMaybe arbitrary
  gateway6 <- genMaybe genIp6Addr
  res <- liftM Just (genBitString $ netmask2NumHosts netmask)
  ext_res <- liftM Just (genBitString $ netmask2NumHosts netmask)
  uuid <- arbitrary
  ctime <- arbitrary
  mtime <- arbitrary
  let n = Network name mac_prefix (Ip4Network net netmask) net6 gateway
          gateway6 res ext_res uuid ctime mtime 0 Set.empty
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
  grp <- arbitrary
  let guuid = groupUuid grp
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
      networks = GenericContainer Map.empty
  let contgroups = GenericContainer $ Map.singleton guuid grp
  serial <- arbitrary
  cluster <- resize 8 arbitrary
  let c = ConfigData version cluster contnodes contgroups continsts networks
            serial
  return c

-- | FIXME: make an even simpler base version of creating a cluster.

-- | Generates config data with a couple of networks.
genConfigDataWithNetworks :: ConfigData -> Gen ConfigData
genConfigDataWithNetworks old_cfg = do
  num_nets <- choose (0, 3)
  -- generate a list of network names (no duplicates)
  net_names <- genUniquesList num_nets genName >>= mapM mkNonEmpty
  -- generate a random list of networks (possibly with duplicate names)
  nets <- vectorOf num_nets genValidNetwork
  -- use unique names for the networks
  let nets_unique = map ( \(name, net) -> net { networkName = name } )
        (zip net_names nets)
      net_map = GenericContainer $ Map.fromList
        (map (\n -> (networkUuid n, n)) nets_unique)
      new_cfg = old_cfg { configNetworks = net_map }
  return new_cfg

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
casePyCompatNetworks :: HUnit.Assertion
casePyCompatNetworks = do
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
        ) $ zip networks_with_properties decoded

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
casePyCompatNodegroups :: HUnit.Assertion
casePyCompatNodegroups = do
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
        ) $ zip groups decoded

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
  uuid <- genFQDN `suchThat` (/= name)
  serial <- arbitrary
  tags <- Set.fromList <$> genTags
  let group = NodeGroup name members ndparams alloc_policy ipolicy diskparams
              net_map ctime mtime uuid serial tags
  return group

instance Arbitrary NodeGroup where
  arbitrary = genNodeGroup

$(genArbitrary ''Ip4Address)

$(genArbitrary ''Ip4Network)

-- | Helper to compute absolute value of an IPv4 address.
ip4AddrValue :: Ip4Address -> Integer
ip4AddrValue (Ip4Address a b c d) =
  fromIntegral a * (2^(24::Integer)) +
  fromIntegral b * (2^(16::Integer)) +
  fromIntegral c * (2^(8::Integer)) + fromIntegral d

-- | Tests that any difference between IPv4 consecutive addresses is 1.
prop_nextIp4Address :: Ip4Address -> Property
prop_nextIp4Address ip4 =
  ip4AddrValue (nextIp4Address ip4) ==? ip4AddrValue ip4 + 1

-- | IsString instance for 'Ip4Address', to help write the tests.
instance IsString Ip4Address where
  fromString s =
    fromMaybe (error $ "Failed to parse address from " ++ s) (readIp4Address s)

-- | Tests a few simple cases of IPv4 next address.
caseNextIp4Address :: HUnit.Assertion
caseNextIp4Address = do
  HUnit.assertEqual "" "0.0.0.1" $ nextIp4Address "0.0.0.0"
  HUnit.assertEqual "" "0.0.0.0" $ nextIp4Address "255.255.255.255"
  HUnit.assertEqual "" "1.2.3.5" $ nextIp4Address "1.2.3.4"
  HUnit.assertEqual "" "1.3.0.0" $ nextIp4Address "1.2.255.255"
  HUnit.assertEqual "" "1.2.255.63" $ nextIp4Address "1.2.255.62"

-- | Tests the compatibility between Haskell-serialized instances and their
-- python-decoded and encoded version.
-- Note: this can be enhanced with logical validations on the decoded objects
casePyCompatInstances :: HUnit.Assertion
casePyCompatInstances = do
  let num_inst = 500::Int
  instances <- genSample (vectorOf num_inst genInst)
  let serialized = J.encode instances
  -- check for non-ASCII fields, usually due to 'arbitrary :: String'
  mapM_ (\inst -> when (any (not . isAscii) (J.encode inst)) .
                 HUnit.assertFailure $
                 "Instance has non-ASCII fields: " ++ show inst
        ) instances
  py_stdout <-
    runPython "from ganeti import objects\n\
              \from ganeti import serializer\n\
              \import sys\n\
              \inst_data = serializer.Load(sys.stdin.read())\n\
              \decoded = [objects.Instance.FromDict(i) for i in inst_data]\n\
              \encoded = [i.ToDict() for i in decoded]\n\
              \print serializer.Dump(encoded)" serialized
    >>= checkPythonResult
  let deserialised = J.decode py_stdout::J.Result [Instance]
  decoded <- case deserialised of
               J.Ok ops -> return ops
               J.Error msg ->
                 HUnit.assertFailure ("Unable to decode instance: " ++ msg)
                 -- this already raised an expection, but we need it
                 -- for proper types
                 >> fail "Unable to decode instances"
  HUnit.assertEqual "Mismatch in number of returned instances"
    (length decoded) (length instances)
  mapM_ (uncurry (HUnit.assertEqual "Different result after encoding/decoding")
        ) $ zip instances decoded

-- | Tests that the logical ID is correctly found in a plain disk
caseIncludeLogicalIdPlain :: HUnit.Assertion
caseIncludeLogicalIdPlain =
  let vg_name = "xenvg" :: String
      lv_name = "1234sdf-qwef-2134-asff-asd2-23145d.data" :: String
      d =
        Disk (LIDPlain vg_name lv_name) [] "diskname" 1000 DiskRdWr
          Nothing Nothing "asdfgr-1234-5123-daf3-sdfw-134f43"
  in
    HUnit.assertBool "Unable to detect that plain Disk includes logical ID" $
      includesLogicalId vg_name lv_name d

-- | Tests that the logical ID is correctly found in a DRBD disk
caseIncludeLogicalIdDrbd :: HUnit.Assertion
caseIncludeLogicalIdDrbd =
  let vg_name = "xenvg" :: String
      lv_name = "1234sdf-qwef-2134-asff-asd2-23145d.data" :: String
      d = 
        Disk
          (LIDDrbd8 "node1.example.com" "node2.example.com" 2000 1 5 "secret")
          [ Disk (LIDPlain "onevg" "onelv") [] "disk1" 1000 DiskRdWr Nothing
              Nothing "145145-asdf-sdf2-2134-asfd-534g2x"
          , Disk (LIDPlain vg_name lv_name) [] "disk2" 1000 DiskRdWr Nothing
              Nothing "6gd3sd-423f-ag2j-563b-dg34-gj3fse"
          ] "diskname" 1000 DiskRdWr Nothing Nothing
          "asdfgr-1234-5123-daf3-sdfw-134f43"
  in
    HUnit.assertBool "Unable to detect that plain Disk includes logical ID" $
      includesLogicalId vg_name lv_name d

-- | Tests that the logical ID is correctly NOT found in a plain disk
caseNotIncludeLogicalIdPlain :: HUnit.Assertion
caseNotIncludeLogicalIdPlain =
  let vg_name = "xenvg" :: String
      lv_name = "1234sdf-qwef-2134-asff-asd2-23145d.data" :: String
      d =
        Disk (LIDPlain "othervg" "otherlv") [] "diskname" 1000 DiskRdWr
          Nothing Nothing "asdfgr-1234-5123-daf3-sdfw-134f43"
  in
    HUnit.assertBool "Unable to detect that plain Disk includes logical ID" $
      not (includesLogicalId vg_name lv_name d)

testSuite "Objects"
  [ 'prop_fillDict
  , 'prop_Disk_serialisation
  , 'prop_Inst_serialisation
  , 'prop_Network_serialisation
  , 'prop_Node_serialisation
  , 'prop_Config_serialisation
  , 'casePyCompatNetworks
  , 'casePyCompatNodegroups
  , 'casePyCompatInstances
  , 'prop_nextIp4Address
  , 'caseNextIp4Address
  , 'caseIncludeLogicalIdPlain
  , 'caseIncludeLogicalIdDrbd
  , 'caseNotIncludeLogicalIdPlain
  ]

{-# LANGUAGE TemplateHaskell, TypeSynonymInstances, FlexibleInstances,
  OverloadedStrings #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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
import Data.Word (Word32)
import GHC.Exts (IsString(..))
import System.Time (ClockTime(..))
import qualified Text.JSON as J

import Test.Ganeti.Query.Language ()
import Test.Ganeti.SlotMap (genSlotLimit)
import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Types ()

import qualified Ganeti.Constants as C
import qualified Ganeti.ConstantUtils as CU
import Ganeti.Network
import Ganeti.Objects as Objects
import qualified Ganeti.Objects.BitArray as BA
import Ganeti.JSON
import Ganeti.Types

-- * Arbitrary instances

instance Arbitrary (Container DataCollectorConfig) where
  arbitrary = do
    let names = CU.toList C.dataCollectorNames
    activations <- vector $ length names
    timeouts <- vector $ length names
    let configs = zipWith DataCollectorConfig activations timeouts
    return GenericContainer {
      fromContainer = Map.fromList $ zip names configs }

$(genArbitrary ''PartialNDParams)

instance Arbitrary Node where
  arbitrary = Node <$> genFQDN <*> genFQDN <*> genFQDN
              <*> arbitrary <*> arbitrary <*> arbitrary <*> genFQDN
              <*> arbitrary <*> arbitrary <*> arbitrary <*> arbitrary
              <*> arbitrary <*> arbitrary <*> genFQDN <*> arbitrary
              <*> (Set.fromList <$> genTags)

$(genArbitrary ''BlockDriver)

$(genArbitrary ''DiskMode)

instance Arbitrary LogicalVolume where
  arbitrary = LogicalVolume <$> validName <*> validName
    where
      validName = -- we intentionally omit '.' and '-' to avoid forbidden names
        listOf1 $ elements (['a'..'z'] ++ ['A'..'Z'] ++ ['0'..'9'] ++ "+_")

instance Arbitrary DiskLogicalId where
  arbitrary = oneof [ LIDPlain <$> arbitrary
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
  arbitrary =
   frequency [ (2, liftM RealDisk $ RealDiskData <$> arbitrary
                   <*> pure [] <*> arbitrary
                   <*> arbitrary <*> arbitrary <*> arbitrary
                   <*> arbitrary <*> arbitrary <*> arbitrary
                   <*> arbitrary <*> arbitrary <*> arbitrary
                   <*> arbitrary)
             , (1, liftM ForthcomingDisk $ ForthcomingDiskData <$> arbitrary
                   <*> pure [] <*> arbitrary
                   <*> arbitrary <*> arbitrary <*> arbitrary
                   <*> arbitrary <*> arbitrary <*> arbitrary
                   <*> arbitrary <*> arbitrary <*> arbitrary
                   <*> arbitrary)
             ]

-- FIXME: we should generate proper values, >=0, etc., but this is
-- hard for partial ones, where all must be wrapped in a 'Maybe'
$(genArbitrary ''PartialBeParams)

$(genArbitrary ''AdminState)

$(genArbitrary ''AdminStateSource)

$(genArbitrary ''PartialNicParams)

$(genArbitrary ''PartialNic)

instance Arbitrary ForthcomingInstanceData where
  arbitrary =
    ForthcomingInstanceData
      -- name
      <$> genMaybe genFQDN
      -- primary node
      <*> genMaybe genFQDN
      -- OS
      <*> genMaybe genFQDN
      -- hypervisor
      <*> arbitrary
      -- hvparams
      -- FIXME: add non-empty hvparams when they're a proper type
      <*> pure (GenericContainer Map.empty)
      -- beparams
      <*> arbitrary
      -- osparams
      <*> pure (GenericContainer Map.empty)
      -- osparams_private
      <*> pure (GenericContainer Map.empty)
      -- admin_state
      <*> genMaybe arbitrary
      -- admin_state_source
      <*> genMaybe arbitrary
      -- nics
      <*> arbitrary
      -- disks
      <*> vectorOf 5 arbitrary
      -- disks active
      <*> genMaybe arbitrary
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

instance Arbitrary RealInstanceData where
  arbitrary =
    RealInstanceData
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
      -- osparams_private
      <*> pure (GenericContainer Map.empty)
      -- admin_state
      <*> arbitrary
      -- admin_state_source
      <*> arbitrary
      -- nics
      <*> arbitrary
      -- disks
      <*> vectorOf 5 arbitrary
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

instance Arbitrary Instance where
  arbitrary = frequency [ (1, ForthcomingInstance <$> arbitrary)
                        , (3, RealInstance <$> arbitrary)
                        ]

-- | Generates an instance that is connected to the given networks
-- and possibly some other networks
genInstWithNets :: [String] -> Gen Instance
genInstWithNets nets = do
  plain_inst <- RealInstance <$> arbitrary
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
  more_nets <- vectorOf num_more_nets genUUID
  let genNic net = PartialNic mac ip nicparams net name uuid
      partial_nics = map (genNic . Just)
                         (List.nub (nets ++ more_nets))
      new_inst = case inst of
                   RealInstance rinst ->
                     RealInstance rinst { realInstNics = partial_nics }
                   ForthcomingInstance _ -> inst
  return new_inst

genDiskWithChildren :: Int -> Gen Disk
genDiskWithChildren num_children = do
  logicalid <- arbitrary
  children <- vectorOf num_children (genDiskWithChildren 0)
  nodes <- arbitrary
  ivname <- genName
  size <- arbitrary
  mode <- arbitrary
  name <- genMaybe genName
  spindles <- arbitrary
  params <- arbitrary
  uuid <- genName
  serial <- arbitrary
  time <- arbitrary
  return . RealDisk $
    RealDiskData logicalid children nodes ivname size mode name
      spindles params uuid serial time time

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

-- | No real arbitrary instance for 'GroupDiskParams' yet.
instance Arbitrary GroupDiskParams where
  arbitrary = return $ GenericContainer Map.empty

instance Arbitrary ClusterNicParams where
  arbitrary = (GenericContainer . Map.singleton C.ppDefault) <$> arbitrary

instance Arbitrary OsParams where
  arbitrary = (GenericContainer . Map.fromList) <$> arbitrary

instance Arbitrary Objects.ClusterOsParamsPrivate where
  arbitrary = (GenericContainer . Map.fromList) <$> arbitrary

instance Arbitrary a => Arbitrary (Private a) where
  arbitrary = Private <$> arbitrary

instance Arbitrary ClusterOsParams where
  arbitrary = (GenericContainer . Map.fromList) <$> arbitrary

instance Arbitrary ClusterBeParams where
  arbitrary = (GenericContainer . Map.fromList) <$> arbitrary

instance Arbitrary TagSet where
  arbitrary = Set.fromList <$> genTags

instance Arbitrary IAllocatorParams where
  arbitrary = return $ GenericContainer Map.empty

$(genArbitrary ''Cluster)

instance Arbitrary ConfigData where
  arbitrary = genEmptyCluster 0 >>= genConfigDataWithNetworks

instance Arbitrary AddressPool where
  arbitrary = AddressPool . BA.fromList <$> arbitrary

instance Arbitrary Network where
  arbitrary = genValidNetwork

instance Arbitrary FilterAction where
  arbitrary = oneof
    [ pure Accept
    , pure Pause
    , pure Reject
    , pure Continue
    , RateLimit <$> genSlotLimit
    ]

instance Arbitrary FilterPredicate where
  arbitrary = oneof
    [ FPJobId <$> arbitrary
    , FPOpCode <$> arbitrary
    , FPReason <$> arbitrary
    ]

instance Arbitrary FilterRule where
  arbitrary = FilterRule <$> arbitrary
                         <*> arbitrary
                         <*> arbitrary
                         <*> arbitrary
                         <*> arbitrary
                         <*> genUUID

instance Arbitrary MaintenanceData where
  arbitrary = MaintenanceData <$> (fromPositive <$> arbitrary)
                              <*> arbitrary
                              <*> arbitrary
                              <*> arbitrary
                              <*> arbitrary

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
  let n = Network name mac_prefix (mkIp4Network net netmask) net6 gateway
          gateway6 res ext_res uuid ctime mtime 0 Set.empty
  return n

-- | Generate an arbitrary string consisting of '0' and '1' of the given length.
genBitString :: Int -> Gen AddressPool
genBitString len =
  (AddressPool . BA.fromList) `liftM` vectorOf len (elements [False, True])

-- | Generate an arbitrary string consisting of '0' and '1' of the maximum given
-- length.
genBitStringMaxLen :: Int -> Gen AddressPool
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
                          let newname = takeWhile (/= '.') (nodeName n)
                                        ++ "-" ++ show idx
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
      disks = GenericContainer Map.empty
      filters = GenericContainer Map.empty
  maintenance <- arbitrary
  let contgroups = GenericContainer $ Map.singleton guuid grp
  serial <- arbitrary
  -- timestamp fields
  ctime <- arbitrary
  mtime <- arbitrary
  cluster <- resize 8 arbitrary
  let c = ConfigData version cluster contnodes contgroups continsts networks
            disks filters ctime maintenance mtime serial
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
  in conjoin [ counterexample "Empty custom filling"
               (fillDict d_map Map.empty [] == d_map)
             , counterexample "Empty defaults filling"
               (fillDict Map.empty c_map [] == c_map)
             , counterexample "Delete all keys"
               (fillDict d_map c_map (d_keys++c_keys) == Map.empty)
             ]

prop_LogicalVolume_serialisation :: LogicalVolume -> Property
prop_LogicalVolume_serialisation = testSerialisation

prop_LogicalVolume_deserialisationFail :: Property
prop_LogicalVolume_deserialisationFail =
  conjoin . map (testDeserialisationFail (LogicalVolume "" "")) $
    [ J.JSArray []
    , J.JSString $ J.toJSString "/abc"
    , J.JSString $ J.toJSString "abc/"
    , J.JSString $ J.toJSString "../."
    , J.JSString $ J.toJSString "g/snapshot"
    , J.JSString $ J.toJSString "g/a_mimagex"
    , J.JSString $ J.toJSString "g/r;3"
    ]

-- | Test that the serialisation of 'DiskLogicalId', which is
-- implemented manually, is idempotent. Since we don't have a
-- standalone JSON instance for DiskLogicalId (it's a data type that
-- expands over two fields in a JSObject), we test this by actially
-- testing entire Disk serialisations. So this tests two things at
-- once, basically.
prop_Disk_serialisation :: Disk -> Property
prop_Disk_serialisation = testSerialisation

prop_Disk_array_serialisation :: Disk -> Property
prop_Disk_array_serialisation = testArraySerialisation

-- | Check that node serialisation is idempotent.
prop_Node_serialisation :: Node -> Property
prop_Node_serialisation = testSerialisation

-- | Check that instance serialisation is idempotent.
prop_Inst_serialisation :: Instance -> Property
prop_Inst_serialisation = testSerialisation

-- | Check that address pool serialisation is idempotent.
prop_AddressPool_serialisation :: AddressPool -> Property
prop_AddressPool_serialisation = testSerialisation

-- | Check that network serialisation is idempotent.
prop_Network_serialisation :: Network -> Property
prop_Network_serialisation = testSerialisation

-- | Check that filter action serialisation is idempotent.
prop_FilterAction_serialisation :: FilterAction -> Property
prop_FilterAction_serialisation = testSerialisation

-- | Check that filter predicate serialisation is idempotent.
prop_FilterPredicate_serialisation :: FilterPredicate -> Property
prop_FilterPredicate_serialisation = testSerialisation

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
    (getFreeCount net, getReservedCount net, net)

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

instance Arbitrary Ip4Address where
  arbitrary = liftM mkIp4Address $ (,,,) <$> choose (0, 255)
                                         <*> choose (0, 255)
                                         <*> choose (0, 255)
                                         <*> choose (0, 255)

$(genArbitrary ''Ip4Network)

-- | Tests conversions of ip addresses from/to numbers.
prop_ip4AddressAsNum :: Ip4Address -> Property
prop_ip4AddressAsNum ip4 =
  ip4AddressFromNumber (ip4AddressToNumber ip4) ==? ip4

-- | Tests that the number produced by 'ip4AddressToNumber' has the correct
-- order of bytes.
prop_ip4AddressToNumber :: Word32 -> Property
prop_ip4AddressToNumber w =
  let byte :: Int -> Word32
      byte i = (w `div` (256^i)) `mod` 256
      ipaddr = List.intercalate "." $ map (show . byte) [3,2..0]
  in ip4AddressToNumber <$> readIp4Address ipaddr
     ==? (return (toInteger w) :: Either String Integer)

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

-- | A helper function for creating 'LIDPlain' values.
mkLIDPlain :: String -> String -> DiskLogicalId
mkLIDPlain = (LIDPlain .) . LogicalVolume

-- | Tests that the logical ID is correctly found in a plain disk
caseIncludeLogicalIdPlain :: HUnit.Assertion
caseIncludeLogicalIdPlain =
  let vg_name = "xenvg" :: String
      lv_name = "1234sdf-qwef-2134-asff-asd2-23145d.data" :: String
      lv = LogicalVolume vg_name lv_name
      time = TOD 0 0
      d = RealDisk $
        RealDiskData (LIDPlain lv) [] ["node1.example.com"] "diskname"
          1000 DiskRdWr
          Nothing Nothing Nothing "asdfgr-1234-5123-daf3-sdfw-134f43"
          0 time time
  in
    HUnit.assertBool "Unable to detect that plain Disk includes logical ID" $
      includesLogicalId lv d

-- | Tests that the logical ID is correctly found in a DRBD disk
caseIncludeLogicalIdDrbd :: HUnit.Assertion
caseIncludeLogicalIdDrbd =
  let vg_name = "xenvg" :: String
      lv_name = "1234sdf-qwef-2134-asff-asd2-23145d.data" :: String
      time = TOD 0 0
      d = RealDisk $
        RealDiskData
          (LIDDrbd8 "node1.example.com" "node2.example.com" 2000 1 5 "secret")
          [ RealDisk $ RealDiskData (mkLIDPlain "onevg" "onelv") []
              ["node1.example.com", "node2.example.com"] "disk1" 1000 DiskRdWr
              Nothing Nothing Nothing "145145-asdf-sdf2-2134-asfd-534g2x"
              0 time time
          , RealDisk $ RealDiskData (mkLIDPlain vg_name lv_name) []
              ["node1.example.com", "node2.example.com"] "disk2" 1000 DiskRdWr
              Nothing Nothing Nothing "6gd3sd-423f-ag2j-563b-dg34-gj3fse"
              0 time time
          ] ["node1.example.com", "node2.example.com"] "diskname" 1000 DiskRdWr
          Nothing Nothing Nothing
          "asdfgr-1234-5123-daf3-sdfw-134f43" 0 time time
  in
    HUnit.assertBool "Unable to detect that plain Disk includes logical ID" $
      includesLogicalId (LogicalVolume vg_name lv_name) d

-- | Tests that the logical ID is correctly NOT found in a plain disk
caseNotIncludeLogicalIdPlain :: HUnit.Assertion
caseNotIncludeLogicalIdPlain =
  let vg_name = "xenvg" :: String
      lv_name = "1234sdf-qwef-2134-asff-asd2-23145d.data" :: String
      time = TOD 0 0
      d = RealDisk $
        RealDiskData (mkLIDPlain "othervg" "otherlv") [] ["node1.example.com"]
          "diskname" 1000 DiskRdWr Nothing Nothing Nothing
          "asdfgr-1234-5123-daf3-sdfw-134f43"
          0 time time
  in
    HUnit.assertBool "Unable to detect that plain Disk includes logical ID" $
      not (includesLogicalId (LogicalVolume vg_name lv_name) d)

testSuite "Objects"
  [ 'prop_fillDict
  , 'prop_LogicalVolume_serialisation
  , 'prop_LogicalVolume_deserialisationFail
  , 'prop_Disk_serialisation
  , 'prop_Disk_array_serialisation
  , 'prop_Inst_serialisation
  , 'prop_AddressPool_serialisation
  , 'prop_Network_serialisation
  , 'prop_Node_serialisation
  , 'prop_Config_serialisation
  , 'prop_FilterAction_serialisation
  , 'prop_FilterPredicate_serialisation
  , 'casePyCompatNetworks
  , 'casePyCompatNodegroups
  , 'casePyCompatInstances
  , 'prop_ip4AddressAsNum
  , 'prop_ip4AddressToNumber
  , 'caseNextIp4Address
  , 'caseIncludeLogicalIdPlain
  , 'caseIncludeLogicalIdDrbd
  , 'caseNotIncludeLogicalIdPlain
  ]

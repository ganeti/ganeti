{-# LANGUAGE TemplateHaskell, TypeSynonymInstances, FlexibleInstances #-}
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

module Test.Ganeti.Objects
  ( testObjects
  , Hypervisor(..)
  , Node(..)
  , genEmptyCluster
  ) where

import Test.QuickCheck

import Control.Applicative
import qualified Data.Map as Map
import qualified Data.Set as Set

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.Constants as C
import Ganeti.Objects as Objects
import Ganeti.JSON

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitrary instances

$(genArbitrary ''Hypervisor)

$(genArbitrary ''PartialNDParams)

instance Arbitrary Node where
  arbitrary = Node <$> getFQDN <*> getFQDN <*> getFQDN
              <*> arbitrary <*> arbitrary <*> arbitrary <*> getFQDN
              <*> arbitrary <*> arbitrary <*> arbitrary <*> arbitrary
              <*> arbitrary <*> arbitrary <*> getFQDN <*> arbitrary
              <*> (Set.fromList <$> genTags)

$(genArbitrary ''FileDriver)

$(genArbitrary ''BlockDriver)

$(genArbitrary ''DiskMode)

instance Arbitrary DiskLogicalId where
  arbitrary = oneof [ LIDPlain <$> arbitrary <*> arbitrary
                    , LIDDrbd8 <$> getFQDN <*> getFQDN <*> arbitrary
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

$(genArbitrary ''DiskTemplate)

$(genArbitrary ''AdminState)

$(genArbitrary ''NICMode)

$(genArbitrary ''PartialNicParams)

$(genArbitrary ''PartialNic)

instance Arbitrary Instance where
  arbitrary =
    Instance
      <$> getFQDN <*> getFQDN <*> getFQDN -- OS name, but...
      <*> arbitrary
      -- FIXME: add non-empty hvparams when they're a proper type
      <*> pure (Container Map.empty) <*> arbitrary
      -- ... and for OSParams
      <*> pure (Container Map.empty) <*> arbitrary <*> arbitrary
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

-- | FIXME: This generates completely random data, without normal
-- validation rules.
instance Arbitrary NodeGroup where
  arbitrary = NodeGroup <$> getFQDN <*> pure [] <*> arbitrary <*> arbitrary
                        <*> arbitrary <*> pure (Container Map.empty)
                        -- ts
                        <*> arbitrary <*> arbitrary
                        -- uuid
                        <*> arbitrary
                        -- serial
                        <*> arbitrary
                        -- tags
                        <*> (Set.fromList <$> genTags)

$(genArbitrary ''AllocPolicy)
$(genArbitrary ''FilledISpecParams)
$(genArbitrary ''FilledIPolicy)
$(genArbitrary ''IpFamily)
$(genArbitrary ''FilledNDParams)
$(genArbitrary ''FilledNicParams)
$(genArbitrary ''FilledBeParams)

-- | No real arbitrary instance for 'ClusterHvParams' yet.
instance Arbitrary ClusterHvParams where
  arbitrary = return $ Container Map.empty

-- | No real arbitrary instance for 'OsHvParams' yet.
instance Arbitrary OsHvParams where
  arbitrary = return $ Container Map.empty

instance Arbitrary ClusterNicParams where
  arbitrary = (Container . Map.singleton C.ppDefault) <$> arbitrary

instance Arbitrary OsParams where
  arbitrary = (Container . Map.fromList) <$> arbitrary

instance Arbitrary ClusterOsParams where
  arbitrary = (Container . Map.fromList) <$> arbitrary

instance Arbitrary ClusterBeParams where
  arbitrary = (Container . Map.fromList) <$> arbitrary

instance Arbitrary TagSet where
  arbitrary = Set.fromList <$> genTags

$(genArbitrary ''Cluster)

-- | Generator for config data with an empty cluster (no instances),
-- with N defined nodes.
genEmptyCluster :: Int -> Gen ConfigData
genEmptyCluster ncount = do
  nodes <- vector ncount
  version <- arbitrary
  let guuid = "00"
      nodes' = zipWith (\n idx -> n { nodeGroup = guuid,
                                      nodeName = nodeName n ++ show idx })
               nodes [(1::Int)..]
      contnodes = Container . Map.fromList $ map (\n -> (nodeName n, n)) nodes'
      continsts = Container Map.empty
  grp <- arbitrary
  let contgroups = Container $ Map.singleton guuid grp
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
  in printTestCase "Empty custom filling"
      (fillDict d_map Map.empty [] == d_map) .&&.
     printTestCase "Empty defaults filling"
      (fillDict Map.empty c_map [] == c_map) .&&.
     printTestCase "Delete all keys"
      (fillDict d_map c_map (d_keys++c_keys) == Map.empty)

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

-- | Check config serialisation.
prop_Config_serialisation :: Property
prop_Config_serialisation =
  forAll (choose (0, maxNodes `div` 4) >>= genEmptyCluster) testSerialisation

testSuite "Objects"
  [ 'prop_fillDict
  , 'prop_Disk_serialisation
  , 'prop_Inst_serialisation
  , 'prop_Node_serialisation
  , 'prop_Config_serialisation
  ]

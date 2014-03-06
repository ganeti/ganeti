{-# LANGUAGE TemplateHaskell #-}
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

module Test.Ganeti.Rpc (testRpc) where

import Test.QuickCheck
import Test.QuickCheck.Monadic (monadicIO, run, stop)

import Control.Applicative
import qualified Data.Map as Map

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Objects (genInst)

import qualified Ganeti.Rpc as Rpc
import qualified Ganeti.Objects as Objects
import qualified Ganeti.Types as Types
import qualified Ganeti.JSON as JSON
import Ganeti.Types

instance Arbitrary Rpc.RpcCallInstanceConsoleInfo where
  arbitrary = Rpc.RpcCallInstanceConsoleInfo <$> genConsoleInfoCallParams

instance Arbitrary Rpc.Compressed where
  arbitrary = Rpc.toCompressed <$> arbitrary

genStorageUnit :: Gen StorageUnit
genStorageUnit = do
  storage_type <- arbitrary
  storage_key <- genName
  storage_es <- arbitrary
  return $ addParamsToStorageUnit storage_es (SURaw storage_type storage_key)

genStorageUnits :: Gen [StorageUnit]
genStorageUnits = do
  num_storage_units <- choose (0, 5)
  vectorOf num_storage_units genStorageUnit

genStorageUnitMap :: Gen (Map.Map String [StorageUnit])
genStorageUnitMap = do
  num_nodes <- choose (0,5)
  node_uuids <- vectorOf num_nodes genName
  storage_units_list <- vectorOf num_nodes genStorageUnits
  return $ Map.fromList (zip node_uuids storage_units_list)

-- FIXME: Generate more interesting hvparams
-- | Generate Hvparams
genHvParams :: Gen Objects.HvParams
genHvParams = return $ JSON.GenericContainer Map.empty

-- | Generate hypervisor specifications to be used for the NodeInfo call
genHvSpecs :: Gen [(Types.Hypervisor, Objects.HvParams)]
genHvSpecs = do
  numhv <- choose (0, 5)
  hvs <- vectorOf numhv arbitrary
  hvparams <- vectorOf numhv genHvParams
  let specs = zip hvs hvparams
  return specs

instance Arbitrary Rpc.RpcCallAllInstancesInfo where
  arbitrary = Rpc.RpcCallAllInstancesInfo <$> genHvSpecs

instance Arbitrary Rpc.RpcCallInstanceList where
  arbitrary = Rpc.RpcCallInstanceList <$> arbitrary

instance Arbitrary Rpc.RpcCallNodeInfo where
  arbitrary = Rpc.RpcCallNodeInfo <$> genStorageUnitMap <*> genHvSpecs

-- | Generates per-instance console info params for the 'InstanceConsoleInfo'
-- call.
genConsoleInfoCallParams :: Gen [(String, Rpc.InstanceConsoleInfoParams)]
genConsoleInfoCallParams = do
  numInstances <- choose (0, 3)
  names <- vectorOf numInstances arbitrary
  params <- vectorOf numInstances genInstanceConsoleInfoParams
  return $ zip names params

-- | Generates parameters for the console info call, consisting of an instance
-- object, node object, 'HvParams', and 'FilledBeParams'.
genInstanceConsoleInfoParams :: Gen Rpc.InstanceConsoleInfoParams
genInstanceConsoleInfoParams = Rpc.InstanceConsoleInfoParams <$>
  genInst <*> arbitrary <*> arbitrary <*> genHvParams <*> arbitrary

-- | Monadic check that, for an offline node and a call that does not support
-- offline nodes, we get a OfflineNodeError response.
runOfflineTest :: (Rpc.Rpc a b, Eq b, Show b) => a -> Property
runOfflineTest call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left Rpc.OfflineNodeError)]

prop_noffl_request_allinstinfo :: Rpc.RpcCallAllInstancesInfo -> Property
prop_noffl_request_allinstinfo = runOfflineTest

prop_noffl_request_instconsinfo :: Rpc.RpcCallInstanceConsoleInfo -> Property
prop_noffl_request_instconsinfo = runOfflineTest

prop_noffl_request_instlist :: Rpc.RpcCallInstanceList -> Property
prop_noffl_request_instlist = runOfflineTest

prop_noffl_request_nodeinfo :: Rpc.RpcCallNodeInfo -> Property
prop_noffl_request_nodeinfo = runOfflineTest

-- | Test that the serialisation of 'Compressed' is idempotent.
prop_Compressed_serialisation :: Rpc.Compressed -> Property
prop_Compressed_serialisation = testSerialisation

testSuite "Rpc"
  [ 'prop_noffl_request_allinstinfo
  , 'prop_noffl_request_instconsinfo
  , 'prop_noffl_request_instlist
  , 'prop_noffl_request_nodeinfo
  , 'prop_Compressed_serialisation
  ]

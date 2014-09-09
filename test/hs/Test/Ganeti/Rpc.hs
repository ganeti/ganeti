{-# LANGUAGE TemplateHaskell #-}
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

module Test.Ganeti.Rpc (testRpc) where

import Test.QuickCheck
import Test.QuickCheck.Monadic (monadicIO, run, stop)

import Control.Applicative
import qualified Data.Map as Map

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Objects ()

import qualified Ganeti.Rpc as Rpc
import qualified Ganeti.Objects as Objects
import qualified Ganeti.Types as Types
import qualified Ganeti.JSON as JSON
import Ganeti.Types

instance Arbitrary Rpc.RpcCallAllInstancesInfo where
  arbitrary = Rpc.RpcCallAllInstancesInfo <$> arbitrary

instance Arbitrary Rpc.RpcCallInstanceList where
  arbitrary = Rpc.RpcCallInstanceList <$> arbitrary

instance Arbitrary Rpc.RpcCallNodeInfo where
  arbitrary = Rpc.RpcCallNodeInfo <$> genStorageUnitMap <*> genHvSpecs

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

-- | Generate hypervisor specifications to be used for the NodeInfo call
genHvSpecs :: Gen [ (Types.Hypervisor, Objects.HvParams) ]
genHvSpecs = do
  numhv <- choose (0, 5)
  hvs <- vectorOf numhv arbitrary
  hvparams <- vectorOf numhv genHvParams
  let specs = zip hvs hvparams
  return specs

-- FIXME: Generate more interesting hvparams
-- | Generate Hvparams
genHvParams :: Gen Objects.HvParams
genHvParams = return $ JSON.GenericContainer Map.empty

-- | Monadic check that, for an offline node and a call that does not
-- offline nodes, we get a OfflineNodeError response.
-- FIXME: We need a way of generalizing this, running it for
-- every call manually will soon get problematic
prop_noffl_request_allinstinfo :: Rpc.RpcCallAllInstancesInfo -> Property
prop_noffl_request_allinstinfo call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left Rpc.OfflineNodeError)]

prop_noffl_request_instlist :: Rpc.RpcCallInstanceList -> Property
prop_noffl_request_instlist call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left Rpc.OfflineNodeError)]

prop_noffl_request_nodeinfo :: Rpc.RpcCallNodeInfo -> Property
prop_noffl_request_nodeinfo call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left Rpc.OfflineNodeError)]

testSuite "Rpc"
  [ 'prop_noffl_request_allinstinfo
  , 'prop_noffl_request_instlist
  , 'prop_noffl_request_nodeinfo
  ]

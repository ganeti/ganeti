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

module Test.Ganeti.Rpc (testRpc) where

import Test.QuickCheck
import Test.QuickCheck.Monadic (monadicIO, run, stop)

import Control.Applicative

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Objects ()

import qualified Ganeti.Rpc as Rpc
import qualified Ganeti.Objects as Objects

instance Arbitrary Rpc.RpcCallAllInstancesInfo where
  arbitrary = Rpc.RpcCallAllInstancesInfo <$> arbitrary

instance Arbitrary Rpc.RpcCallInstanceList where
  arbitrary = Rpc.RpcCallInstanceList <$> arbitrary

instance Arbitrary Rpc.RpcCallNodeInfo where
  arbitrary = Rpc.RpcCallNodeInfo <$> arbitrary <*> arbitrary

-- | Monadic check that, for an offline node and a call that does not
-- offline nodes, we get a OfflineNodeError response.
-- FIXME: We need a way of generalizing this, running it for
-- every call manually will soon get problematic
prop_Rpc_noffl_request_allinstinfo :: Rpc.RpcCallAllInstancesInfo -> Property
prop_Rpc_noffl_request_allinstinfo call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left (Rpc.OfflineNodeError node))]

prop_Rpc_noffl_request_instlist :: Rpc.RpcCallInstanceList -> Property
prop_Rpc_noffl_request_instlist call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left (Rpc.OfflineNodeError node))]

prop_Rpc_noffl_request_nodeinfo :: Rpc.RpcCallNodeInfo -> Property
prop_Rpc_noffl_request_nodeinfo call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left (Rpc.OfflineNodeError node))]

testSuite "Rpc"
  [ 'prop_Rpc_noffl_request_allinstinfo
  , 'prop_Rpc_noffl_request_instlist
  , 'prop_Rpc_noffl_request_nodeinfo
  ]

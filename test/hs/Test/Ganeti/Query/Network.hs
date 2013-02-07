{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for Network Queries.

-}

{-

Copyright (C) 2013 Google Inc.

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

module Test.Ganeti.Query.Network
  ( testQuery_Network
  ) where

import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Query.Network
import Ganeti.Types

import Test.Ganeti.Objects
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper

import Test.QuickCheck

import qualified Data.Map as Map
import Data.Maybe

instance Arbitrary ConfigData where
  arbitrary = genEmptyCluster 0 >>= genConfigDataWithNetworks

-- | Check if looking up a valid network ID of a nodegroup yields
-- a non-Nothing result.
prop_getGroupConnection :: NodeGroup -> Property
prop_getGroupConnection group =
  let net_keys = (Map.keys . fromContainer . groupNetworks) group
  in True ==? all
    (\nk -> isJust (getGroupConnection nk group)) net_keys

-- | Checks if looking up an ID of a non-existing network in a node group
-- yields 'Nothing'.
prop_getGroupConnection_notFound :: NodeGroup -> String -> Property
prop_getGroupConnection_notFound group uuid =
  let net_keys = (Map.keys . fromContainer . groupNetworks) group
  in notElem uuid net_keys ==> isNothing (getGroupConnection uuid group)

-- | Check if getting the network's UUID from the config actually gets the
-- correct UUIDs.
prop_getNetworkUuid :: ConfigData -> Property
prop_getNetworkUuid cfg =
  let nets = (Map.elems . fromContainer . configNetworks) cfg
  in True ==? all
    (\n -> fromJust (getNetworkUuid cfg ((fromNonEmpty . networkName) n))
    == networkUuid n) nets

-- | Check if trying to get a UUID of a non-existing networks results in
-- 'Nothing'.
prop_getNetworkUuid_notFound :: ConfigData -> String -> Property
prop_getNetworkUuid_notFound cfg uuid =
  let net_keys = (Map.keys . fromContainer . configNetworks) cfg
  in notElem uuid net_keys ==> isNothing (getNetworkUuid cfg uuid)

-- | Checks whether actually connected instances are identified as such.
prop_instIsConnected :: ConfigData -> Property
prop_instIsConnected cfg =
  let nets = (fromContainer . configNetworks) cfg
      net_keys = Map.keys nets
      net_names = map (fromNonEmpty . networkName) (Map.elems nets)
  in  forAll (genInstWithNets net_names) $ \inst ->
      True ==? all (\nk -> instIsConnected cfg nk inst) net_keys

-- | Tests whether instances that are not connected to a network are
-- correctly classified as such.
prop_instIsConnected_notFound :: ConfigData -> String -> Property
prop_instIsConnected_notFound cfg network_uuid =
  let nets = (fromContainer . configNetworks) cfg
      net_keys = Map.keys nets
      net_names = map (fromNonEmpty . networkName) (Map.elems nets)
  in  notElem network_uuid net_keys ==>
      forAll (genInstWithNets net_names) $ \inst ->
        not (instIsConnected cfg network_uuid inst)

testSuite "Query_Network"
  [ 'prop_getNetworkUuid
  , 'prop_getNetworkUuid_notFound
  , 'prop_getGroupConnection
  , 'prop_getGroupConnection_notFound
  , 'prop_instIsConnected
  , 'prop_instIsConnected_notFound
  ]



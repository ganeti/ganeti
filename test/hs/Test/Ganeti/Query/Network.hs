{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for Network Queries.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Test.Ganeti.Query.Network
  ( testQuery_Network
  ) where

import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Query.Network

import Test.Ganeti.Objects
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper

import Test.QuickCheck

import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.Map as Map
import Data.Maybe

-- | Check if looking up a valid network ID of a nodegroup yields
-- a non-Nothing result.
prop_getGroupConnection :: NodeGroup -> Property
prop_getGroupConnection group =
  let net_keys = map UTF8.toString . Map.keys . fromContainer . groupNetworks
                 $ group
  in True ==? all
    (\nk -> isJust (getGroupConnection nk group)) net_keys

-- | Checks if looking up an ID of a non-existing network in a node group
-- yields 'Nothing'.
prop_getGroupConnection_notFound :: NodeGroup -> String -> Property
prop_getGroupConnection_notFound group uuid =
  let net_map = fromContainer . groupNetworks $ group
  in not (UTF8.fromString uuid `Map.member` net_map)
     ==> isNothing (getGroupConnection uuid group)

-- | Checks whether actually connected instances are identified as such.
prop_instIsConnected :: ConfigData -> Property
prop_instIsConnected cfg =
  let nets = (fromContainer . configNetworks) cfg
      net_keys = map UTF8.toString $ Map.keys nets
  in  forAll (genInstWithNets net_keys) $ \inst ->
      True ==? all (`instIsConnected` inst) net_keys

-- | Tests whether instances that are not connected to a network are
-- correctly classified as such.
prop_instIsConnected_notFound :: ConfigData -> String -> Property
prop_instIsConnected_notFound cfg network_uuid =
  let nets = (fromContainer . configNetworks) cfg
      net_keys = map UTF8.toString $ Map.keys nets
  in  notElem network_uuid net_keys ==>
      forAll (genInstWithNets net_keys) $ \inst ->
        not (instIsConnected network_uuid inst)

testSuite "Query_Network"
  [ 'prop_getGroupConnection
  , 'prop_getGroupConnection_notFound
  , 'prop_instIsConnected
  , 'prop_instIsConnected_notFound
  ]



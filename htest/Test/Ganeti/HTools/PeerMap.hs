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

module Test.Ganeti.HTools.PeerMap (testPeerMap) where

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.HTools.PeerMap as PeerMap

-- | Make sure add is idempotent.
prop_PeerMap_addIdempotent :: PeerMap.PeerMap
                           -> PeerMap.Key -> PeerMap.Elem -> Property
prop_PeerMap_addIdempotent pmap key em =
  fn puniq ==? fn (fn puniq)
    where fn = PeerMap.add key em
          puniq = PeerMap.accumArray const pmap

-- | Make sure remove is idempotent.
prop_PeerMap_removeIdempotent :: PeerMap.PeerMap -> PeerMap.Key -> Property
prop_PeerMap_removeIdempotent pmap key =
  fn puniq ==? fn (fn puniq)
    where fn = PeerMap.remove key
          puniq = PeerMap.accumArray const pmap

-- | Make sure a missing item returns 0.
prop_PeerMap_findMissing :: PeerMap.PeerMap -> PeerMap.Key -> Property
prop_PeerMap_findMissing pmap key =
  PeerMap.find key (PeerMap.remove key puniq) ==? 0
    where puniq = PeerMap.accumArray const pmap

-- | Make sure an added item is found.
prop_PeerMap_addFind :: PeerMap.PeerMap
                     -> PeerMap.Key -> PeerMap.Elem -> Property
prop_PeerMap_addFind pmap key em =
  PeerMap.find key (PeerMap.add key em puniq) ==? em
    where puniq = PeerMap.accumArray const pmap

-- | Manual check that maxElem returns the maximum indeed, or 0 for null.
prop_PeerMap_maxElem :: PeerMap.PeerMap -> Property
prop_PeerMap_maxElem pmap =
  PeerMap.maxElem puniq ==? if null puniq then 0
                              else (maximum . snd . unzip) puniq
    where puniq = PeerMap.accumArray const pmap

-- | List of tests for the PeerMap module.
testSuite "PeerMap"
            [ 'prop_PeerMap_addIdempotent
            , 'prop_PeerMap_removeIdempotent
            , 'prop_PeerMap_maxElem
            , 'prop_PeerMap_addFind
            , 'prop_PeerMap_findMissing
            ]

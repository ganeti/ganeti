{-| Unittests for ganeti-htools

-}

{-

Copyright (C) 2009 Google Inc.

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

module Ganeti.HTools.QC
    ( test_PeerMap
    , test_Container
    , test_Instance
    , test_Node
    ) where

import Test.QuickCheck
import Test.QuickCheck.Batch
import Data.Maybe
import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.IAlloc as IAlloc
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.PeerMap as PeerMap
import qualified Ganeti.HTools.Rapi as Rapi
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Utils as Utils

-- copied from the introduction to quickcheck
instance Arbitrary Char where
    arbitrary = choose ('\32', '\128')

-- let's generate a random instance
instance Arbitrary Instance.Instance where
    arbitrary = do
      name <- arbitrary
      mem <- choose(0, 100)
      dsk <- choose(0, 100)
      run_st <- arbitrary
      pn <- arbitrary
      sn <- arbitrary
      return $ Instance.create name mem dsk run_st pn sn

-- and a random node
instance Arbitrary Node.Node where
    arbitrary = do
      name <- arbitrary
      mem_t <- arbitrary
      mem_f <- choose (0, mem_t)
      mem_n <- choose (0, mem_t - mem_f)
      dsk_t <- arbitrary
      dsk_f <- choose (0, dsk_t)
      offl <- arbitrary
      let n = Node.create name (fromIntegral mem_t) mem_n mem_f
              (fromIntegral dsk_t) dsk_f offl
          n' = Node.buildPeers n Container.empty
      return n'

-- | Make sure add is idempotent
prop_PeerMap_addIdempotent pmap key elem =
    fn puniq == fn (fn puniq)
    where _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key, elem::PeerMap.Elem)
          fn = PeerMap.add key elem
          puniq = PeerMap.accumArray const pmap

-- | Make sure remove is idempotent
prop_PeerMap_removeIdempotent pmap key =
    fn puniq == fn (fn puniq)
    where _types = (pmap::PeerMap.PeerMap, key::PeerMap.Key)
          fn = PeerMap.remove key
          puniq = PeerMap.accumArray const pmap

-- | Make sure a missing item returns 0
prop_PeerMap_findMissing pmap key =
    PeerMap.find key (PeerMap.remove key puniq) == 0
    where _types = (pmap::PeerMap.PeerMap, key::PeerMap.Key)
          puniq = PeerMap.accumArray const pmap

-- | Make sure an added item is found
prop_PeerMap_addFind pmap key elem =
    PeerMap.find key (PeerMap.add key elem puniq) == elem
    where _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key, elem::PeerMap.Elem)
          puniq = PeerMap.accumArray const pmap

-- | Manual check that maxElem returns the maximum indeed, or 0 for null
prop_PeerMap_maxElem pmap =
    PeerMap.maxElem puniq == if null puniq then 0
                             else (maximum . snd . unzip) puniq
    where _types = pmap::PeerMap.PeerMap
          puniq = PeerMap.accumArray const pmap

test_PeerMap =
    [ run prop_PeerMap_addIdempotent
    , run prop_PeerMap_removeIdempotent
    , run prop_PeerMap_maxElem
    , run prop_PeerMap_addFind
    , run prop_PeerMap_findMissing
    ]

-- Container tests

prop_Container_addTwo cdata i1 i2 =
    fn i1 i2 cont == fn i2 i1 cont &&
       fn i1 i2 cont == fn i1 i2 (fn i1 i2 cont)
    where _types = (cdata::[Int],
                    i1::Int, i2::Int)
          cont = foldl (\c x -> Container.add x x c) Container.empty cdata
          fn x1 x2 = Container.addTwo x1 x1 x2 x2

test_Container =
    [ run prop_Container_addTwo ]

-- Simple instance tests, we only have setter/getters

prop_Instance_setIdx inst idx =
    Instance.idx (Instance.setIdx inst idx) == idx
    where _types = (inst::Instance.Instance, idx::Types.Idx)

prop_Instance_setName inst name =
    Instance.name (Instance.setName inst name) == name
    where _types = (inst::Instance.Instance, name::String)

prop_Instance_setPri inst pdx =
    Instance.pnode (Instance.setPri inst pdx) == pdx
    where _types = (inst::Instance.Instance, pdx::Types.Ndx)

prop_Instance_setSec inst sdx =
    Instance.snode (Instance.setSec inst sdx) == sdx
    where _types = (inst::Instance.Instance, sdx::Types.Ndx)

prop_Instance_setBoth inst pdx sdx =
    Instance.pnode si == pdx && Instance.snode si == sdx
    where _types = (inst::Instance.Instance, pdx::Types.Ndx, sdx::Types.Ndx)
          si = Instance.setBoth inst pdx sdx

test_Instance =
    [ run prop_Instance_setIdx
    , run prop_Instance_setName
    , run prop_Instance_setPri
    , run prop_Instance_setSec
    , run prop_Instance_setBoth
    ]

-- Node tests

-- | Check that an instance add with too high memory or disk will be rejected
prop_Node_addPri node inst = (Instance.mem inst >= Node.f_mem node ||
                              Instance.dsk inst >= Node.f_dsk node) &&
                             (not $ Node.failN1 node)
                             ==>
                             isNothing(Node.addPri node inst)
    where _types = (node::Node.Node, inst::Instance.Instance)


-- | Check that an instance add with too high memory or disk will be rejected
prop_Node_addSec node inst pdx =
    (Instance.mem inst >= (Node.f_mem node - Node.r_mem node) ||
     Instance.dsk inst >= Node.f_dsk node) &&
    (not $ Node.failN1 node)
    ==> isNothing(Node.addSec node inst pdx)
        where _types = (node::Node.Node, inst::Instance.Instance, pdx::Int)

test_Node =
    [ run prop_Node_addPri
    , run prop_Node_addSec
    ]

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
    ( testPeerMap
    , testContainer
    , testInstance
    , testNode
    , testText
    , testCluster
    ) where

import Test.QuickCheck
import Test.QuickCheck.Batch
import Data.Maybe
import qualified Data.Map
import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.IAlloc as IAlloc
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.PeerMap as PeerMap
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Utils as Utils

-- | Maximum memory (1TiB, somewhat random value)
maxMem :: Int
maxMem = 1024 * 1024

-- | Maximum disk (8TiB, somewhat random value)
maxDsk :: Int
maxDsk = 1024 * 1024 * 8

-- | Max CPUs (1024, somewhat random value)
maxCpu :: Int
maxCpu = 1024

-- | Simple checker for whether OpResult is fail or pass
isFailure :: Types.OpResult a -> Bool
isFailure (Types.OpFail _) = True
isFailure _ = False

-- | Simple checker for whether Result is fail or pass
isOk :: Types.Result a -> Bool
isOk (Types.Ok _ ) = True
isOk _ = False

-- copied from the introduction to quickcheck
instance Arbitrary Char where
    arbitrary = choose ('\32', '\128')

-- let's generate a random instance
instance Arbitrary Instance.Instance where
    arbitrary = do
      name <- arbitrary
      mem <- choose (0, maxMem)
      dsk <- choose (0, maxDsk)
      run_st <- elements ["ERROR_up", "ERROR_down", "ADMIN_down"
                         , "ERROR_nodedown", "ERROR_nodeoffline"
                         , "running"
                         , "no_such_status1", "no_such_status2"]
      pn <- arbitrary
      sn <- arbitrary
      vcpus <- choose (0, maxCpu)
      return $ Instance.create name mem dsk vcpus run_st [] pn sn

-- and a random node
instance Arbitrary Node.Node where
    arbitrary = do
      name <- arbitrary
      mem_t <- choose (0, maxMem)
      mem_f <- choose (0, mem_t)
      mem_n <- choose (0, mem_t - mem_f)
      dsk_t <- choose (0, maxDsk)
      dsk_f <- choose (0, dsk_t)
      cpu_t <- choose (0, maxCpu)
      offl <- arbitrary
      let n = Node.create name (fromIntegral mem_t) mem_n mem_f
              (fromIntegral dsk_t) dsk_f (fromIntegral cpu_t) offl
          n' = Node.buildPeers n Container.empty
      return n'

setInstanceSmallerThanNode node inst =
    inst { Instance.mem = (Node.availMem node) `div` 2
         , Instance.dsk = (Node.availDisk node) `div` 2
         , Instance.vcpus = (Node.availCpu node) `div` 2
         }

-- | Make sure add is idempotent
prop_PeerMap_addIdempotent pmap key em =
    fn puniq == fn (fn puniq)
    where _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key, em::PeerMap.Elem)
          fn = PeerMap.add key em
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
prop_PeerMap_addFind pmap key em =
    PeerMap.find key (PeerMap.add key em puniq) == em
    where _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key, em::PeerMap.Elem)
          puniq = PeerMap.accumArray const pmap

-- | Manual check that maxElem returns the maximum indeed, or 0 for null
prop_PeerMap_maxElem pmap =
    PeerMap.maxElem puniq == if null puniq then 0
                             else (maximum . snd . unzip) puniq
    where _types = pmap::PeerMap.PeerMap
          puniq = PeerMap.accumArray const pmap

testPeerMap =
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

testContainer =
    [ run prop_Container_addTwo ]

-- Simple instance tests, we only have setter/getters

prop_Instance_setIdx inst idx =
    Instance.idx (Instance.setIdx inst idx) == idx
    where _types = (inst::Instance.Instance, idx::Types.Idx)

prop_Instance_setName inst name =
    Instance.name (Instance.setName inst name) == name
    where _types = (inst::Instance.Instance, name::String)

prop_Instance_setPri inst pdx =
    Instance.pNode (Instance.setPri inst pdx) == pdx
    where _types = (inst::Instance.Instance, pdx::Types.Ndx)

prop_Instance_setSec inst sdx =
    Instance.sNode (Instance.setSec inst sdx) == sdx
    where _types = (inst::Instance.Instance, sdx::Types.Ndx)

prop_Instance_setBoth inst pdx sdx =
    Instance.pNode si == pdx && Instance.sNode si == sdx
    where _types = (inst::Instance.Instance, pdx::Types.Ndx, sdx::Types.Ndx)
          si = Instance.setBoth inst pdx sdx

prop_Instance_runStatus_True inst =
    let run_st = Instance.running inst
        run_tx = Instance.runSt inst
    in
      run_tx `elem` Instance.runningStates ==> run_st

prop_Instance_runStatus_False inst =
    let run_st = Instance.running inst
        run_tx = Instance.runSt inst
    in
      run_tx `notElem` Instance.runningStates ==> not run_st

prop_Instance_shrinkMG inst =
    Instance.mem inst >= 2 * Types.unitMem ==>
        case Instance.shrinkByType inst Types.FailMem of
          Types.Ok inst' ->
              Instance.mem inst' == Instance.mem inst - Types.unitMem
          _ -> False
    where _types = (inst::Instance.Instance)

prop_Instance_shrinkMF inst =
    Instance.mem inst < 2 * Types.unitMem ==>
        not . isOk $ Instance.shrinkByType inst Types.FailMem
    where _types = (inst::Instance.Instance)

prop_Instance_shrinkCG inst =
    Instance.vcpus inst >= 2 * Types.unitCpu ==>
        case Instance.shrinkByType inst Types.FailCPU of
          Types.Ok inst' ->
              Instance.vcpus inst' == Instance.vcpus inst - Types.unitCpu
          _ -> False
    where _types = (inst::Instance.Instance)

prop_Instance_shrinkCF inst =
    Instance.vcpus inst < 2 * Types.unitCpu ==>
        not . isOk $ Instance.shrinkByType inst Types.FailCPU
    where _types = (inst::Instance.Instance)

prop_Instance_shrinkDG inst =
    Instance.dsk inst >= 2 * Types.unitDsk ==>
        case Instance.shrinkByType inst Types.FailDisk of
          Types.Ok inst' ->
              Instance.dsk inst' == Instance.dsk inst - Types.unitDsk
          _ -> False
    where _types = (inst::Instance.Instance)

prop_Instance_shrinkDF inst =
    Instance.dsk inst < 2 * Types.unitDsk ==>
        not . isOk $ Instance.shrinkByType inst Types.FailDisk
    where _types = (inst::Instance.Instance)

prop_Instance_setMovable inst m =
    Instance.movable inst' == m
    where _types = (inst::Instance.Instance, m::Bool)
          inst' = Instance.setMovable inst m

testInstance =
    [ run prop_Instance_setIdx
    , run prop_Instance_setName
    , run prop_Instance_setPri
    , run prop_Instance_setSec
    , run prop_Instance_setBoth
    , run prop_Instance_runStatus_True
    , run prop_Instance_runStatus_False
    , run prop_Instance_shrinkMG
    , run prop_Instance_shrinkMF
    , run prop_Instance_shrinkCG
    , run prop_Instance_shrinkCF
    , run prop_Instance_shrinkDG
    , run prop_Instance_shrinkDF
    , run prop_Instance_setMovable
    ]

-- Instance text loader tests

prop_Text_Load_Instance name mem dsk vcpus status pnode snode pdx sdx =
    let vcpus_s = show vcpus
        dsk_s = show dsk
        mem_s = show mem
        rsnode = snode ++ "a" -- non-empty secondary node
        rsdx = if pdx == sdx
               then sdx + 1
               else sdx
        ndx = [(pnode, pdx), (rsnode, rsdx)]
        tags = ""
        inst = Text.loadInst ndx
               [name, mem_s, dsk_s, vcpus_s, status, pnode, rsnode, tags]::
               Maybe (String, Instance.Instance)
        _types = ( name::String, mem::Int, dsk::Int
                 , vcpus::Int, status::String
                 , pnode::String, snode::String
                 , pdx::Types.Ndx, sdx::Types.Ndx)
    in
      case inst of
        Nothing -> False
        Just (_, i) ->
            (Instance.name i == name &&
             Instance.vcpus i == vcpus &&
             Instance.mem i == mem &&
             Instance.pNode i == pdx &&
             Instance.sNode i == rsdx)

testText =
    [ run prop_Text_Load_Instance
    ]

-- Node tests

-- | Check that an instance add with too high memory or disk will be rejected
prop_Node_addPriFM node inst = Instance.mem inst >= Node.fMem node &&
                               not (Node.failN1 node)
                               ==>
                               case Node.addPri node inst'' of
                                 Types.OpFail Types.FailMem -> True
                                 _ -> False
    where _types = (node::Node.Node, inst::Instance.Instance)
          inst' = setInstanceSmallerThanNode node inst
          inst'' = inst' { Instance.mem = Instance.mem inst }

prop_Node_addPriFD node inst = Instance.dsk inst >= Node.fDsk node &&
                               not (Node.failN1 node)
                               ==>
                               case Node.addPri node inst'' of
                                 Types.OpFail Types.FailDisk -> True
                                 _ -> False
    where _types = (node::Node.Node, inst::Instance.Instance)
          inst' = setInstanceSmallerThanNode node inst
          inst'' = inst' { Instance.dsk = Instance.dsk inst }

prop_Node_addPriFC node inst = Instance.vcpus inst > Node.availCpu node &&
                               not (Node.failN1 node)
                               ==>
                               case Node.addPri node inst'' of
                                 Types.OpFail Types.FailCPU -> True
                                 _ -> False
    where _types = (node::Node.Node, inst::Instance.Instance)
          inst' = setInstanceSmallerThanNode node inst
          inst'' = inst' { Instance.vcpus = Instance.vcpus inst }

-- | Check that an instance add with too high memory or disk will be rejected
prop_Node_addSec node inst pdx =
    (Instance.mem inst >= (Node.fMem node - Node.rMem node) ||
     Instance.dsk inst >= Node.fDsk node) &&
    not (Node.failN1 node)
    ==> isFailure (Node.addSec node inst pdx)
        where _types = (node::Node.Node, inst::Instance.Instance, pdx::Int)

newtype SmallRatio = SmallRatio Double deriving Show
instance Arbitrary SmallRatio where
    arbitrary = do
      v <- choose (0, 1)
      return $ SmallRatio v

-- | Check mdsk setting
prop_Node_setMdsk node mx =
    Node.loDsk node' >= 0 &&
    fromIntegral (Node.loDsk node') <= Node.tDsk node &&
    Node.availDisk node' >= 0 &&
    Node.availDisk node' <= Node.fDsk node' &&
    fromIntegral (Node.availDisk node') <= Node.tDsk node'
    where _types = (node::Node.Node, mx::SmallRatio)
          node' = Node.setMdsk node mx'
          SmallRatio mx' = mx

-- Check tag maps
prop_Node_tagMaps_idempotent tags =
    Node.delTags (Node.addTags m tags) tags == m
    where _types = (tags::[String])
          m = Data.Map.empty

prop_Node_tagMaps_reject tags =
    not (null tags) ==>
    any (\t -> Node.rejectAddTags m [t]) tags
    where _types = (tags::[String])
          m = Node.addTags (Data.Map.empty) tags

testNode =
    [ run prop_Node_addPriFM
    , run prop_Node_addPriFD
    , run prop_Node_addPriFC
    , run prop_Node_addSec
    , run prop_Node_setMdsk
    , run prop_Node_tagMaps_idempotent
    , run prop_Node_tagMaps_reject
    ]


-- Cluster tests

-- | Check that the cluster score is close to zero for a homogeneous cluster
prop_Score_Zero node count =
    (not (Node.offline node) && not (Node.failN1 node) && (count > 0) &&
     (Node.tDsk node > 0) && (Node.tMem node > 0)) ==>
    let fn = Node.buildPeers node Container.empty
        nlst = zip [1..] $ replicate count fn::[(Types.Ndx, Node.Node)]
        nl = Container.fromAssocList nlst
        score = Cluster.compCV nl
    -- we can't say == 0 here as the floating point errors accumulate;
    -- this should be much lower than the default score in CLI.hs
    in score <= 1e-15

-- | Check that cluster stats are sane
prop_CStats_sane node count =
    (not (Node.offline node) && not (Node.failN1 node) && (count > 0) &&
     (Node.tDsk node > 0) && (Node.tMem node > 0)) ==>
    let fn = Node.buildPeers node Container.empty
        nlst = zip [1..] $ replicate count fn::[(Types.Ndx, Node.Node)]
        nl = Container.fromAssocList nlst
        cstats = Cluster.totalResources nl
    in Cluster.csAdsk cstats >= 0 &&
       Cluster.csAdsk cstats <= Cluster.csFdsk cstats

testCluster =
    [ run prop_Score_Zero
    , run prop_CStats_sane
    ]

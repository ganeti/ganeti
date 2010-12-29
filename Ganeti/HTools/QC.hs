{-| Unittests for ganeti-htools

-}

{-

Copyright (C) 2009, 2010 Google Inc.

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
    ( testUtils
    , testPeerMap
    , testContainer
    , testInstance
    , testNode
    , testText
    , testOpCodes
    , testJobs
    , testCluster
    , testLoader
    ) where

import Test.QuickCheck
import Test.QuickCheck.Batch
import Data.List (findIndex, intercalate, nub)
import Data.Maybe
import Control.Monad
import qualified Text.JSON as J
import qualified Data.Map
import qualified Data.IntMap as IntMap
import qualified Ganeti.OpCodes as OpCodes
import qualified Ganeti.Jobs as Jobs
import qualified Ganeti.Luxi
import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.ExtLoader
import qualified Ganeti.HTools.IAlloc as IAlloc
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Luxi
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.PeerMap as PeerMap
import qualified Ganeti.HTools.Rapi
import qualified Ganeti.HTools.Simu
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Utils as Utils
import qualified Ganeti.HTools.Version

-- * Constants

-- | Maximum memory (1TiB, somewhat random value)
maxMem :: Int
maxMem = 1024 * 1024

-- | Maximum disk (8TiB, somewhat random value)
maxDsk :: Int
maxDsk = 1024 * 1024 * 8

-- | Max CPUs (1024, somewhat random value)
maxCpu :: Int
maxCpu = 1024

defGroup :: Group.Group
defGroup = flip Group.setIdx 0 $
               Group.create "default" Utils.defaultGroupID
                    Types.AllocPreferred

defGroupList :: Group.List
defGroupList = Container.fromAssocList [(Group.idx defGroup, defGroup)]

defGroupAssoc :: Data.Map.Map String Types.Gdx
defGroupAssoc = Data.Map.singleton (Group.uuid defGroup) (Group.idx defGroup)

-- * Helper functions

-- | Simple checker for whether OpResult is fail or pass
isFailure :: Types.OpResult a -> Bool
isFailure (Types.OpFail _) = True
isFailure _ = False

-- | Update an instance to be smaller than a node
setInstanceSmallerThanNode node inst =
    inst { Instance.mem = Node.availMem node `div` 2
         , Instance.dsk = Node.availDisk node `div` 2
         , Instance.vcpus = Node.availCpu node `div` 2
         }

-- | Create an instance given its spec
createInstance mem dsk vcpus =
    Instance.create "inst-unnamed" mem dsk vcpus "running" [] (-1) (-1)

-- | Create a small cluster by repeating a node spec
makeSmallCluster :: Node.Node -> Int -> Node.List
makeSmallCluster node count =
    let fn = Node.buildPeers node Container.empty
        namelst = map (\n -> (Node.name n, n)) (replicate count fn)
        (_, nlst) = Loader.assignIndices namelst
    in nlst

-- | Checks if a node is "big" enough
isNodeBig :: Node.Node -> Int -> Bool
isNodeBig node size = Node.availDisk node > size * Types.unitDsk
                      && Node.availMem node > size * Types.unitMem
                      && Node.availCpu node > size * Types.unitCpu

canBalance :: Cluster.Table -> Bool -> Bool -> Bool
canBalance tbl dm evac = isJust $ Cluster.tryBalance tbl dm evac 0 0

-- | Assigns a new fresh instance to a cluster; this is not
-- allocation, so no resource checks are done
assignInstance :: Node.List -> Instance.List -> Instance.Instance ->
                  Types.Idx -> Types.Idx ->
                  (Node.List, Instance.List)
assignInstance nl il inst pdx sdx =
  let pnode = Container.find pdx nl
      snode = Container.find sdx nl
      maxiidx = if Container.null il
                then 0
                else fst (Container.findMax il) + 1
      inst' = inst { Instance.idx = maxiidx,
                     Instance.pNode = pdx, Instance.sNode = sdx }
      pnode' = Node.setPri pnode inst'
      snode' = Node.setSec snode inst'
      nl' = Container.addTwo pdx pnode' sdx snode' nl
      il' = Container.add maxiidx inst' il
  in (nl', il')

-- * Arbitrary instances

-- copied from the introduction to quickcheck
instance Arbitrary Char where
    arbitrary = choose ('\32', '\128')

newtype DNSChar = DNSChar { dnsGetChar::Char }
instance Arbitrary DNSChar where
    arbitrary = do
      x <- elements (['a'..'z'] ++ ['0'..'9'] ++ "_-")
      return (DNSChar x)

getName :: Gen String
getName = do
  n <- choose (1, 64)
  dn <- vector n::Gen [DNSChar]
  return (map dnsGetChar dn)


getFQDN :: Gen String
getFQDN = do
  felem <- getName
  ncomps <- choose (1, 4)
  frest <- vector ncomps::Gen [[DNSChar]]
  let frest' = map (map dnsGetChar) frest
  return (felem ++ "." ++ intercalate "." frest')

-- let's generate a random instance
instance Arbitrary Instance.Instance where
    arbitrary = do
      name <- getFQDN
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
      name <- getFQDN
      mem_t <- choose (0, maxMem)
      mem_f <- choose (0, mem_t)
      mem_n <- choose (0, mem_t - mem_f)
      dsk_t <- choose (0, maxDsk)
      dsk_f <- choose (0, dsk_t)
      cpu_t <- choose (0, maxCpu)
      offl <- arbitrary
      let n = Node.create name (fromIntegral mem_t) mem_n mem_f
              (fromIntegral dsk_t) dsk_f (fromIntegral cpu_t) offl
              0
          n' = Node.buildPeers n Container.empty
      return n'

-- replace disks
instance Arbitrary OpCodes.ReplaceDisksMode where
  arbitrary = elements [ OpCodes.ReplaceOnPrimary
                       , OpCodes.ReplaceOnSecondary
                       , OpCodes.ReplaceNewSecondary
                       , OpCodes.ReplaceAuto
                       ]

instance Arbitrary OpCodes.OpCode where
  arbitrary = do
    op_id <- elements [ "OP_TEST_DELAY"
                      , "OP_INSTANCE_REPLACE_DISKS"
                      , "OP_INSTANCE_FAILOVER"
                      , "OP_INSTANCE_MIGRATE"
                      ]
    (case op_id of
        "OP_TEST_DELAY" ->
          liftM3 OpCodes.OpTestDelay arbitrary arbitrary arbitrary
        "OP_INSTANCE_REPLACE_DISKS" ->
          liftM5 OpCodes.OpReplaceDisks arbitrary arbitrary
          arbitrary arbitrary arbitrary
        "OP_INSTANCE_FAILOVER" ->
          liftM2 OpCodes.OpFailoverInstance arbitrary arbitrary
        "OP_INSTANCE_MIGRATE" ->
          liftM3 OpCodes.OpMigrateInstance arbitrary arbitrary arbitrary
        _ -> fail "Wrong opcode")

instance Arbitrary Jobs.OpStatus where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Jobs.JobStatus where
  arbitrary = elements [minBound..maxBound]

-- * Actual tests

-- If the list is not just an empty element, and if the elements do
-- not contain commas, then join+split should be idepotent
prop_Utils_commaJoinSplit lst = lst /= [""] &&
                                all (not . elem ',') lst ==>
                                Utils.sepSplit ',' (Utils.commaJoin lst) == lst
-- Split and join should always be idempotent
prop_Utils_commaSplitJoin s = Utils.commaJoin (Utils.sepSplit ',' s) == s

testUtils =
  [ run prop_Utils_commaJoinSplit
  , run prop_Utils_commaSplitJoin
  ]

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

prop_Container_nameOf node =
  let nl = makeSmallCluster node 1
      fnode = head (Container.elems nl)
  in Container.nameOf nl (Node.idx fnode) == Node.name fnode

-- We test that in a cluster, given a random node, we can find it by
-- its name and alias, as long as all names and aliases are unique,
-- and that we fail to find a non-existing name
prop_Container_findByName node othername =
  forAll (choose (1, 20)) $ \ cnt ->
  forAll (choose (0, cnt - 1)) $ \ fidx ->
  forAll (vector cnt) $ \ names ->
  (length . nub) (map fst names ++ map snd names) ==
  length names * 2 &&
  not (othername `elem` (map fst names ++ map snd names)) ==>
  let nl = makeSmallCluster node cnt
      nodes = Container.elems nl
      nodes' = map (\((name, alias), nn) -> (Node.idx nn,
                                             nn { Node.name = name,
                                                  Node.alias = alias }))
               $ zip names nodes
      nl' = Container.fromAssocList nodes'
      target = snd (nodes' !! fidx)
  in Container.findByName nl' (Node.name target) == Just target &&
     Container.findByName nl' (Node.alias target) == Just target &&
     Container.findByName nl' othername == Nothing

testContainer =
    [ run prop_Container_addTwo
    , run prop_Container_nameOf
    , run prop_Container_findByName
    ]

-- Simple instance tests, we only have setter/getters

prop_Instance_creat inst =
    Instance.name inst == Instance.alias inst

prop_Instance_setIdx inst idx =
    Instance.idx (Instance.setIdx inst idx) == idx
    where _types = (inst::Instance.Instance, idx::Types.Idx)

prop_Instance_setName inst name =
    Instance.name newinst == name &&
    Instance.alias newinst == name
    where _types = (inst::Instance.Instance, name::String)
          newinst = Instance.setName inst name

prop_Instance_setAlias inst name =
    Instance.name newinst == Instance.name inst &&
    Instance.alias newinst == name
    where _types = (inst::Instance.Instance, name::String)
          newinst = Instance.setAlias inst name

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

prop_Instance_shrinkMF inst =
    Instance.mem inst < 2 * Types.unitMem ==>
        Types.isBad $ Instance.shrinkByType inst Types.FailMem

prop_Instance_shrinkCG inst =
    Instance.vcpus inst >= 2 * Types.unitCpu ==>
        case Instance.shrinkByType inst Types.FailCPU of
          Types.Ok inst' ->
              Instance.vcpus inst' == Instance.vcpus inst - Types.unitCpu
          _ -> False

prop_Instance_shrinkCF inst =
    Instance.vcpus inst < 2 * Types.unitCpu ==>
        Types.isBad $ Instance.shrinkByType inst Types.FailCPU

prop_Instance_shrinkDG inst =
    Instance.dsk inst >= 2 * Types.unitDsk ==>
        case Instance.shrinkByType inst Types.FailDisk of
          Types.Ok inst' ->
              Instance.dsk inst' == Instance.dsk inst - Types.unitDsk
          _ -> False

prop_Instance_shrinkDF inst =
    Instance.dsk inst < 2 * Types.unitDsk ==>
        Types.isBad $ Instance.shrinkByType inst Types.FailDisk

prop_Instance_setMovable inst m =
    Instance.movable inst' == m
    where inst' = Instance.setMovable inst m

testInstance =
    [ run prop_Instance_creat
    , run prop_Instance_setIdx
    , run prop_Instance_setName
    , run prop_Instance_setAlias
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
    not (null pnode) && pdx >= 0 && sdx >= 0 ==>
    let vcpus_s = show vcpus
        dsk_s = show dsk
        mem_s = show mem
        rsdx = if pdx == sdx
               then sdx + 1
               else sdx
        ndx = if null snode
              then [(pnode, pdx)]
              else [(pnode, pdx), (snode, rsdx)]
        nl = Data.Map.fromList ndx
        tags = ""
        inst = Text.loadInst nl
               [name, mem_s, dsk_s, vcpus_s, status, pnode, snode, tags]::
               Maybe (String, Instance.Instance)
        fail1 = Text.loadInst nl
               [name, mem_s, dsk_s, vcpus_s, status, pnode, pnode, tags]::
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
             Instance.sNode i == (if null snode
                                  then Node.noSecondary
                                  else rsdx) &&
             isNothing fail1)

prop_Text_Load_InstanceFail ktn fields =
    length fields /= 8 ==> isNothing $ Text.loadInst nl fields
    where nl = Data.Map.fromList ktn

prop_Text_Load_Node name tm nm fm td fd tc fo =
    let conv v = if v < 0
                    then "?"
                    else show v
        tm_s = conv tm
        nm_s = conv nm
        fm_s = conv fm
        td_s = conv td
        fd_s = conv fd
        tc_s = conv tc
        fo_s = if fo
               then "Y"
               else "N"
        any_broken = any (< 0) [tm, nm, fm, td, fd, tc]
        gid = Group.uuid defGroup
    in case Text.loadNode defGroupAssoc
           [name, tm_s, nm_s, fm_s, td_s, fd_s, tc_s, fo_s, gid] of
         Nothing -> False
         Just (name', node) ->
             if fo || any_broken
             then Node.offline node
             else Node.name node == name' && name' == name &&
                  Node.alias node == name &&
                  Node.tMem node == fromIntegral tm &&
                  Node.nMem node == nm &&
                  Node.fMem node == fm &&
                  Node.tDsk node == fromIntegral td &&
                  Node.fDsk node == fd &&
                  Node.tCpu node == fromIntegral tc

prop_Text_Load_NodeFail fields =
    length fields /= 8 ==> isNothing $ Text.loadNode Data.Map.empty fields

prop_Text_NodeLSIdempotent node =
    (Text.loadNode defGroupAssoc.
         Utils.sepSplit '|' . Text.serializeNode defGroupList) n ==
    Just (Node.name n, n)
    -- override failN1 to what loadNode returns by default
    where n = node { Node.failN1 = True, Node.offline = False }

testText =
    [ run prop_Text_Load_Instance
    , run prop_Text_Load_InstanceFail
    , run prop_Text_Load_Node
    , run prop_Text_Load_NodeFail
    , run prop_Text_NodeLSIdempotent
    ]

-- Node tests

prop_Node_setAlias node name =
    Node.name newnode == Node.name node &&
    Node.alias newnode == name
    where _types = (node::Node.Node, name::String)
          newnode = Node.setAlias node name

prop_Node_setOffline node status =
    Node.offline newnode == status
    where newnode = Node.setOffline node status

prop_Node_setXmem node xm =
    Node.xMem newnode == xm
    where newnode = Node.setXmem node xm

prop_Node_setMcpu node mc =
    Node.mCpu newnode == mc
    where newnode = Node.setMcpu node mc

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
    fromIntegral (Node.availDisk node') <= Node.tDsk node' &&
    Node.mDsk node' == mx'
    where _types = (node::Node.Node, mx::SmallRatio)
          node' = Node.setMdsk node mx'
          SmallRatio mx' = mx

-- Check tag maps
prop_Node_tagMaps_idempotent tags =
    Node.delTags (Node.addTags m tags) tags == m
    where m = Data.Map.empty

prop_Node_tagMaps_reject tags =
    not (null tags) ==>
    any (\t -> Node.rejectAddTags m [t]) tags
    where m = Node.addTags Data.Map.empty tags

prop_Node_showField node =
  forAll (elements Node.defaultFields) $ \ field ->
  fst (Node.showHeader field) /= Types.unknownField &&
  Node.showField node field /= Types.unknownField


prop_Node_computeGroups nodes =
  let ng = Node.computeGroups nodes
      onlyuuid = map fst ng
  in length nodes == sum (map (length . snd) ng) &&
     all (\(guuid, ns) -> all ((== guuid) . Node.group) ns) ng &&
     length (nub onlyuuid) == length onlyuuid &&
     if null nodes then True else not (null ng)

testNode =
    [ run prop_Node_setAlias
    , run prop_Node_setOffline
    , run prop_Node_setMcpu
    , run prop_Node_setXmem
    , run prop_Node_addPriFM
    , run prop_Node_addPriFD
    , run prop_Node_addPriFC
    , run prop_Node_addSec
    , run prop_Node_setMdsk
    , run prop_Node_tagMaps_idempotent
    , run prop_Node_tagMaps_reject
    , run prop_Node_showField
    , run prop_Node_computeGroups
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
     (Node.availDisk node > 0) && (Node.availMem node > 0)) ==>
    let fn = Node.buildPeers node Container.empty
        nlst = zip [1..] $ replicate count fn::[(Types.Ndx, Node.Node)]
        nl = Container.fromAssocList nlst
        cstats = Cluster.totalResources nl
    in Cluster.csAdsk cstats >= 0 &&
       Cluster.csAdsk cstats <= Cluster.csFdsk cstats

-- | Check that one instance is allocated correctly, without
-- rebalances needed
prop_ClusterAlloc_sane node inst =
    forAll (choose (5, 20)) $ \count ->
    not (Node.offline node)
            && not (Node.failN1 node)
            && Node.availDisk node > 0
            && Node.availMem node > 0
            ==>
    let nl = makeSmallCluster node count
        il = Container.empty
        rqnodes = 2
        inst' = setInstanceSmallerThanNode node inst
    in case Cluster.tryAlloc nl il inst' rqnodes of
         Types.Bad _ -> False
         Types.Ok as ->
             case Cluster.asSolutions as of
               [] -> False
               (xnl, xi, _, cv):[] ->
                   let il' = Container.add (Instance.idx xi) xi il
                       tbl = Cluster.Table xnl il' cv []
                   in not (canBalance tbl True False)
               _ -> False

-- | Checks that on a 2-5 node cluster, we can allocate a random
-- instance spec via tiered allocation (whatever the original instance
-- spec), on either one or two nodes
prop_ClusterCanTieredAlloc node inst =
    forAll (choose (2, 5)) $ \count ->
    forAll (choose (1, 2)) $ \rqnodes ->
    not (Node.offline node)
            && not (Node.failN1 node)
            && isNodeBig node 4
            ==>
    let nl = makeSmallCluster node count
        il = Container.empty
    in case Cluster.tieredAlloc nl il inst rqnodes [] []of
         Types.Bad _ -> False
         Types.Ok (_, _, il', ixes, cstats) -> not (null ixes) &&
                                      IntMap.size il' == length ixes &&
                                      length ixes == length cstats

-- | Checks that on a 4-8 node cluster, once we allocate an instance,
-- we can also evacuate it
prop_ClusterAllocEvac node inst =
    forAll (choose (4, 8)) $ \count ->
    not (Node.offline node)
            && not (Node.failN1 node)
            && isNodeBig node 4
            ==>
    let nl = makeSmallCluster node count
        il = Container.empty
        rqnodes = 2
        inst' = setInstanceSmallerThanNode node inst
    in case Cluster.tryAlloc nl il inst' rqnodes of
         Types.Bad _ -> False
         Types.Ok as ->
             case Cluster.asSolutions as of
               [] -> False
               (xnl, xi, _, _):[] ->
                   let sdx = Instance.sNode xi
                       il' = Container.add (Instance.idx xi) xi il
                   in case Cluster.tryEvac xnl il' [sdx] of
                        Just _ -> True
                        _ -> False
               _ -> False

-- | Check that allocating multiple instances on a cluster, then
-- adding an empty node, results in a valid rebalance
prop_ClusterAllocBalance node =
    forAll (choose (3, 5)) $ \count ->
    not (Node.offline node)
            && not (Node.failN1 node)
            && isNodeBig node 4
            && not (isNodeBig node 8)
            ==>
    let nl = makeSmallCluster node count
        (hnode, nl') = IntMap.deleteFindMax nl
        il = Container.empty
        rqnodes = 2
        i_templ = createInstance Types.unitMem Types.unitDsk Types.unitCpu
    in case Cluster.iterateAlloc nl' il i_templ rqnodes [] [] of
         Types.Bad _ -> False
         Types.Ok (_, xnl, il', _, _) ->
                   let ynl = Container.add (Node.idx hnode) hnode xnl
                       cv = Cluster.compCV ynl
                       tbl = Cluster.Table ynl il' cv []
                   in canBalance tbl True False

-- | Checks consistency
prop_ClusterCheckConsistency node inst =
  let nl = makeSmallCluster node 3
      [node1, node2, node3] = Container.elems nl
      node3' = node3 { Node.group = 1 }
      nl' = Container.add (Node.idx node3') node3' nl
      inst1 = Instance.setBoth inst (Node.idx node1) (Node.idx node2)
      inst2 = Instance.setBoth inst (Node.idx node1) Node.noSecondary
      inst3 = Instance.setBoth inst (Node.idx node1) (Node.idx node3)
      ccheck = Cluster.findSplitInstances nl' . Container.fromAssocList
  in null (ccheck [(0, inst1)]) &&
     null (ccheck [(0, inst2)]) &&
     (not . null $ ccheck [(0, inst3)])

-- For now, we only test that we don't lose instances during the split
prop_ClusterSplitCluster node inst =
  forAll (choose (0, 100)) $ \icnt ->
  let nl = makeSmallCluster node 2
      (nl', il') = foldl (\(ns, is) _ -> assignInstance ns is inst 0 1)
                   (nl, Container.empty) [1..icnt]
      gni = Cluster.splitCluster nl' il'
  in sum (map (Container.size . snd . snd) gni) == icnt &&
     all (\(guuid, (nl'', _)) -> all ((== guuid) . Node.group)
                                 (Container.elems nl'')) gni

testCluster =
    [ run prop_Score_Zero
    , run prop_CStats_sane
    , run prop_ClusterAlloc_sane
    , run prop_ClusterCanTieredAlloc
    , run prop_ClusterAllocEvac
    , run prop_ClusterAllocBalance
    , run prop_ClusterCheckConsistency
    , run prop_ClusterSplitCluster
    ]

-- | Check that opcode serialization is idempotent

prop_OpCodes_serialization op =
  case J.readJSON (J.showJSON op) of
    J.Error _ -> False
    J.Ok op' -> op == op'
  where _types = op::OpCodes.OpCode

testOpCodes =
  [ run prop_OpCodes_serialization
  ]

-- | Check that (queued) job\/opcode status serialization is idempotent
prop_OpStatus_serialization os =
  case J.readJSON (J.showJSON os) of
    J.Error _ -> False
    J.Ok os' -> os == os'
  where _types = os::Jobs.OpStatus

prop_JobStatus_serialization js =
  case J.readJSON (J.showJSON js) of
    J.Error _ -> False
    J.Ok js' -> js == js'
  where _types = js::Jobs.JobStatus

testJobs =
  [ run prop_OpStatus_serialization
  , run prop_JobStatus_serialization
  ]

-- | Loader tests

prop_Loader_lookupNode ktn inst node =
  Loader.lookupNode nl inst node == Data.Map.lookup node nl
  where nl = Data.Map.fromList ktn

prop_Loader_lookupInstance kti inst =
  Loader.lookupInstance il inst == Data.Map.lookup inst il
  where il = Data.Map.fromList kti

prop_Loader_assignIndices nodes =
  Data.Map.size nassoc == length nodes &&
  Container.size kt == length nodes &&
  (if not (null nodes)
   then maximum (IntMap.keys kt) == length nodes - 1
   else True)
  where (nassoc, kt) = Loader.assignIndices (map (\n -> (Node.name n, n)) nodes)


-- | Checks that the number of primary instances recorded on the nodes
-- is zero
prop_Loader_mergeData ns =
  let na = Container.fromAssocList $ map (\n -> (Node.idx n, n)) ns
  in case Loader.mergeData [] [] []
         (Loader.emptyCluster {Loader.cdNodes = na}) of
    Types.Bad _ -> False
    Types.Ok (Loader.ClusterData _ nl il _) ->
      let nodes = Container.elems nl
          instances = Container.elems il
      in (sum . map (length . Node.pList)) nodes == 0 &&
         null instances

testLoader =
  [ run prop_Loader_lookupNode
  , run prop_Loader_lookupInstance
  , run prop_Loader_assignIndices
  , run prop_Loader_mergeData
  ]

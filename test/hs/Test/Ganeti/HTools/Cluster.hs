{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

module Test.Ganeti.HTools.Cluster (testHTools_Cluster) where

import Test.QuickCheck hiding (Result)

import Control.Monad (liftM)
import qualified Data.IntMap as IntMap
import Data.Maybe

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools
import Test.Ganeti.HTools.Instance ( genInstanceSmallerThanNode
                                   , genInstanceMaybeBiggerThanNode )
import Test.Ganeti.HTools.Node (genOnlineNode, genNode)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.AlgorithmParams as Alg
import qualified Ganeti.HTools.Backend.IAlloc as IAlloc
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.AllocationSolution as AllocSol
import qualified Ganeti.HTools.Cluster.Evacuate as Evacuate
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import qualified Ganeti.HTools.Cluster.Utils as ClusterUtils
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.Types as Types (EvacMode(..))

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Helpers

-- | Make a small cluster, both nodes and instances.
makeSmallEmptyCluster :: Node.Node -> Int -> Instance.Instance
                      -> (Node.List, Instance.List, Instance.Instance)
makeSmallEmptyCluster node count inst =
  (makeSmallCluster node count, Container.empty,
   setInstanceSmallerThanNode node inst)

-- | Checks if a node is "big" enough.
isNodeBig :: Int -> Node.Node -> Bool
isNodeBig size node = Node.availDisk node > size * Types.unitDsk
                      && Node.availMem node > size * Types.unitMem
                      && Node.availCpu node > size * Types.unitCpu

canBalance :: Cluster.Table -> Bool -> Bool -> Bool -> Bool
canBalance tbl@(Cluster.Table _ _ ini_cv _)  dm im evac =
  maybe False (\(Cluster.Table _ _ fin_cv _) -> ini_cv - fin_cv > 1e-12)
  $ Cluster.tryBalance (Alg.defaultOptions { Alg.algMinGain = 0.0
                                           , Alg.algMinGainLimit = 0.0
                                           , Alg.algDiskMoves = dm
                                           , Alg.algInstanceMoves = im
                                           , Alg.algEvacMode = evac}) tbl

-- | Assigns a new fresh instance to a cluster; this is not
-- allocation, so no resource checks are done.
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

-- | Checks if an instance is mirrored.
isMirrored :: Instance.Instance -> Bool
isMirrored = (/= Types.MirrorNone) . Instance.mirrorType

-- | Returns the possible change node types for a disk template.
evacModeOptions :: Types.MirrorType -> [Types.EvacMode]
evacModeOptions Types.MirrorNone     = []
evacModeOptions Types.MirrorInternal = [minBound..maxBound] -- DRBD can do all
evacModeOptions Types.MirrorExternal = [Types.ChangePrimary, Types.ChangeAll]

-- * Test cases

-- | Check that the cluster score is close to zero for a homogeneous
-- cluster.
prop_Score_Zero :: Node.Node -> Property
prop_Score_Zero node =
  forAll (choose (1, 1024)) $ \count ->
    (not (Node.offline node) && not (Node.failN1 node) && (count > 0) &&
     (Node.tDsk node > 0) && (Node.tMem node > 0) &&
     (Node.tSpindles node > 0) && (Node.tCpu node > 0)) ==>
  let fn = Node.buildPeers node Container.empty
      nlst = replicate count fn
      score = Metrics.compCVNodes nlst
  -- we can't say == 0 here as the floating point errors accumulate;
  -- this should be much lower than the default score in CLI.hs
  in score <= 1e-12

-- | Check that cluster stats are sane.
prop_CStats_sane :: Property
prop_CStats_sane =
  forAll (choose (1, 1024)) $ \count ->
  forAll genOnlineNode $ \node ->
  let fn = Node.buildPeers node Container.empty
      nlst = zip [1..] $ replicate count fn::[(Types.Ndx, Node.Node)]
      nl = Container.fromList nlst
      cstats = Cluster.totalResources nl
  in Cluster.csAdsk cstats >= 0 &&
     Cluster.csAdsk cstats <= Cluster.csFdsk cstats

-- | Check that one instance is allocated correctly on an empty cluster,
-- without rebalances needed.
prop_Alloc_sane :: Instance.Instance -> Property
prop_Alloc_sane inst =
  forAll (choose (5, 20)) $ \count ->
  forAll genOnlineNode $ \node ->
  let (nl, il, inst') = makeSmallEmptyCluster node count inst
      reqnodes = Instance.requiredNodes $ Instance.diskTemplate inst
      opts = Alg.defaultOptions
  in case Cluster.genAllocNodes Alg.defaultOptions
                                defGroupList nl reqnodes True >>=
     Cluster.tryAlloc opts nl il inst' of
       Bad msg -> failTest msg
       Ok as ->
         case AllocSol.asSolution as of
           Nothing -> failTest "Failed to allocate, empty solution"
           Just (xnl, xi, _, cv) ->
             let il' = Container.add (Instance.idx xi) xi il
                 tbl = Cluster.Table xnl il' cv []
             in counterexample "Cluster can be balanced after allocation"
                  (not (canBalance tbl True True False)) .&&.
                counterexample "Solution score differs from actual node list"
                  (abs (Metrics.compCV xnl - cv) < 1e-12)

-- | Checks that on a 2-5 node cluster, we can allocate a random
-- instance spec via tiered allocation (whatever the original instance
-- spec), on either one or two nodes. Furthermore, we test that
-- computed allocation statistics are correct.
prop_CanTieredAlloc :: Property
prop_CanTieredAlloc =
  forAll (choose (2, 5)) $ \count ->
  forAll (liftM (Node.setPolicy Types.defIPolicy)
            (genOnlineNode `suchThat` isNodeBig 5)) $ \node ->
  forAll (genInstanceMaybeBiggerThanNode node) $ \inst ->
  let nl = makeSmallCluster node count
      il = Container.empty
      rqnodes = Instance.requiredNodes $ Instance.diskTemplate inst
      allocnodes = Cluster.genAllocNodes Alg.defaultOptions
                                         defGroupList nl rqnodes True
      opts = Alg.defaultOptions
  in case allocnodes >>= \allocnodes' ->
    Cluster.tieredAlloc opts nl il (Just 5) inst allocnodes' [] [] of
       Bad msg -> failTest $ "Failed to tiered alloc: " ++ msg
       Ok (_, nl', il', ixes, cstats) ->
         let (ai_alloc, ai_pool, ai_unav) =
               Cluster.computeAllocationDelta
                (Cluster.totalResources nl)
                (Cluster.totalResources nl')
             all_nodes fn = sum $ map fn (Container.elems nl)
             all_res fn = sum $ map fn [ai_alloc, ai_pool, ai_unav]
         in conjoin
            [ counterexample "No instances allocated" $ not (null ixes)
            , IntMap.size il' ==? length ixes
            , length ixes     ==? length cstats
            , all_res Types.allocInfoVCpus ==? all_nodes Node.hiCpu
            , all_res Types.allocInfoNCpus ==? all_nodes Node.tCpu
            , all_res Types.allocInfoMem   ==? truncate (all_nodes Node.tMem)
            , all_res Types.allocInfoDisk  ==? truncate (all_nodes Node.tDsk)
            ]

-- | Helper function to create a cluster with the given range of nodes
-- and allocate an instance on it.
genClusterAlloc :: Int -> Node.Node -> Instance.Instance
                -> Result (Node.List, Instance.List, Instance.Instance)
genClusterAlloc count node inst =
  let nl = makeSmallCluster node count
      reqnodes = Instance.requiredNodes $ Instance.diskTemplate inst
      opts = Alg.defaultOptions
  in case Cluster.genAllocNodes Alg.defaultOptions
                                defGroupList nl reqnodes True >>=
     Cluster.tryAlloc opts nl Container.empty inst of
       Bad msg -> Bad $ "Can't allocate: " ++ msg
       Ok as ->
         case AllocSol.asSolution as of
           Nothing -> Bad "Empty solution?"
           Just (xnl, xi, _, _) ->
             let xil = Container.add (Instance.idx xi) xi Container.empty
             in Ok (xnl, xil, xi)

-- | Checks that on a 4-8 node cluster, once we allocate an instance,
-- we can also relocate it.
prop_AllocRelocate :: Property
prop_AllocRelocate =
  forAll (choose (4, 8)) $ \count ->
  forAll (genOnlineNode `suchThat` isNodeBig 4) $ \node ->
  forAll (genInstanceSmallerThanNode node `suchThat` isMirrored) $ \inst ->
  case genClusterAlloc count node inst of
    Bad msg -> failTest msg
    Ok (nl, il, inst') ->
      case IAlloc.processRelocate Alg.defaultOptions defGroupList nl il
             (Instance.idx inst) 1
             [(if Instance.diskTemplate inst' == Types.DTDrbd8
                 then Instance.sNode
                 else Instance.pNode) inst'] of
        Ok _ -> passTest
        Bad msg -> failTest $ "Failed to relocate: " ++ msg

-- | Helper property checker for the result of a nodeEvac or
-- changeGroup operation.
check_EvacMode :: Group.Group -> Instance.Instance
               -> Result (Node.List, Instance.List, Evacuate.EvacSolution)
               -> Property
check_EvacMode grp inst result =
  case result of
    Bad msg -> failTest $ "Couldn't evacuate/change group:" ++ msg
    Ok (_, _, es) ->
      let moved = Evacuate.esMoved es
          failed = Evacuate.esFailed es
          opcodes = not . null $ Evacuate.esOpCodes es
      in conjoin
           [ failmsg ("'failed' not empty: " ++ show failed) (null failed)
           , failmsg "'opcodes' is null" opcodes
           , case moved of
               [(idx', gdx, _)] ->
                 failmsg "invalid instance moved" (idx == idx') .&&.
                 failmsg "wrong target group" (gdx == Group.idx grp)
               v -> failmsg  ("invalid solution: " ++ show v) False
           ]
  where failmsg :: String -> Bool -> Property
        failmsg msg = counterexample ("Failed to evacuate: " ++ msg)
        idx = Instance.idx inst

-- | Checks that on a 4-8 node cluster, once we allocate an instance,
-- we can also node-evacuate it.
prop_AllocEvacuate :: Property
prop_AllocEvacuate =
  forAll (choose (4, 8)) $ \count ->
  forAll (genOnlineNode `suchThat` isNodeBig 4) $ \node ->
  forAll (genInstanceSmallerThanNode node `suchThat` isMirrored) $ \inst ->
  case genClusterAlloc count node inst of
    Bad msg -> failTest msg
    Ok (nl, il, inst') ->
      conjoin . map (\mode -> check_EvacMode defGroup inst' $
                              Evacuate.tryNodeEvac Alg.defaultOptions
                                defGroupList nl il mode
                                [Instance.idx inst']) .
                              evacModeOptions .
                              Instance.mirrorType $ inst'

-- | Checks that on a 4-8 node cluster with two node groups, once we
-- allocate an instance on the first node group, we can also change
-- its group.
prop_AllocChangeGroup :: Property
prop_AllocChangeGroup =
  forAll (choose (4, 8)) $ \count ->
  forAll (genOnlineNode `suchThat` isNodeBig 4) $ \node ->
  forAll (genInstanceSmallerThanNode node `suchThat` isMirrored) $ \inst ->
  case genClusterAlloc count node inst of
    Bad msg -> failTest msg
    Ok (nl, il, inst') ->
      -- we need to add a second node group and nodes to the cluster
      let nl2 = Container.elems $ makeSmallCluster node count
          grp2 = Group.setIdx defGroup (Group.idx defGroup + 1)
          maxndx = maximum . map Node.idx $ nl2
          nl3 = map (\n -> n { Node.group = Group.idx grp2
                             , Node.idx = Node.idx n + maxndx }) nl2
          nl4 = Container.fromList . map (\n -> (Node.idx n, n)) $ nl3
          gl' = Container.add (Group.idx grp2) grp2 defGroupList
          nl' = IntMap.union nl nl4
          opts = Alg.defaultOptions
      in check_EvacMode grp2 inst' $
         Cluster.tryChangeGroup opts gl' nl' il [] [Instance.idx inst']

-- | Check that allocating multiple instances on a cluster, then
-- adding an empty node, results in a valid rebalance.
prop_AllocBalance :: Property
prop_AllocBalance =
  forAll (genNode (Just 5) (Just 128)) $ \node ->
  forAll (choose (3, 5)) $ \count ->
  not (Node.offline node) && not (Node.failN1 node) ==>
  let nl = makeSmallCluster node count
      hnode = snd $ IntMap.findMax nl
      nl' = IntMap.deleteMax nl
      il = Container.empty
      allocnodes = Cluster.genAllocNodes Alg.defaultOptions
                                         defGroupList nl' 2 True
      i_templ = createInstance Types.unitMem Types.unitDsk Types.unitCpu
      opts = Alg.defaultOptions
  in case allocnodes >>= \allocnodes' ->
    Cluster.iterateAlloc opts nl' il (Just 5) i_templ allocnodes' [] [] of
       Bad msg -> failTest $ "Failed to allocate: " ++ msg
       Ok (_, _, _, [], _) -> failTest "Failed to allocate: no instances"
       Ok (_, xnl, il', _, _) ->
         let ynl = Container.add (Node.idx hnode) hnode xnl
             cv = Metrics.compCV ynl
             tbl = Cluster.Table ynl il' cv []
         in counterexample "Failed to rebalance" $
            canBalance tbl True True False

-- | Checks consistency.
prop_CheckConsistency :: Node.Node -> Instance.Instance -> Bool
prop_CheckConsistency node inst =
  let nl = makeSmallCluster node 3
      (node1, node2, node3) =
        case Container.elems nl of
          [a, b, c] -> (a, b, c)
          l -> error $ "Invalid node list out of makeSmallCluster/3: " ++
               show l
      node3' = node3 { Node.group = 1 }
      nl' = Container.add (Node.idx node3') node3' nl
      inst1 = Instance.setBoth inst (Node.idx node1) (Node.idx node2)
      inst2 = Instance.setBoth inst (Node.idx node1) Node.noSecondary
      inst3 = Instance.setBoth inst (Node.idx node1) (Node.idx node3)
      ccheck = Cluster.findSplitInstances nl' . Container.fromList
  in null (ccheck [(0, inst1)]) &&
     null (ccheck [(0, inst2)]) &&
     (not . null $ ccheck [(0, inst3)])

-- | For now, we only test that we don't lose instances during the split.
prop_SplitCluster :: Node.Node -> Instance.Instance -> Property
prop_SplitCluster node inst =
  forAll (choose (0, 100)) $ \icnt ->
  let nl = makeSmallCluster node 2
      (nl', il') = foldl (\(ns, is) _ -> assignInstance ns is inst 0 1)
                   (nl, Container.empty) [1..icnt]
      gni = ClusterUtils.splitCluster nl' il'
  in sum (map (Container.size . snd . snd) gni) == icnt &&
     all (\(guuid, (nl'', _)) -> all ((== guuid) . Node.group)
                                 (Container.elems nl'')) gni

-- | Helper function to check if we can allocate an instance on a
-- given node list. Successful allocation is denoted by 'Nothing',
-- otherwise the 'Just' value will contain the error message.
canAllocOn :: Node.List -> Int -> Instance.Instance -> Maybe String
canAllocOn nl reqnodes inst =
  case Cluster.genAllocNodes Alg.defaultOptions
                             defGroupList nl reqnodes True >>=
       Cluster.tryAlloc Alg.defaultOptions nl Container.empty inst of
       Bad msg -> Just $ "Can't allocate: " ++ msg
       Ok as ->
         case AllocSol.asSolution as of
           Nothing -> Just $ "No allocation solution; failures: " ++
                      show (AllocSol.collapseFailures $ AllocSol.asFailures as)
           Just _ -> Nothing

-- | Checks that allocation obeys minimum and maximum instance
-- policies. The unittest generates a random node, duplicates it /count/
-- times, and generates a random instance that can be allocated on
-- this mini-cluster; it then checks that after applying a policy that
-- the instance doesn't fits, the allocation fails.
prop_AllocPolicy :: Property
prop_AllocPolicy =
  forAll genOnlineNode $ \node ->
  forAll (choose (5, 20)) $ \count ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  forAll (arbitrary `suchThat`
          (isBad . flip (Instance.instMatchesPolicy inst)
           (Node.exclStorage node))) $ \ipol ->
  let rqn = Instance.requiredNodes $ Instance.diskTemplate inst
      node' = Node.setPolicy ipol node
      nl = makeSmallCluster node' count
  in counterexample "Allocation check:"
       (isNothing (canAllocOn (makeSmallCluster node count) rqn inst)) .&&.
     counterexample "Policy failure check:" (isJust $ canAllocOn nl rqn inst)

testSuite "HTools/Cluster"
            [ 'prop_Score_Zero
            , 'prop_CStats_sane
            , 'prop_Alloc_sane
            , 'prop_CanTieredAlloc
            , 'prop_AllocRelocate
            , 'prop_AllocEvacuate
            , 'prop_AllocChangeGroup
            , 'prop_AllocBalance
            , 'prop_CheckConsistency
            , 'prop_SplitCluster
            , 'prop_AllocPolicy
            ]

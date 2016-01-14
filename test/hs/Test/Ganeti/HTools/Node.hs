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

module Test.Ganeti.HTools.Node
  ( testHTools_Node
  , Node.Node(..)
  , setInstanceSmallerThanNode
  , genNode
  , genOnlineNode
  , genEmptyOnlineNode
  , genNodeList
  , genUniqueNodeList
  ) where

import Test.QuickCheck
import Test.HUnit

import Control.Monad
import qualified Data.Map as Map
import qualified Data.Graph as Graph
import Data.List

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools
import Test.Ganeti.HTools.Instance ( genInstanceSmallerThanNode
                                   , genInstanceList
                                   , genInstanceOnNodeList)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Graph as HGraph

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitrary instances

-- | Generates an arbitrary node based on sizing information.
genNode :: Maybe Int -- ^ Minimum node size in terms of units
        -> Maybe Int -- ^ Maximum node size (when Nothing, bounded
                     -- just by the max... constants)
        -> Gen Node.Node
genNode min_multiplier max_multiplier = do
  let (base_mem, base_dsk, base_cpu, base_spindles) =
        case min_multiplier of
          Just mm -> (mm * Types.unitMem,
                      mm * Types.unitDsk,
                      mm * Types.unitCpu,
                      mm)
          Nothing -> (0, 0, 0, 0)
      (top_mem, top_dsk, top_cpu, top_spindles)  =
        case max_multiplier of
          Just mm -> (mm * Types.unitMem,
                      mm * Types.unitDsk,
                      mm * Types.unitCpu,
                      mm)
          Nothing -> (maxMem, maxDsk, maxCpu, maxSpindles)
  name  <- genFQDN
  mem_t <- choose (base_mem, top_mem)
  mem_f <- choose (base_mem, mem_t)
  mem_n <- choose (0, mem_t - mem_f)
  dsk_t <- choose (base_dsk, top_dsk)
  dsk_f <- choose (base_dsk, dsk_t)
  cpu_t <- choose (base_cpu, top_cpu)
  cpu_n <- choose (base_cpu, cpu_t)
  offl  <- arbitrary
  spindles <- choose (base_spindles, top_spindles)
  let n = Node.create name (fromIntegral mem_t) mem_n mem_f
          (fromIntegral dsk_t) dsk_f (fromIntegral cpu_t) cpu_n offl spindles
          0 0 False
      n' = Node.setPolicy nullIPolicy n
  return $ Node.buildPeers n' Container.empty

-- | Helper function to generate a sane node.
genOnlineNode :: Gen Node.Node
genOnlineNode =
  arbitrary `suchThat` (\n -> not (Node.offline n) &&
                              not (Node.failN1 n) &&
                              Node.availDisk n > 2 * Types.unitDsk &&
                              Node.availMem n > 2 * Types.unitMem &&
                              Node.availCpu n > 2 &&
                              Node.tSpindles n > 2)

-- | Helper function to generate a sane empty node with consistent
-- internal data.
genEmptyOnlineNode :: Gen Node.Node
genEmptyOnlineNode =
  (do node <- arbitrary
      let fmem = truncate (Node.tMem node) - Node.nMem node
      let node' = node { Node.offline = False
                       , Node.fMem = fmem
                       , Node.fMemForth = fmem
                       , Node.pMem = fromIntegral fmem / Node.tMem node
                       , Node.pMemForth = fromIntegral fmem / Node.tMem node
                       , Node.rMem = 0
                       , Node.rMemForth = 0
                       , Node.pRem = 0
                       , Node.pRemForth = 0
                       }
      return node') `suchThat` (\ n -> not (Node.failN1 n) &&
                                       Node.availDisk n > 0 &&
                                       Node.availMem n > 0 &&
                                       Node.availCpu n > 0 &&
                                       Node.tSpindles n > 0)

-- | Generate a node with exclusive storage enabled.
genExclStorNode :: Gen Node.Node
genExclStorNode = do
  n <- genOnlineNode
  fs <- choose (Types.unitSpindle, Node.tSpindles n)
  fsForth <- choose (Types.unitSpindle, fs)
  let pd = fromIntegral fs / fromIntegral (Node.tSpindles n)::Double
  let pdForth = fromIntegral fsForth / fromIntegral (Node.tSpindles n)::Double
  return n { Node.exclStorage = True
           , Node.fSpindles = fs
           , Node.fSpindlesForth = fsForth
           , Node.pDsk = pd
           , Node.pDskForth = pdForth
           }

-- | Generate a node with exclusive storage possibly enabled.
genMaybeExclStorNode :: Gen Node.Node
genMaybeExclStorNode = oneof [genOnlineNode, genExclStorNode]

-- and a random node
instance Arbitrary Node.Node where
  arbitrary = genNode Nothing Nothing

-- | Node list generator.
-- Given a node generator, create a random length node list.  Note that "real"
-- clusters always have at least one node, so we don't generate empty node
-- lists here.
genNodeList :: Gen Node.Node -> Gen Node.List
genNodeList ngen = fmap (snd . Loader.assignIndices) names_nodes
    where names_nodes = (fmap . map) (\n -> (Node.name n, n)) nodes
          nodes = listOf1 ngen `suchThat`
                  ((\ns -> ns == nub ns) . map Node.name)

-- | Node list generator where node names are unique
genUniqueNodeList :: Gen Node.Node -> Gen (Node.List, Types.NameAssoc)
genUniqueNodeList ngen = (do
  nl <- genNodeList ngen
  let na = (fst . Loader.assignIndices) $
           map (\n -> (Node.name n, n)) (Container.elems nl)
  return (nl, na)) `suchThat`
    (\(nl, na) -> Container.size nl == Map.size na)

-- | Generate a node list, an instance list, and a node graph.
-- We choose instances with nodes contained in the node list.
genNodeGraph :: Gen (Maybe Graph.Graph, Node.List, Instance.List)
genNodeGraph = do
  nl <- genNodeList genOnlineNode `suchThat` ((2<=).Container.size)
  il <- genInstanceList (genInstanceOnNodeList nl)
  return (Node.mkNodeGraph nl il, nl, il)

-- * Test cases

prop_setAlias :: Node.Node -> String -> Bool
prop_setAlias node name =
  Node.name newnode == Node.name node &&
  Node.alias newnode == name
    where newnode = Node.setAlias node name

prop_setOffline :: Node.Node -> Bool -> Property
prop_setOffline node status =
  Node.offline newnode ==? status
    where newnode = Node.setOffline node status

prop_setXmem :: Node.Node -> Int -> Property
prop_setXmem node xm =
  Node.xMem newnode ==? xm
    where newnode = Node.setXmem node xm

prop_setMcpu :: Node.Node -> Double -> Property
prop_setMcpu node mc =
  Types.iPolicyVcpuRatio (Node.iPolicy newnode) ==? mc
    where newnode = Node.setMcpu node mc

-- Check if adding an instance that consumes exactly all reserved
-- memory does not raise an N+1 error
prop_addPri_NoN1Fail :: Property
prop_addPri_NoN1Fail =
  forAll genMaybeExclStorNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let inst' = inst { Instance.mem = Node.fMem node - Node.rMem node }
  in (Node.addPri node inst' /=? Bad Types.FailN1)

-- | Check that an instance add with too high memory or disk will be
-- rejected.
prop_addPriFM :: Node.Node -> Instance.Instance -> Property
prop_addPriFM node inst =
  Instance.mem inst >= Node.fMem node && not (Node.failN1 node) &&
  Instance.usesMemory inst ==>
  (Node.addPri node inst'' ==? Bad Types.FailMem)
  where inst' = setInstanceSmallerThanNode node inst
        inst'' = inst' { Instance.mem = Instance.mem inst }

-- | Check that adding a primary instance with too much disk fails
-- with type FailDisk.
prop_addPriFD :: Instance.Instance -> Property
prop_addPriFD inst =
  forAll (genNode (Just 1) Nothing) $ \node ->
  forAll (elements Instance.localStorageTemplates) $ \dt ->
  Instance.dsk inst >= Node.fDsk node && not (Node.failN1 node) ==>
  let inst' = setInstanceSmallerThanNode node inst
      inst'' = inst' { Instance.dsk = Instance.dsk inst
                     , Instance.diskTemplate = dt }
  in (Node.addPri node inst'' ==? Bad Types.FailDisk)

-- | Check if an instance exceeds a spindles limit or has no spindles set.
hasInstTooManySpindles :: Instance.Instance -> Int -> Bool
hasInstTooManySpindles inst sp_lim =
  case Instance.getTotalSpindles inst of
    Just s -> s > sp_lim
    Nothing -> True

-- | Check that adding a primary instance with too many spindles fails
-- with type FailSpindles (when exclusive storage is enabled).
prop_addPriFS :: Instance.Instance -> Property
prop_addPriFS inst =
  forAll genExclStorNode $ \node ->
  forAll (elements Instance.localStorageTemplates) $ \dt ->
  hasInstTooManySpindles inst (Node.fSpindles node) &&
    not (Node.failN1 node) ==>
  let inst' = setInstanceSmallerThanNode node inst
      inst'' = inst' { Instance.disks = Instance.disks inst
                     , Instance.diskTemplate = dt }
  in (Node.addPri node inst'' ==? Bad Types.FailSpindles)

-- | Check that adding a primary instance with too many VCPUs fails
-- with type FailCPU.
prop_addPriFC :: Property
prop_addPriFC =
  forAll (choose (1, maxCpu)) $ \extra ->
  forAll genMaybeExclStorNode $ \node ->
  forAll (arbitrary `suchThat` Instance.notOffline
                    `suchThat` (not . Instance.forthcoming)) $ \inst ->
  let inst' = setInstanceSmallerThanNode node inst
      inst'' = inst' { Instance.vcpus = Node.availCpu node + extra }
  in case Node.addPri node inst'' of
       Bad Types.FailCPU -> passTest
       v -> failTest $ "Expected OpFail FailCPU, but got " ++ show v

-- | Check that an instance add with too high memory or disk will be
-- rejected.
prop_addSec :: Node.Node -> Instance.Instance -> Int -> Property
prop_addSec node inst pdx =
  ((Instance.mem inst >= (Node.fMem node - Node.rMem node) &&
    not (Instance.isOffline inst)) ||
   Instance.dsk inst >= Node.fDsk node ||
   (Node.exclStorage node &&
    hasInstTooManySpindles inst (Node.fSpindles node))) &&
  not (Node.failN1 node) ==>
      isBad (Node.addSec node inst pdx)

-- | Check that an offline instance with reasonable disk size but
-- extra mem/cpu can always be added.
prop_addOfflinePri :: NonNegative Int -> NonNegative Int -> Property
prop_addOfflinePri (NonNegative extra_mem) (NonNegative extra_cpu) =
  forAll genMaybeExclStorNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let inst' = inst { Instance.runSt = Types.StatusOffline
                   , Instance.mem = Node.availMem node + extra_mem
                   , Instance.vcpus = Node.availCpu node + extra_cpu }
  in case Node.addPriEx True node inst' of
       Ok _ -> passTest
       v -> failTest $ "Expected OpGood, but got: " ++ show v

-- | Check that an offline instance with reasonable disk size but
-- extra mem/cpu can always be added.
prop_addOfflineSec :: NonNegative Int -> NonNegative Int
                   -> Types.Ndx -> Property
prop_addOfflineSec (NonNegative extra_mem) (NonNegative extra_cpu) pdx =
  forAll genMaybeExclStorNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let inst' = inst { Instance.runSt = Types.StatusOffline
                   , Instance.mem = Node.availMem node + extra_mem
                   , Instance.vcpus = Node.availCpu node + extra_cpu
                   , Instance.diskTemplate = Types.DTDrbd8 }
  in case Node.addSec node inst' pdx of
       Ok _ -> passTest
       v -> failTest $ "Expected OpGood/OpGood, but got: " ++ show v

-- | Checks for memory reservation changes.
prop_rMem :: Instance.Instance -> Property
prop_rMem inst =
  not (Instance.isOffline inst) && not (Instance.forthcoming inst) ==>
  -- TODO Should we also require ((> Types.unitMem) . Node.fMemForth) ?
  forAll (genMaybeExclStorNode `suchThat` ((> Types.unitMem) . Node.fMem)) $
    \node ->
  -- ab = auto_balance, nb = non-auto_balance
  -- we use -1 as the primary node of the instance
  let inst' = inst { Instance.pNode = -1, Instance.autoBalance = True
                   , Instance.diskTemplate = Types.DTDrbd8 }
      inst_ab = setInstanceSmallerThanNode node inst'
      inst_nb = inst_ab { Instance.autoBalance = False }
      -- now we have the two instances, identical except the
      -- autoBalance attribute
      orig_rmem = Node.rMem node
      inst_idx = Instance.idx inst_ab
      node_add_ab = Node.addSec node inst_ab (-1)
      node_add_nb = Node.addSec node inst_nb (-1)
      node_del_ab = liftM (`Node.removeSec` inst_ab) node_add_ab
      node_del_nb = liftM (`Node.removeSec` inst_nb) node_add_nb
  in case (node_add_ab, node_add_nb, node_del_ab, node_del_nb) of
       (Ok a_ab, Ok a_nb,
        Ok d_ab, Ok d_nb) ->
         counterexample "Consistency checks failed" $
           Node.rMem a_ab >  orig_rmem &&
           Node.rMem a_ab - orig_rmem == Instance.mem inst_ab &&
           Node.rMem a_nb == orig_rmem &&
           Node.rMem d_ab == orig_rmem &&
           Node.rMem d_nb == orig_rmem &&
           -- this is not related to rMem, but as good a place to
           -- test as any
           inst_idx `elem` Node.sList a_ab &&
           inst_idx `notElem` Node.sList d_ab
       x -> failTest $ "Failed to add/remove instances: " ++ show x

-- | Check mdsk setting.
prop_setMdsk :: Node.Node -> SmallRatio -> Bool
prop_setMdsk node mx =
  Node.loDsk node' >= 0 &&
  fromIntegral (Node.loDsk node') <= Node.tDsk node &&
  Node.availDisk node' >= 0 &&
  Node.availDisk node' <= Node.fDsk node' &&
  fromIntegral (Node.availDisk node') <= Node.tDsk node' &&
  Node.mDsk node' == mx'
    where node' = Node.setMdsk node mx'
          SmallRatio mx' = mx

-- Check tag maps
prop_tagMaps_idempotent :: Property
prop_tagMaps_idempotent =
  forAll genTags $ \tags ->
  Node.delTags (Node.addTags m tags) tags ==? m
    where m = Map.empty

prop_tagMaps_reject :: Property
prop_tagMaps_reject =
  forAll (genTags `suchThat` (not . null)) $ \tags ->
  let m = Node.addTags Map.empty tags
  in all (\t -> Node.rejectAddTags m [t]) tags

prop_showField :: Node.Node -> Property
prop_showField node =
  forAll (elements Node.defaultFields) $ \ field ->
  fst (Node.showHeader field) /= Types.unknownField &&
  Node.showField node field /= Types.unknownField

prop_computeGroups :: [Node.Node] -> Bool
prop_computeGroups nodes =
  let ng = Node.computeGroups nodes
      onlyuuid = map fst ng
  in length nodes == sum (map (length . snd) ng) &&
     all (\(guuid, ns) -> all ((== guuid) . Node.group) ns) ng &&
     length (nub onlyuuid) == length onlyuuid &&
     (null nodes || not (null ng))

-- Check idempotence of add/remove operations
prop_addPri_idempotent :: Property
prop_addPri_idempotent =
  forAll genMaybeExclStorNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  case Node.addPri node inst of
    Ok node' -> Node.removePri node' inst ==? node
    _ -> failTest "Can't add instance"

prop_addSec_idempotent :: Property
prop_addSec_idempotent =
  forAll genMaybeExclStorNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let pdx = Node.idx node + 1
      inst' = Instance.setPri inst pdx
      inst'' = inst' { Instance.diskTemplate = Types.DTDrbd8 }
  in case Node.addSec node inst'' pdx of
       Ok node' -> Node.removeSec node' inst'' ==? node
       _ -> failTest "Can't add instance"

-- | Check that no graph is created on an empty node list.
case_emptyNodeList :: Assertion
case_emptyNodeList =
  assertEqual "" Nothing $ Node.mkNodeGraph emptynodes emptyinstances
    where emptynodes = Container.empty :: Node.List
          emptyinstances = Container.empty :: Instance.List

-- | Check that the number of vertices of a nodegraph is equal to the number of
-- nodes in the original node list.
prop_numVertices :: Property
prop_numVertices =
  forAll genNodeGraph $ \(graph, nl, _) ->
    (fmap numvertices graph ==? Just (Container.size nl))
    where numvertices = length . Graph.vertices

-- | Check that the number of edges of a nodegraph is equal to twice the number
-- of instances with secondary nodes in the original instance list.
prop_numEdges :: Property
prop_numEdges =
  forAll genNodeGraph $ \(graph, _, il) ->
    (fmap numedges graph ==? Just (numwithsec il * 2))
    where numedges = length . Graph.edges
          numwithsec = length . filter Instance.hasSecondary . Container.elems

-- | Check that a node graph is colorable.
prop_nodeGraphIsColorable :: Property
prop_nodeGraphIsColorable =
  forAll genNodeGraph $ \(graph, _, _) ->
    fmap HGraph.isColorable graph ==? Just True

-- | Check that each edge in a nodegraph is an instance.
prop_instanceIsEdge :: Property
prop_instanceIsEdge =
  forAll genNodeGraph $ \(graph, _, il) ->
    fmap (\g -> all (`isEdgeOn` g) (iwithsec il)) graph ==? Just True
    where i `isEdgeOn` g = iEdges i `intersect` Graph.edges g == iEdges i
          iEdges i = [ (Instance.pNode i, Instance.sNode i)
                     , (Instance.sNode i, Instance.pNode i)]
          iwithsec = filter Instance.hasSecondary . Container.elems

-- | Check that each instance in an edge in the resulting nodegraph.
prop_edgeIsInstance :: Property
prop_edgeIsInstance =
  forAll genNodeGraph $ \(graph, _, il) ->
    fmap (all (`isInstanceIn` il).Graph.edges) graph ==? Just True
      where e `isInstanceIn` il = any (`hasNodes` e) (Container.elems il)
            i `hasNodes` (v1,v2) =
              Instance.allNodes i `elem` permutations [v1,v2]

-- | List of tests for the Node module.
testSuite "HTools/Node"
            [ 'prop_setAlias
            , 'prop_setOffline
            , 'prop_setMcpu
            , 'prop_setXmem
            , 'prop_addPriFM
            , 'prop_addPriFD
            , 'prop_addPriFS
            , 'prop_addPriFC
            , 'prop_addPri_NoN1Fail
            , 'prop_addSec
            , 'prop_addOfflinePri
            , 'prop_addOfflineSec
            , 'prop_rMem
            , 'prop_setMdsk
            , 'prop_tagMaps_idempotent
            , 'prop_tagMaps_reject
            , 'prop_showField
            , 'prop_computeGroups
            , 'prop_addPri_idempotent
            , 'prop_addSec_idempotent
            , 'case_emptyNodeList
            , 'prop_numVertices
            , 'prop_numEdges
            , 'prop_nodeGraphIsColorable
            , 'prop_edgeIsInstance
            , 'prop_instanceIsEdge
            ]

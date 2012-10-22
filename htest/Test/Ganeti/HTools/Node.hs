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

module Test.Ganeti.HTools.Node
  ( testHTools_Node
  , Node.Node(..)
  , setInstanceSmallerThanNode
  , genNode
  , genOnlineNode
  ) where

import Test.QuickCheck

import Control.Monad
import qualified Data.Map as Map
import Data.List

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools
import Test.Ganeti.HTools.Instance (genInstanceSmallerThanNode)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Types as Types

-- * Arbitrary instances

-- | Generates an arbitrary node based on sizing information.
genNode :: Maybe Int -- ^ Minimum node size in terms of units
        -> Maybe Int -- ^ Maximum node size (when Nothing, bounded
                     -- just by the max... constants)
        -> Gen Node.Node
genNode min_multiplier max_multiplier = do
  let (base_mem, base_dsk, base_cpu) =
        case min_multiplier of
          Just mm -> (mm * Types.unitMem,
                      mm * Types.unitDsk,
                      mm * Types.unitCpu)
          Nothing -> (0, 0, 0)
      (top_mem, top_dsk, top_cpu)  =
        case max_multiplier of
          Just mm -> (mm * Types.unitMem,
                      mm * Types.unitDsk,
                      mm * Types.unitCpu)
          Nothing -> (maxMem, maxDsk, maxCpu)
  name  <- getFQDN
  mem_t <- choose (base_mem, top_mem)
  mem_f <- choose (base_mem, mem_t)
  mem_n <- choose (0, mem_t - mem_f)
  dsk_t <- choose (base_dsk, top_dsk)
  dsk_f <- choose (base_dsk, dsk_t)
  cpu_t <- choose (base_cpu, top_cpu)
  offl  <- arbitrary
  let n = Node.create name (fromIntegral mem_t) mem_n mem_f
          (fromIntegral dsk_t) dsk_f (fromIntegral cpu_t) offl 1 0
      n' = Node.setPolicy nullIPolicy n
  return $ Node.buildPeers n' Container.empty

-- | Helper function to generate a sane node.
genOnlineNode :: Gen Node.Node
genOnlineNode =
  arbitrary `suchThat` (\n -> not (Node.offline n) &&
                              not (Node.failN1 n) &&
                              Node.availDisk n > 0 &&
                              Node.availMem n > 0 &&
                              Node.availCpu n > 0)

-- and a random node
instance Arbitrary Node.Node where
  arbitrary = genNode Nothing Nothing

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

prop_setFmemGreater :: Node.Node -> Int -> Property
prop_setFmemGreater node new_mem =
  not (Node.failN1 node) && (Node.rMem node >= 0) &&
  (new_mem > Node.rMem node) ==>
  not (Node.failN1 (Node.setFmem node new_mem))

prop_setFmemExact :: Node.Node -> Property
prop_setFmemExact node =
  not (Node.failN1 node) && (Node.rMem node >= 0) ==>
  not (Node.failN1 (Node.setFmem node (Node.rMem node)))

-- Check if adding an instance that consumes exactly all reserved
-- memory does not raise an N+1 error
prop_addPri_NoN1Fail :: Property
prop_addPri_NoN1Fail =
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let inst' = inst { Instance.mem = Node.fMem node - Node.rMem node }
  in (Node.addPri node inst' /=? Bad Types.FailN1)

-- | Check that an instance add with too high memory or disk will be
-- rejected.
prop_addPriFM :: Node.Node -> Instance.Instance -> Property
prop_addPriFM node inst =
  Instance.mem inst >= Node.fMem node && not (Node.failN1 node) &&
  not (Instance.isOffline inst) ==>
  (Node.addPri node inst'' ==? Bad Types.FailMem)
  where inst' = setInstanceSmallerThanNode node inst
        inst'' = inst' { Instance.mem = Instance.mem inst }

-- | Check that adding a primary instance with too much disk fails
-- with type FailDisk.
prop_addPriFD :: Node.Node -> Instance.Instance -> Property
prop_addPriFD node inst =
  forAll (elements Instance.localStorageTemplates) $ \dt ->
  Instance.dsk inst >= Node.fDsk node && not (Node.failN1 node) ==>
  let inst' = setInstanceSmallerThanNode node inst
      inst'' = inst' { Instance.dsk = Instance.dsk inst
                     , Instance.diskTemplate = dt }
  in (Node.addPri node inst'' ==? Bad Types.FailDisk)

-- | Check that adding a primary instance with too many VCPUs fails
-- with type FailCPU.
prop_addPriFC :: Property
prop_addPriFC =
  forAll (choose (1, maxCpu)) $ \extra ->
  forAll genOnlineNode $ \node ->
  forAll (arbitrary `suchThat` Instance.notOffline) $ \inst ->
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
   Instance.dsk inst >= Node.fDsk node) &&
  not (Node.failN1 node) ==>
      isBad (Node.addSec node inst pdx)

-- | Check that an offline instance with reasonable disk size but
-- extra mem/cpu can always be added.
prop_addOfflinePri :: NonNegative Int -> NonNegative Int -> Property
prop_addOfflinePri (NonNegative extra_mem) (NonNegative extra_cpu) =
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let inst' = inst { Instance.runSt = Types.AdminOffline
                   , Instance.mem = Node.availMem node + extra_mem
                   , Instance.vcpus = Node.availCpu node + extra_cpu }
  in case Node.addPri node inst' of
       Ok _ -> passTest
       v -> failTest $ "Expected OpGood, but got: " ++ show v

-- | Check that an offline instance with reasonable disk size but
-- extra mem/cpu can always be added.
prop_addOfflineSec :: NonNegative Int -> NonNegative Int
                   -> Types.Ndx -> Property
prop_addOfflineSec (NonNegative extra_mem) (NonNegative extra_cpu) pdx =
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let inst' = inst { Instance.runSt = Types.AdminOffline
                   , Instance.mem = Node.availMem node + extra_mem
                   , Instance.vcpus = Node.availCpu node + extra_cpu
                   , Instance.diskTemplate = Types.DTDrbd8 }
  in case Node.addSec node inst' pdx of
       Ok _ -> passTest
       v -> failTest $ "Expected OpGood/OpGood, but got: " ++ show v

-- | Checks for memory reservation changes.
prop_rMem :: Instance.Instance -> Property
prop_rMem inst =
  not (Instance.isOffline inst) ==>
  forAll (genOnlineNode `suchThat` ((> Types.unitMem) . Node.fMem)) $ \node ->
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
         printTestCase "Consistency checks failed" $
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
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  case Node.addPri node inst of
    Ok node' -> Node.removePri node' inst ==? node
    _ -> failTest "Can't add instance"

prop_addSec_idempotent :: Property
prop_addSec_idempotent =
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let pdx = Node.idx node + 1
      inst' = Instance.setPri inst pdx
      inst'' = inst' { Instance.diskTemplate = Types.DTDrbd8 }
  in case Node.addSec node inst'' pdx of
       Ok node' -> Node.removeSec node' inst'' ==? node
       _ -> failTest "Can't add instance"

testSuite "HTools/Node"
            [ 'prop_setAlias
            , 'prop_setOffline
            , 'prop_setMcpu
            , 'prop_setFmemGreater
            , 'prop_setFmemExact
            , 'prop_setXmem
            , 'prop_addPriFM
            , 'prop_addPriFD
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
            ]

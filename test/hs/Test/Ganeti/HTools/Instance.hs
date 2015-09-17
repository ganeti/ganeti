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

module Test.Ganeti.HTools.Instance
  ( testHTools_Instance
  , genInstanceSmallerThanNode
  , genInstanceMaybeBiggerThanNode
  , genInstanceOnNodeList
  , genInstanceList
  , Instance.Instance(..)
  ) where

import Prelude ()
import Ganeti.Prelude

import Control.Arrow ((&&&))
import Control.Monad (liftM)
import Test.QuickCheck hiding (Result)

import Test.Ganeti.TestHTools (nullISpec)
import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.HTools.Types ()

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Types as Types

-- * Arbitrary instances

-- | Generates a random instance with maximum and minimum disk/mem/cpu values.
genInstanceWithin :: Int -> Int -> Int -> Int
                  -> Int -> Int -> Int -> Maybe Int
                  -> Gen Instance.Instance
genInstanceWithin min_mem min_dsk min_cpu min_spin
                  max_mem max_dsk max_cpu max_spin = do
  name <- genFQDN
  mem <- choose (min_mem, max_mem)
  dsk <- choose (min_dsk, max_dsk)
  run_st <- arbitrary
  pn <- arbitrary
  sn <- arbitrary
  vcpus <- choose (min_cpu, max_cpu)
  dt <- arbitrary
  spindles <- case max_spin of
    Nothing -> genMaybe $ choose (min_spin, maxSpindles)
    Just ls -> liftM Just $ choose (min_spin, ls)
  forthcoming <- arbitrary
  let disk = Instance.Disk dsk spindles
  return $ Instance.create
    name mem dsk [disk] vcpus run_st [] True pn sn dt 1 [] forthcoming

-- | Generate an instance with maximum disk/mem/cpu values.
genInstanceSmallerThan :: Int -> Int -> Int -> Maybe Int
                       -> Gen Instance.Instance
genInstanceSmallerThan = genInstanceWithin 1 0 1 0

-- | Generates an instance smaller than a node.
genInstanceSmallerThanNode :: Node.Node -> Gen Instance.Instance
genInstanceSmallerThanNode node =
  genInstanceSmallerThan (Node.availMem node `div` 2)
                         (Node.availDisk node `div` 2)
                         (Node.availCpu node `div` 2)
                         (if Node.exclStorage node
                          then Just $ Node.fSpindlesForth node `div` 2
                          else Nothing)

-- | Generates an instance possibly bigger than a node.
-- In any case, that instance will be bigger than the node's ipolicy's lower
-- bound.
genInstanceMaybeBiggerThanNode :: Node.Node -> Gen Instance.Instance
genInstanceMaybeBiggerThanNode node =
  let minISpec = runListHead nullISpec Types.minMaxISpecsMinSpec
                 . Types.iPolicyMinMaxISpecs $ Node.iPolicy node
  in genInstanceWithin (Types.iSpecMemorySize minISpec)
                       (Types.iSpecDiskSize minISpec)
                       (Types.iSpecCpuCount minISpec)
                       (Types.iSpecSpindleUse minISpec)
                       (Node.availMem  node + Types.unitMem * 2)
                       (Node.availDisk node + Types.unitDsk * 3)
                       (Node.availCpu  node + Types.unitCpu * 4)
                       (if Node.exclStorage node
                          then Just $ Node.fSpindles node +
                               Types.unitSpindle * 5
                          else Nothing)

-- | Generates an instance with nodes on a node list.
-- The following rules are respected:
-- 1. The instance is never bigger than its primary node
-- 2. If possible the instance has different pnode and snode
-- 3. Else disk templates which require secondary nodes are disabled
genInstanceOnNodeList :: Node.List -> Gen Instance.Instance
genInstanceOnNodeList nl = do
  let nsize = Container.size nl
  pnode <- choose (0, nsize-1)
  let (snodefilter, dtfilter) =
        if nsize >= 2
          then ((/= pnode), const True)
          else (const True, not . Instance.hasSecondary)
  snode <- choose (0, nsize-1) `suchThat` snodefilter
  i <- genInstanceSmallerThanNode (Container.find pnode nl) `suchThat` dtfilter
  return $ i { Instance.pNode = pnode, Instance.sNode = snode }

-- | Generates an instance list given an instance generator.
genInstanceList :: Gen Instance.Instance -> Gen Instance.List
genInstanceList igen = fmap (snd . Loader.assignIndices) names_instances
    where names_instances =
            map (Instance.name &&& id) <$> listOf igen

-- let's generate a random instance
instance Arbitrary Instance.Instance where
  arbitrary = genInstanceSmallerThan maxMem maxDsk maxCpu Nothing

-- * Test cases

-- Simple instance tests, we only have setter/getters

prop_creat :: Instance.Instance -> Property
prop_creat inst =
  Instance.name inst ==? Instance.alias inst

prop_setIdx :: Instance.Instance -> Types.Idx -> Property
prop_setIdx inst idx =
  Instance.idx (Instance.setIdx inst idx) ==? idx

prop_setName :: Instance.Instance -> String -> Bool
prop_setName inst name =
  Instance.name newinst == name &&
  Instance.alias newinst == name
    where newinst = Instance.setName inst name

prop_setAlias :: Instance.Instance -> String -> Bool
prop_setAlias inst name =
  Instance.name newinst == Instance.name inst &&
  Instance.alias newinst == name
    where newinst = Instance.setAlias inst name

prop_setPri :: Instance.Instance -> Types.Ndx -> Property
prop_setPri inst pdx =
  Instance.pNode (Instance.setPri inst pdx) ==? pdx

prop_setSec :: Instance.Instance -> Types.Ndx -> Property
prop_setSec inst sdx =
  Instance.sNode (Instance.setSec inst sdx) ==? sdx

prop_setBoth :: Instance.Instance -> Types.Ndx -> Types.Ndx -> Bool
prop_setBoth inst pdx sdx =
  Instance.pNode si == pdx && Instance.sNode si == sdx
    where si = Instance.setBoth inst pdx sdx

prop_shrinkMG :: Instance.Instance -> Property
prop_shrinkMG inst =
  Instance.mem inst >= 2 * Types.unitMem ==>
    case Instance.shrinkByType inst Types.FailMem of
      Ok inst' -> Instance.mem inst' ==? Instance.mem inst - Types.unitMem
      Bad msg -> failTest msg

prop_shrinkMF :: Instance.Instance -> Property
prop_shrinkMF inst =
  forAll (choose (0, 2 * Types.unitMem - 1)) $ \mem ->
    let inst' = inst { Instance.mem = mem}
    in isBad $ Instance.shrinkByType inst' Types.FailMem

prop_shrinkCG :: Instance.Instance -> Property
prop_shrinkCG inst =
  Instance.vcpus inst >= 2 * Types.unitCpu ==>
    case Instance.shrinkByType inst Types.FailCPU of
      Ok inst' -> Instance.vcpus inst' ==? Instance.vcpus inst - Types.unitCpu
      Bad msg -> failTest msg

prop_shrinkCF :: Instance.Instance -> Property
prop_shrinkCF inst =
  forAll (choose (0, 2 * Types.unitCpu - 1)) $ \vcpus ->
    let inst' = inst { Instance.vcpus = vcpus }
    in isBad $ Instance.shrinkByType inst' Types.FailCPU

prop_shrinkDG :: Instance.Instance -> Property
prop_shrinkDG inst =
  Instance.dsk inst >= 2 * Types.unitDsk ==>
    case Instance.shrinkByType inst Types.FailDisk of
      Ok inst' -> Instance.dsk inst' ==? Instance.dsk inst - Types.unitDsk
      Bad msg -> failTest msg

prop_shrinkDF :: Instance.Instance -> Property
prop_shrinkDF inst =
  forAll (choose (0, 2 * Types.unitDsk - 1)) $ \dsk ->
    let inst' = inst { Instance.dsk = dsk
                     , Instance.disks = [Instance.Disk dsk Nothing] }
    in isBad $ Instance.shrinkByType inst' Types.FailDisk

prop_setMovable :: Instance.Instance -> Bool -> Property
prop_setMovable inst m =
  Instance.movable inst' ==? m
    where inst' = Instance.setMovable inst m

testSuite "HTools/Instance"
            [ 'prop_creat
            , 'prop_setIdx
            , 'prop_setName
            , 'prop_setAlias
            , 'prop_setPri
            , 'prop_setSec
            , 'prop_setBoth
            , 'prop_shrinkMG
            , 'prop_shrinkMF
            , 'prop_shrinkCG
            , 'prop_shrinkCF
            , 'prop_shrinkDG
            , 'prop_shrinkDF
            , 'prop_setMovable
            ]

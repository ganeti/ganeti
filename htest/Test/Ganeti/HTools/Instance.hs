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

module Test.Ganeti.HTools.Instance
  ( testHTools_Instance
  , genInstanceSmallerThanNode
  , genInstanceMaybeBiggerThanNode
  , genInstanceSmallerThan
  , genInstanceList
  , Instance.Instance(..)
  ) where

import Test.QuickCheck hiding (Result)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.HTools.Types ()

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Types as Types

-- * Arbitrary instances

-- | Generates a random instance with maximum disk/mem/cpu values.
genInstanceSmallerThan :: Int -> Int -> Int -> Gen Instance.Instance
genInstanceSmallerThan lim_mem lim_dsk lim_cpu = do
  name <- genFQDN
  mem <- choose (0, lim_mem)
  dsk <- choose (0, lim_dsk)
  run_st <- arbitrary
  pn <- arbitrary
  sn <- arbitrary
  vcpus <- choose (0, lim_cpu)
  dt <- arbitrary
  return $ Instance.create name mem dsk vcpus run_st [] True pn sn dt 1

-- | Generates an instance smaller than a node.
genInstanceSmallerThanNode :: Node.Node -> Gen Instance.Instance
genInstanceSmallerThanNode node =
  genInstanceSmallerThan (Node.availMem node `div` 2)
                         (Node.availDisk node `div` 2)
                         (Node.availCpu node `div` 2)

-- | Generates an instance possibly bigger than a node.
genInstanceMaybeBiggerThanNode :: Node.Node -> Gen Instance.Instance
genInstanceMaybeBiggerThanNode node =
  genInstanceSmallerThan (Node.availMem  node + Types.unitMem * 2)
                         (Node.availDisk node + Types.unitDsk * 3)
                         (Node.availCpu  node + Types.unitCpu * 4)

-- | Generates an instance list given an instance generator.
genInstanceList :: Gen Instance.Instance -> Gen Instance.List
genInstanceList igen = fmap (snd . Loader.assignIndices) names_instances
    where names_instances =
            (fmap . map) (\n -> (Instance.name n, n)) $ listOf igen

-- let's generate a random instance
instance Arbitrary Instance.Instance where
  arbitrary = genInstanceSmallerThan maxMem maxDsk maxCpu

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
    let inst' = inst { Instance.dsk = dsk }
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

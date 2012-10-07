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

module Test.Ganeti.HTools.Simu (testHTools_Simu) where

import Test.QuickCheck hiding (Result)

import Control.Monad
import qualified Data.IntMap as IntMap
import Text.Printf (printf)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Simu as Simu
import qualified Ganeti.HTools.Types as Types

-- | Generates a tuple of specs for simulation.
genSimuSpec :: Gen (String, Int, Int, Int, Int)
genSimuSpec = do
  pol <- elements [C.allocPolicyPreferred,
                   C.allocPolicyLastResort, C.allocPolicyUnallocable,
                  "p", "a", "u"]
 -- should be reasonable (nodes/group), bigger values only complicate
 -- the display of failed tests, and we don't care (in this particular
 -- test) about big node groups
  nodes <- choose (0, 20)
  dsk <- choose (0, maxDsk)
  mem <- choose (0, maxMem)
  cpu <- choose (0, maxCpu)
  return (pol, nodes, dsk, mem, cpu)

-- | Checks that given a set of corrects specs, we can load them
-- successfully, and that at high-level the values look right.
prop_Load :: Property
prop_Load =
  forAll (choose (0, 10)) $ \ngroups ->
  forAll (replicateM ngroups genSimuSpec) $ \specs ->
  let strspecs = map (\(p, n, d, m, c) -> printf "%s,%d,%d,%d,%d"
                                          p n d m c::String) specs
      totnodes = sum $ map (\(_, n, _, _, _) -> n) specs
      mdc_in = concatMap (\(_, n, d, m, c) ->
                            replicate n (fromIntegral m, fromIntegral d,
                                         fromIntegral c,
                                         fromIntegral m, fromIntegral d))
               specs :: [(Double, Double, Double, Int, Int)]
  in case Simu.parseData strspecs of
       Bad msg -> failTest $ "Failed to load specs: " ++ msg
       Ok (Loader.ClusterData gl nl il tags ipol) ->
         let nodes = map snd $ IntMap.toAscList nl
             nidx = map Node.idx nodes
             mdc_out = map (\n -> (Node.tMem n, Node.tDsk n, Node.tCpu n,
                                   Node.fMem n, Node.fDsk n)) nodes
         in
         Container.size gl ==? ngroups .&&.
         Container.size nl ==? totnodes .&&.
         Container.size il ==? 0 .&&.
         length tags ==? 0 .&&.
         ipol ==? Types.defIPolicy .&&.
         nidx ==? [1..totnodes] .&&.
         mdc_in ==? mdc_out .&&.
         map Group.iPolicy (Container.elems gl) ==?
             replicate ngroups Types.defIPolicy

testSuite "HTools/Simu"
            [ 'prop_Load
            ]

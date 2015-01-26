{-| Implementation of special handling of dedicated clusters.

-}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.HTools.Dedicated
  ( isDedicated
  , testInstances
  , allocationVector
  , Metric
  , lostAllocationsMetric
  , allocateOnSingle
  ) where

import Control.Applicative (liftA2)
import qualified Data.Foldable as F
import Data.Function (on)
import qualified Data.IntMap as IntMap
import qualified Data.IntSet as IntSet
import Data.List (sortBy)

import Ganeti.BasicTypes (iterateOk)
import qualified Ganeti.HTools.AlgorithmParams as Alg
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Types as T

-- | Given a cluster description and maybe a group name, decide
-- if that group, or all allocatable groups if no group is given,
-- is dedicated.
isDedicated :: Loader.ClusterData -> Maybe String -> Bool
isDedicated cdata maybeGroup =
  let groups =
        IntMap.keysSet
        . IntMap.filter (maybe ((/=) T.AllocUnallocable . Group.allocPolicy)
                               (\name -> (==) name . Group.name) maybeGroup)
        $ Loader.cdGroups cdata
  in F.all (liftA2 (||) Node.exclStorage
            $ not  . (`IntSet.member` groups) . Node.group)
     $ Loader.cdNodes cdata

-- | Given a specification interval, create an instance minimally fitting
-- into that interval. In other words create an instance from the lower bounds
-- of the specified interval.
minimallyCompliantInstance :: T.ISpec -> Instance.Instance
minimallyCompliantInstance spec =
  Instance.create "minimalspecinstance"
    (T.iSpecMemorySize spec)
    (T.iSpecDiskSize spec)
    []
    (T.iSpecCpuCount spec)
    T.Running [] False Node.noSecondary Node.noSecondary T.DTPlain
    (T.iSpecSpindleUse spec)
    [] False

-- | From an instance policy get the list of test instances, in correct order,
-- for which the allocation count has to be determined for the lost allocations
-- metrics.
testInstances :: T.IPolicy -> [Instance.Instance]
testInstances =
  map minimallyCompliantInstance
  . sortBy (flip compare `on` T.iSpecDiskSize)
  . map T.minMaxISpecsMinSpec
  . T.iPolicyMinMaxISpecs

-- | Given the test instances, compute the allocations vector of a node
allocationVector :: [Instance.Instance] -> Node.Node -> [Int]
allocationVector insts node =
  map (\ inst -> length $ iterateOk (`Node.addPri` inst) node) insts

-- | The metric do be used in dedicated allocation.
type Metric = ([Int], Int)

-- | Given the test instances and an instance to be placed, compute
-- the lost allocations metrics for that node, together with the
-- modified node. Return Bad if it is not possible to place the
-- instance on that node.
lostAllocationsMetric :: Alg.AlgorithmOptions
                      -> [Instance.Instance]
                      -> Instance.Instance
                      -> Node.Node
                      -> T.OpResult (Metric, Node.Node)
lostAllocationsMetric opts insts inst node = do
  let allocVec = allocationVector insts
      before = allocVec node
      force = Alg.algIgnoreSoftErrors opts
  node' <- Node.addPriEx force node inst
  let after = allocVec node'
      disk = Node.fDsk node'
  return ((zipWith (-) before after, disk), node')

-- | Allocate an instance on a given node.
allocateOnSingle :: Alg.AlgorithmOptions
                 -> Node.List -> Instance.Instance -> T.Ndx
                 -> T.OpResult (Node.GenericAllocElement Metric)
allocateOnSingle opts nl inst new_pdx = do
  let primary = Container.find new_pdx nl
      policy = Node.iPolicy primary
      testInst = testInstances policy
      excl = Node.exclStorage primary
      new_inst = Instance.setBoth inst new_pdx Node.noSecondary
  Instance.instMatchesPolicy inst policy excl
  (metrics, new_p) <- lostAllocationsMetric opts testInst inst primary
  let new_nl = Container.add new_pdx new_p nl
  return (new_nl, new_inst, [new_p], metrics)

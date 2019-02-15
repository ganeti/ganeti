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
  , allocateOnPair
  , findAllocation
  , runDedicatedAllocation
  ) where

import Control.Applicative (liftA2, (<$>))
import Control.Arrow ((&&&))
import Control.Monad (unless, liftM, foldM, mplus)
import qualified Data.Foldable as F
import Data.Function (on)
import qualified Data.IntMap as IntMap
import qualified Data.IntSet as IntSet
import Data.List (sortBy, intercalate)

import Ganeti.BasicTypes (iterateOk, Result, failError)
import qualified Ganeti.HTools.AlgorithmParams as Alg
import qualified Ganeti.HTools.Backend.IAlloc as IAlloc
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.AllocationSolution as AllocSol
import qualified Ganeti.HTools.Cluster.Utils as ClusterUtils
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
                 -> T.OpResult (AllocSol.GenericAllocElement Metric)
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

-- | Allocate an instance on a given pair of nodes.
allocateOnPair :: Alg.AlgorithmOptions
               -> Node.List
               -> Instance.Instance
               -> T.Ndx
               -> T.Ndx
               -> T.OpResult (AllocSol.GenericAllocElement Metric)
allocateOnPair opts nl inst pdx sdx = do
  let primary = Container.find pdx nl
      secondary = Container.find sdx nl
      policy = Node.iPolicy primary
      testInst = testInstances policy
      inst' = Instance.setBoth inst pdx sdx
  Instance.instMatchesPolicy inst policy (Node.exclStorage primary)
  ((lAllP, dskP), primary') <- lostAllocationsMetric opts testInst inst' primary
  secondary' <- Node.addSec secondary inst' pdx
  let lAllS =  zipWith (-) (allocationVector testInst secondary)
                           (allocationVector testInst secondary')
      dskS = Node.fDsk secondary'
      metric = (zipWith (+) lAllP lAllS, dskP + dskS)
      nl' = Container.addTwo pdx primary' sdx secondary' nl
  return (nl', inst', [primary', secondary'], metric)

-- | Find an allocation for an instance on a group.
findAllocation :: Alg.AlgorithmOptions
               -> Group.List
               -> Node.List
               -> T.Gdx
               -> Instance.Instance
               -> Int
               -> Result (AllocSol.GenericAllocSolution Metric, [String])
findAllocation opts mggl mgnl gdx inst count = do
  let nl = Container.filter ((== gdx) . Node.group) mgnl
      group = Container.find gdx mggl
  unless (Cluster.hasRequiredNetworks group inst) . failError
         $ "The group " ++ Group.name group ++ " is not connected to\
           \ a network required by instance " ++ Instance.name inst
  allocNodes <- Cluster.genAllocNodes opts mggl nl count False
  solution <- case allocNodes of
    (Right []) -> fail "Not enough online nodes"
    (Right pairs) ->
      let sols = foldl AllocSol.sumAllocs AllocSol.emptyAllocSolution
                   $ map (\(p, ss) -> foldl
                           (\cstate ->
                             AllocSol.concatAllocs cstate
                             . allocateOnPair opts nl inst p)
                           AllocSol.emptyAllocSolution ss)
                     pairs
       in return $ AllocSol.genericAnnotateSolution show sols
    (Left []) -> fail "No online nodes"
    (Left nodes) ->
      let sols = foldl (\cstate ->
                          AllocSol.concatAllocs cstate
                          . allocateOnSingle opts nl inst)
                       AllocSol.emptyAllocSolution nodes
      in return $ AllocSol.genericAnnotateSolution show sols
  return (solution, AllocSol.solutionDescription (group, return solution))

-- | Find an allocation in a suitable group.
findMGAllocation :: Alg.AlgorithmOptions
                 -> Group.List
                 -> Node.List
                 -> Instance.List
                 -> Instance.Instance
                 -> Int
                 -> Result (AllocSol.GenericAllocSolution Metric)
findMGAllocation opts gl nl il inst count = do
  let groups_by_idx = ClusterUtils.splitCluster nl il
      genSol (gdx, (nl', _)) =
        liftM fst $ findAllocation opts gl nl' gdx inst count
      sols = map (flip Container.find gl . fst &&& genSol) groups_by_idx
      goodSols = Cluster.sortMGResults $ Cluster.filterMGResults sols
      all_msgs = concatMap AllocSol.solutionDescription sols
  case goodSols of
    [] -> fail $ intercalate ", " all_msgs
    (final_group, final_sol):_ ->
      let sel_msg = "Selected group: " ++ Group.name final_group
      in return $ final_sol { AllocSol.asLog = sel_msg : all_msgs }

-- | Handle allocation requests in the dedicated scenario.
runDedicatedAllocation :: Alg.AlgorithmOptions
                       -> Loader.Request
                       -> (Maybe (Node.List, Instance.List), String)
runDedicatedAllocation opts request =
  let Loader.Request rqtype (Loader.ClusterData gl nl il _ _) = request
      allocresult =
        case rqtype of
          Loader.Allocate inst (Cluster.AllocDetails count (Just gn)) rNds -> do
            gdx <- Group.idx <$> Container.findByName gl gn
            let opts' = opts { Alg.algRestrictToNodes =
                                 Alg.algRestrictToNodes opts `mplus` rNds }
            (solution, msgs) <- findAllocation opts' gl nl gdx inst count
            IAlloc.formatAllocate il $ solution { AllocSol.asLog = msgs }
          Loader.Allocate inst (Cluster.AllocDetails count Nothing) rNds ->
            let opts' = opts { Alg.algRestrictToNodes =
                                 Alg.algRestrictToNodes opts `mplus` rNds }
            in findMGAllocation opts' gl nl il inst count
                 >>= IAlloc.formatAllocate il
          Loader.MultiAllocate insts ->
            IAlloc.formatMultiAlloc =<< foldM
              (\(nl', il', res)
                (inst, Cluster.AllocDetails count maybeGroup) -> do
                  ares <- maybe (findMGAllocation opts gl nl' il' inst count)
                            (\gn -> do
                               gdx <- Group.idx <$> Container.findByName gl gn
                               liftM fst
                                 $ findAllocation opts gl nl gdx inst count)
                          maybeGroup
                  let sol = AllocSol.asSolution ares
                      nl'' = AllocSol.extractNl nl' il' sol
                      il'' = AllocSol.updateIl il' sol
                  return (nl'', il'', (inst, ares):res))
               (nl, il, []) insts
          _ -> fail "Dedicated Allocation only for proper allocation requests"
  in IAlloc.formatIAllocResult allocresult

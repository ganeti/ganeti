{-| Implementation of cluster-wide logic.

This module holds all pure cluster-logic; I\/O related functionality
goes into the /Main/ module for the individual binaries.

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

module Ganeti.HTools.Cluster
  (
    -- * Types
    AllocDetails(..)
  , AllocSolution(..)
  , EvacSolution(..)
  , Table(..)
  , CStats(..)
  , AllocNodes
  , AllocResult
  , AllocMethod
  , AllocSolutionList
  -- * Generic functions
  , totalResources
  , computeAllocationDelta
  -- * First phase functions
  , computeBadItems
  -- * Second phase functions
  , printSolutionLine
  , formatCmds
  , involvedNodes
  , getMoves
  , splitJobs
  -- * Display functions
  , printNodes
  , printInsts
  -- * Balacing functions
  , doNextBalance
  , tryBalance
  , compCV
  , compCVNodes
  , compDetailedCV
  , printStats
  , iMoveToJob
  -- * IAllocator functions
  , genAllocNodes
  , tryAlloc
  , tryGroupAlloc
  , tryMGAlloc
  , tryNodeEvac
  , tryChangeGroup
  , collapseFailures
  , allocList
  -- * Allocation functions
  , iterateAlloc
  , tieredAlloc
  -- * Node group functions
  , instanceGroup
  , findSplitInstances
  , splitCluster
  ) where

import Control.Applicative ((<$>), liftA2)
import Control.Arrow ((&&&))
import Control.Monad (unless)
import qualified Data.IntSet as IntSet
import Data.List
import Data.Maybe (fromJust, fromMaybe, isJust, isNothing)
import Data.Ord (comparing)
import Text.Printf (printf)

import Ganeti.BasicTypes
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..), defaultOptions)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Nic as Nic
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group
import Ganeti.HTools.Types
import Ganeti.Compat
import qualified Ganeti.OpCodes as OpCodes
import Ganeti.Utils
import Ganeti.Utils.Statistics
import Ganeti.Types (EvacMode(..), mkNonEmpty)

-- * Types

-- | Allocation details for an instance, specifying
-- | required number of nodes, and
-- | an optional group (name) to allocate to
data AllocDetails = AllocDetails Int (Maybe String)
                    deriving (Show)

-- | Allocation\/relocation solution.
data AllocSolution = AllocSolution
  { asFailures :: [FailMode]              -- ^ Failure counts
  , asAllocs   :: Int                     -- ^ Good allocation count
  , asSolution :: Maybe Node.AllocElement -- ^ The actual allocation result
  , asLog      :: [String]                -- ^ Informational messages
  }

-- | Node evacuation/group change iallocator result type. This result
-- type consists of actual opcodes (a restricted subset) that are
-- transmitted back to Ganeti.
data EvacSolution = EvacSolution
  { esMoved   :: [(Idx, Gdx, [Ndx])]  -- ^ Instances moved successfully
  , esFailed  :: [(Idx, String)]      -- ^ Instances which were not
                                      -- relocated
  , esOpCodes :: [[OpCodes.OpCode]]   -- ^ List of jobs
  } deriving (Show)

-- | Allocation results, as used in 'iterateAlloc' and 'tieredAlloc'.
type AllocResult = (FailStats, Node.List, Instance.List,
                    [Instance.Instance], [CStats])

-- | Type alias for easier handling.
type AllocSolutionList = [(Instance.Instance, AllocSolution)]

-- | A type denoting the valid allocation mode/pairs.
--
-- For a one-node allocation, this will be a @Left ['Ndx']@, whereas
-- for a two-node allocation, this will be a @Right [('Ndx',
-- ['Ndx'])]@. In the latter case, the list is basically an
-- association list, grouped by primary node and holding the potential
-- secondary nodes in the sub-list.
type AllocNodes = Either [Ndx] [(Ndx, [Ndx])]

-- | The empty solution we start with when computing allocations.
emptyAllocSolution :: AllocSolution
emptyAllocSolution = AllocSolution { asFailures = [], asAllocs = 0
                                   , asSolution = Nothing, asLog = [] }

-- | The empty evac solution.
emptyEvacSolution :: EvacSolution
emptyEvacSolution = EvacSolution { esMoved = []
                                 , esFailed = []
                                 , esOpCodes = []
                                 }

-- | The complete state for the balancing solution.
data Table = Table Node.List Instance.List Score [Placement]
             deriving (Show)

-- | Cluster statistics data type.
data CStats = CStats
  { csFmem :: Integer -- ^ Cluster free mem
  , csFdsk :: Integer -- ^ Cluster free disk
  , csFspn :: Integer -- ^ Cluster free spindles
  , csAmem :: Integer -- ^ Cluster allocatable mem
  , csAdsk :: Integer -- ^ Cluster allocatable disk
  , csAcpu :: Integer -- ^ Cluster allocatable cpus
  , csMmem :: Integer -- ^ Max node allocatable mem
  , csMdsk :: Integer -- ^ Max node allocatable disk
  , csMcpu :: Integer -- ^ Max node allocatable cpu
  , csImem :: Integer -- ^ Instance used mem
  , csIdsk :: Integer -- ^ Instance used disk
  , csIspn :: Integer -- ^ Instance used spindles
  , csIcpu :: Integer -- ^ Instance used cpu
  , csTmem :: Double  -- ^ Cluster total mem
  , csTdsk :: Double  -- ^ Cluster total disk
  , csTspn :: Double  -- ^ Cluster total spindles
  , csTcpu :: Double  -- ^ Cluster total cpus
  , csVcpu :: Integer -- ^ Cluster total virtual cpus
  , csNcpu :: Double  -- ^ Equivalent to 'csIcpu' but in terms of
                      -- physical CPUs, i.e. normalised used phys CPUs
  , csXmem :: Integer -- ^ Unnacounted for mem
  , csNmem :: Integer -- ^ Node own memory
  , csScore :: Score  -- ^ The cluster score
  , csNinst :: Int    -- ^ The total number of instances
  } deriving (Show)

-- | A simple type for allocation functions.
type AllocMethod =  Node.List           -- ^ Node list
                 -> Instance.List       -- ^ Instance list
                 -> Maybe Int           -- ^ Optional allocation limit
                 -> Instance.Instance   -- ^ Instance spec for allocation
                 -> AllocNodes          -- ^ Which nodes we should allocate on
                 -> [Instance.Instance] -- ^ Allocated instances
                 -> [CStats]            -- ^ Running cluster stats
                 -> Result AllocResult  -- ^ Allocation result

-- | A simple type for the running solution of evacuations.
type EvacInnerState =
  Either String (Node.List, Instance.Instance, Score, Ndx)

-- * Utility functions

-- | Verifies the N+1 status and return the affected nodes.
verifyN1 :: [Node.Node] -> [Node.Node]
verifyN1 = filter Node.failN1

{-| Computes the pair of bad nodes and instances.

The bad node list is computed via a simple 'verifyN1' check, and the
bad instance list is the list of primary and secondary instances of
those nodes.

-}
computeBadItems :: Node.List -> Instance.List ->
                   ([Node.Node], [Instance.Instance])
computeBadItems nl il =
  let bad_nodes = verifyN1 $ getOnline nl
      bad_instances = map (`Container.find` il) .
                      sort . nub $
                      concatMap (\ n -> Node.sList n ++ Node.pList n) bad_nodes
  in
    (bad_nodes, bad_instances)

-- | Extracts the node pairs for an instance. This can fail if the
-- instance is single-homed. FIXME: this needs to be improved,
-- together with the general enhancement for handling non-DRBD moves.
instanceNodes :: Node.List -> Instance.Instance ->
                 (Ndx, Ndx, Node.Node, Node.Node)
instanceNodes nl inst =
  let old_pdx = Instance.pNode inst
      old_sdx = Instance.sNode inst
      old_p = Container.find old_pdx nl
      old_s = Container.find old_sdx nl
  in (old_pdx, old_sdx, old_p, old_s)

-- | Zero-initializer for the CStats type.
emptyCStats :: CStats
emptyCStats = CStats 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0

-- | Update stats with data from a new node.
updateCStats :: CStats -> Node.Node -> CStats
updateCStats cs node =
  let CStats { csFmem = x_fmem, csFdsk = x_fdsk,
               csAmem = x_amem, csAcpu = x_acpu, csAdsk = x_adsk,
               csMmem = x_mmem, csMdsk = x_mdsk, csMcpu = x_mcpu,
               csImem = x_imem, csIdsk = x_idsk, csIcpu = x_icpu,
               csTmem = x_tmem, csTdsk = x_tdsk, csTcpu = x_tcpu,
               csVcpu = x_vcpu, csNcpu = x_ncpu,
               csXmem = x_xmem, csNmem = x_nmem, csNinst = x_ninst,
               csFspn = x_fspn, csIspn = x_ispn, csTspn = x_tspn
             }
        = cs
      inc_amem = Node.fMem node - Node.rMem node
      inc_amem' = if inc_amem > 0 then inc_amem else 0
      inc_adsk = Node.availDisk node
      inc_imem = truncate (Node.tMem node) - Node.nMem node
                 - Node.xMem node - Node.fMem node
      inc_icpu = Node.uCpu node
      inc_idsk = truncate (Node.tDsk node) - Node.fDsk node
      inc_ispn = Node.tSpindles node - Node.fSpindles node
      inc_vcpu = Node.hiCpu node
      inc_acpu = Node.availCpu node
      inc_ncpu = fromIntegral (Node.uCpu node) /
                 iPolicyVcpuRatio (Node.iPolicy node)
  in cs { csFmem = x_fmem + fromIntegral (Node.fMem node)
        , csFdsk = x_fdsk + fromIntegral (Node.fDsk node)
        , csFspn = x_fspn + fromIntegral (Node.fSpindles node)
        , csAmem = x_amem + fromIntegral inc_amem'
        , csAdsk = x_adsk + fromIntegral inc_adsk
        , csAcpu = x_acpu + fromIntegral inc_acpu
        , csMmem = max x_mmem (fromIntegral inc_amem')
        , csMdsk = max x_mdsk (fromIntegral inc_adsk)
        , csMcpu = max x_mcpu (fromIntegral inc_acpu)
        , csImem = x_imem + fromIntegral inc_imem
        , csIdsk = x_idsk + fromIntegral inc_idsk
        , csIspn = x_ispn + fromIntegral inc_ispn
        , csIcpu = x_icpu + fromIntegral inc_icpu
        , csTmem = x_tmem + Node.tMem node
        , csTdsk = x_tdsk + Node.tDsk node
        , csTspn = x_tspn + fromIntegral (Node.tSpindles node)
        , csTcpu = x_tcpu + Node.tCpu node
        , csVcpu = x_vcpu + fromIntegral inc_vcpu
        , csNcpu = x_ncpu + inc_ncpu
        , csXmem = x_xmem + fromIntegral (Node.xMem node)
        , csNmem = x_nmem + fromIntegral (Node.nMem node)
        , csNinst = x_ninst + length (Node.pList node)
        }

-- | Compute the total free disk and memory in the cluster.
totalResources :: Node.List -> CStats
totalResources nl =
  let cs = foldl' updateCStats emptyCStats . Container.elems $ nl
  in cs { csScore = compCV nl }

-- | Compute the delta between two cluster state.
--
-- This is used when doing allocations, to understand better the
-- available cluster resources. The return value is a triple of the
-- current used values, the delta that was still allocated, and what
-- was left unallocated.
computeAllocationDelta :: CStats -> CStats -> AllocStats
computeAllocationDelta cini cfin =
  let CStats {csImem = i_imem, csIdsk = i_idsk, csIcpu = i_icpu,
              csNcpu = i_ncpu, csIspn = i_ispn } = cini
      CStats {csImem = f_imem, csIdsk = f_idsk, csIcpu = f_icpu,
              csTmem = t_mem, csTdsk = t_dsk, csVcpu = f_vcpu,
              csNcpu = f_ncpu, csTcpu = f_tcpu,
              csIspn = f_ispn, csTspn = t_spn } = cfin
      rini = AllocInfo { allocInfoVCpus = fromIntegral i_icpu
                       , allocInfoNCpus = i_ncpu
                       , allocInfoMem   = fromIntegral i_imem
                       , allocInfoDisk  = fromIntegral i_idsk
                       , allocInfoSpn   = fromIntegral i_ispn
                       }
      rfin = AllocInfo { allocInfoVCpus = fromIntegral (f_icpu - i_icpu)
                       , allocInfoNCpus = f_ncpu - i_ncpu
                       , allocInfoMem   = fromIntegral (f_imem - i_imem)
                       , allocInfoDisk  = fromIntegral (f_idsk - i_idsk)
                       , allocInfoSpn   = fromIntegral (f_ispn - i_ispn)
                       }
      runa = AllocInfo { allocInfoVCpus = fromIntegral (f_vcpu - f_icpu)
                       , allocInfoNCpus = f_tcpu - f_ncpu
                       , allocInfoMem   = truncate t_mem - fromIntegral f_imem
                       , allocInfoDisk  = truncate t_dsk - fromIntegral f_idsk
                       , allocInfoSpn   = truncate t_spn - fromIntegral f_ispn
                       }
  in (rini, rfin, runa)

-- | The names and weights of the individual elements in the CV list, together
-- with their statistical accumulation function and a bit to decide whether it
-- is a statistics for online nodes.
detailedCVInfoExt :: [((Double, String), ([Double] -> Statistics, Bool))]
detailedCVInfoExt = [ ((1,  "free_mem_cv"), (getStdDevStatistics, True))
                    , ((1,  "free_disk_cv"), (getStdDevStatistics, True))
                    , ((1,  "n1_cnt"), (getSumStatistics, True))
                    , ((1,  "reserved_mem_cv"), (getStdDevStatistics, True))
                    , ((4,  "offline_all_cnt"), (getSumStatistics, False))
                    , ((16, "offline_pri_cnt"), (getSumStatistics, False))
                    , ((1,  "vcpu_ratio_cv"), (getStdDevStatistics, True))
                    , ((1,  "cpu_load_cv"), (getStdDevStatistics, True))
                    , ((1,  "mem_load_cv"), (getStdDevStatistics, True))
                    , ((1,  "disk_load_cv"), (getStdDevStatistics, True))
                    , ((1,  "net_load_cv"), (getStdDevStatistics, True))
                    , ((2,  "pri_tags_score"), (getSumStatistics, True))
                    , ((1,  "spindles_cv"), (getStdDevStatistics, True))
                    ]

-- | The names and weights of the individual elements in the CV list.
detailedCVInfo :: [(Double, String)]
detailedCVInfo = map fst detailedCVInfoExt

-- | Holds the weights used by 'compCVNodes' for each metric.
detailedCVWeights :: [Double]
detailedCVWeights = map fst detailedCVInfo

-- | The aggregation functions for the weights
detailedCVAggregation :: [([Double] -> Statistics, Bool)]
detailedCVAggregation = map snd detailedCVInfoExt

-- | The bit vector describing which parts of the statistics are
-- for online nodes.
detailedCVOnlineStatus :: [Bool]
detailedCVOnlineStatus = map snd detailedCVAggregation

-- | Compute statistical measures of a single node.
compDetailedCVNode :: Node.Node -> [Double]
compDetailedCVNode node =
  let mem = Node.pMem node
      dsk = Node.pDsk node
      n1 = fromIntegral
           $ if Node.failN1 node
               then length (Node.sList node) + length (Node.pList node)
               else 0
      res = Node.pRem node
      ipri = fromIntegral . length $ Node.pList node
      isec = fromIntegral . length $ Node.sList node
      ioff = ipri + isec
      cpu = Node.pCpuEff node
      DynUtil c1 m1 d1 nn1 = Node.utilLoad node
      DynUtil c2 m2 d2 nn2 = Node.utilPool node
      (c_load, m_load, d_load, n_load) = (c1/c2, m1/m2, d1/d2, nn1/nn2)
      pri_tags = fromIntegral $ Node.conflictingPrimaries node
      spindles = Node.instSpindles node / Node.hiSpindles node
  in [ mem, dsk, n1, res, ioff, ipri, cpu
     , c_load, m_load, d_load, n_load
     , pri_tags, spindles
     ]

-- | Compute the statistics of a cluster.
compClusterStatistics :: [Node.Node] -> [Statistics]
compClusterStatistics all_nodes =
  let (offline, nodes) = partition Node.offline all_nodes
      offline_values = transpose (map compDetailedCVNode offline)
                       ++ repeat []
      -- transpose of an empty list is empty and not k times the empty list, as
      -- would be the transpose of a 0 x k matrix
      online_values = transpose $ map compDetailedCVNode nodes
      aggregate (f, True) (onNodes, _) = f onNodes
      aggregate (f, False) (_, offNodes) = f offNodes
  in zipWith aggregate detailedCVAggregation
       $ zip online_values offline_values

-- | Update a cluster statistics by replacing the contribution of one
-- node by that of another.
updateClusterStatistics :: [Statistics]
                           -> (Node.Node, Node.Node) -> [Statistics]
updateClusterStatistics stats (old, new) =
  let update = zip (compDetailedCVNode old) (compDetailedCVNode new)
      online = not $ Node.offline old
      updateStat forOnline stat upd = if forOnline == online
                                        then updateStatistics stat upd
                                        else stat
  in zipWith3 updateStat detailedCVOnlineStatus stats update

-- | Update a cluster statistics twice.
updateClusterStatisticsTwice :: [Statistics]
                                -> (Node.Node, Node.Node)
                                -> (Node.Node, Node.Node)
                                -> [Statistics]
updateClusterStatisticsTwice s a =
  updateClusterStatistics (updateClusterStatistics s a)

-- | Compute cluster statistics
compDetailedCV :: [Node.Node] -> [Double]
compDetailedCV = map getStatisticValue . compClusterStatistics

-- | Compute the cluster score from its statistics
compCVfromStats :: [Statistics] -> Double
compCVfromStats = sum . zipWith (*) detailedCVWeights . map getStatisticValue

-- | Compute the /total/ variance.
compCVNodes :: [Node.Node] -> Double
compCVNodes = sum . zipWith (*) detailedCVWeights . compDetailedCV

-- | Wrapper over 'compCVNodes' for callers that have a 'Node.List'.
compCV :: Node.List -> Double
compCV = compCVNodes . Container.elems

-- | Compute online nodes from a 'Node.List'.
getOnline :: Node.List -> [Node.Node]
getOnline = filter (not . Node.offline) . Container.elems

-- * Balancing functions

-- | Compute best table. Note that the ordering of the arguments is important.
compareTables :: Table -> Table -> Table
compareTables a@(Table _ _ a_cv _) b@(Table _ _ b_cv _ ) =
  if a_cv > b_cv then b else a

-- | Applies an instance move to a given node list and instance.
applyMoveEx :: Bool -- ^ whether to ignore soft errors
               -> Node.List -> Instance.Instance
               -> IMove -> OpResult (Node.List, Instance.Instance, Ndx, Ndx)
-- Failover (f)
applyMoveEx force nl inst Failover =
  let (old_pdx, old_sdx, old_p, old_s) = instanceNodes nl inst
      int_p = Node.removePri old_p inst
      int_s = Node.removeSec old_s inst
      new_nl = do -- OpResult
        Node.checkMigration old_p old_s
        new_p <- Node.addPriEx (Node.offline old_p || force) int_s inst
        new_s <- Node.addSec int_p inst old_sdx
        let new_inst = Instance.setBoth inst old_sdx old_pdx
        return (Container.addTwo old_pdx new_s old_sdx new_p nl,
                new_inst, old_sdx, old_pdx)
  in new_nl

-- Failover to any (fa)
applyMoveEx force nl inst (FailoverToAny new_pdx) = do
  let (old_pdx, old_sdx, old_pnode, _) = instanceNodes nl inst
      new_pnode = Container.find new_pdx nl
      force_failover = Node.offline old_pnode || force
  Node.checkMigration old_pnode new_pnode
  new_pnode' <- Node.addPriEx force_failover new_pnode inst
  let old_pnode' = Node.removePri old_pnode inst
      inst' = Instance.setPri inst new_pdx
      nl' = Container.addTwo old_pdx old_pnode' new_pdx new_pnode' nl
  return (nl', inst', new_pdx, old_sdx)

-- Replace the primary (f:, r:np, f)
applyMoveEx force nl inst (ReplacePrimary new_pdx) =
  let (old_pdx, old_sdx, old_p, old_s) = instanceNodes nl inst
      tgt_n = Container.find new_pdx nl
      int_p = Node.removePri old_p inst
      int_s = Node.removeSec old_s inst
      force_p = Node.offline old_p || force
      new_nl = do -- OpResult
                  -- check that the current secondary can host the instance
                  -- during the migration
        Node.checkMigration old_p old_s
        Node.checkMigration old_s tgt_n
        tmp_s <- Node.addPriEx force_p int_s inst
        let tmp_s' = Node.removePri tmp_s inst
        new_p <- Node.addPriEx force_p tgt_n inst
        new_s <- Node.addSecEx force_p tmp_s' inst new_pdx
        let new_inst = Instance.setPri inst new_pdx
        return (Container.add new_pdx new_p $
                Container.addTwo old_pdx int_p old_sdx new_s nl,
                new_inst, new_pdx, old_sdx)
  in new_nl

-- Replace the secondary (r:ns)
applyMoveEx force nl inst (ReplaceSecondary new_sdx) =
  let old_pdx = Instance.pNode inst
      old_sdx = Instance.sNode inst
      old_s = Container.find old_sdx nl
      tgt_n = Container.find new_sdx nl
      int_s = Node.removeSec old_s inst
      force_s = Node.offline old_s || force
      new_inst = Instance.setSec inst new_sdx
      new_nl = Node.addSecEx force_s tgt_n inst old_pdx >>=
               \new_s -> return (Container.addTwo new_sdx
                                 new_s old_sdx int_s nl,
                                 new_inst, old_pdx, new_sdx)
  in new_nl

-- Replace the secondary and failover (r:np, f)
applyMoveEx force nl inst (ReplaceAndFailover new_pdx) =
  let (old_pdx, old_sdx, old_p, old_s) = instanceNodes nl inst
      tgt_n = Container.find new_pdx nl
      int_p = Node.removePri old_p inst
      int_s = Node.removeSec old_s inst
      force_s = Node.offline old_s || force
      new_nl = do -- OpResult
        Node.checkMigration old_p tgt_n
        new_p <- Node.addPri tgt_n inst
        new_s <- Node.addSecEx force_s int_p inst new_pdx
        let new_inst = Instance.setBoth inst new_pdx old_pdx
        return (Container.add new_pdx new_p $
                Container.addTwo old_pdx new_s old_sdx int_s nl,
                new_inst, new_pdx, old_pdx)
  in new_nl

-- Failver and replace the secondary (f, r:ns)
applyMoveEx force nl inst (FailoverAndReplace new_sdx) =
  let (old_pdx, old_sdx, old_p, old_s) = instanceNodes nl inst
      tgt_n = Container.find new_sdx nl
      int_p = Node.removePri old_p inst
      int_s = Node.removeSec old_s inst
      force_p = Node.offline old_p || force
      new_nl = do -- OpResult
        Node.checkMigration old_p old_s
        new_p <- Node.addPriEx force_p int_s inst
        new_s <- Node.addSecEx force_p tgt_n inst old_sdx
        let new_inst = Instance.setBoth inst old_sdx new_sdx
        return (Container.add new_sdx new_s $
                Container.addTwo old_sdx new_p old_pdx int_p nl,
                new_inst, old_sdx, new_sdx)
  in new_nl

-- | Applies an instance move to a given node list and instance.
applyMove :: Node.List -> Instance.Instance
          -> IMove -> OpResult (Node.List, Instance.Instance, Ndx, Ndx)
applyMove = applyMoveEx False

-- | Tries to allocate an instance on one given node.
allocateOnSingle :: Node.List -> Instance.Instance -> Ndx
                 -> OpResult Node.AllocElement
allocateOnSingle nl inst new_pdx =
  let p = Container.find new_pdx nl
      new_inst = Instance.setBoth inst new_pdx Node.noSecondary
  in do
    Instance.instMatchesPolicy inst (Node.iPolicy p) (Node.exclStorage p)
    new_p <- Node.addPri p inst
    let new_nl = Container.add new_pdx new_p nl
        new_score = compCV new_nl
    return (new_nl, new_inst, [new_p], new_score)

-- | Tries to allocate an instance on a given pair of nodes.
allocateOnPair :: [Statistics]
               -> Node.List -> Instance.Instance -> Ndx -> Ndx
               -> OpResult Node.AllocElement
allocateOnPair stats nl inst new_pdx new_sdx =
  let tgt_p = Container.find new_pdx nl
      tgt_s = Container.find new_sdx nl
  in do
    Instance.instMatchesPolicy inst (Node.iPolicy tgt_p)
      (Node.exclStorage tgt_p)
    new_p <- Node.addPri tgt_p inst
    new_s <- Node.addSec tgt_s inst new_pdx
    let new_inst = Instance.setBoth inst new_pdx new_sdx
        new_nl = Container.addTwo new_pdx new_p new_sdx new_s nl
        new_stats = updateClusterStatisticsTwice stats
                      (tgt_p, new_p) (tgt_s, new_s)
    return (new_nl, new_inst, [new_p, new_s], compCVfromStats new_stats)

-- | Tries to perform an instance move and returns the best table
-- between the original one and the new one.
checkSingleStep :: Bool -- ^ Whether to unconditionally ignore soft errors
                -> Table -- ^ The original table
                -> Instance.Instance -- ^ The instance to move
                -> Table -- ^ The current best table
                -> IMove -- ^ The move to apply
                -> Table -- ^ The final best table
checkSingleStep force ini_tbl target cur_tbl move =
  let Table ini_nl ini_il _ ini_plc = ini_tbl
      tmp_resu = applyMoveEx force ini_nl target move
  in case tmp_resu of
       Bad _ -> cur_tbl
       Ok (upd_nl, new_inst, pri_idx, sec_idx) ->
         let tgt_idx = Instance.idx target
             upd_cvar = compCV upd_nl
             upd_il = Container.add tgt_idx new_inst ini_il
             upd_plc = (tgt_idx, pri_idx, sec_idx, move, upd_cvar):ini_plc
             upd_tbl = Table upd_nl upd_il upd_cvar upd_plc
         in compareTables cur_tbl upd_tbl

-- | Given the status of the current secondary as a valid new node and
-- the current candidate target node, generate the possible moves for
-- a instance.
possibleMoves :: MirrorType -- ^ The mirroring type of the instance
              -> Bool       -- ^ Whether the secondary node is a valid new node
              -> Bool       -- ^ Whether we can change the primary node
              -> (Bool, Bool) -- ^ Whether migration is restricted and whether
                              -- the instance primary is offline
              -> Ndx        -- ^ Target node candidate
              -> [IMove]    -- ^ List of valid result moves

possibleMoves MirrorNone _ _ _ _ = []

possibleMoves MirrorExternal _ False _  _ = []

possibleMoves MirrorExternal _ True _ tdx =
  [ FailoverToAny tdx ]

possibleMoves MirrorInternal _ False _ tdx =
  [ ReplaceSecondary tdx ]

possibleMoves MirrorInternal _ _ (True, False) tdx =
  [ ReplaceSecondary tdx
  ]

possibleMoves MirrorInternal True True (False, _) tdx =
  [ ReplaceSecondary tdx
  , ReplaceAndFailover tdx
  , ReplacePrimary tdx
  , FailoverAndReplace tdx
  ]

possibleMoves MirrorInternal True True (True, True) tdx =
  [ ReplaceSecondary tdx
  , ReplaceAndFailover tdx
  , FailoverAndReplace tdx
  ]

possibleMoves MirrorInternal False True _ tdx =
  [ ReplaceSecondary tdx
  , ReplaceAndFailover tdx
  ]

-- | Compute the best move for a given instance.
checkInstanceMove ::  AlgorithmOptions -- ^ Algorithmic options for balancing
                  -> [Ndx]             -- ^ Allowed target node indices
                  -> Table             -- ^ Original table
                  -> Instance.Instance -- ^ Instance to move
                  -> Table             -- ^ Best new table for this instance
checkInstanceMove opts nodes_idx ini_tbl@(Table nl _ _ _) target =
  let force = algIgnoreSoftErrors opts
      disk_moves = algDiskMoves opts
      inst_moves = algInstanceMoves opts
      rest_mig = algRestrictedMigration opts
      opdx = Instance.pNode target
      osdx = Instance.sNode target
      bad_nodes = [opdx, osdx]
      nodes = filter (`notElem` bad_nodes) nodes_idx
      mir_type = Instance.mirrorType target
      use_secondary = elem osdx nodes_idx && inst_moves
      aft_failover = if mir_type == MirrorInternal && use_secondary
                       -- if drbd and allowed to failover
                       then checkSingleStep force ini_tbl target ini_tbl
                              Failover
                       else ini_tbl
      primary_drained = Node.offline
                        . flip Container.find nl
                        $ Instance.pNode target
      all_moves =
        if disk_moves
          then concatMap (possibleMoves mir_type use_secondary inst_moves
                          (rest_mig, primary_drained))
               nodes
          else []
    in
      -- iterate over the possible nodes for this instance
      foldl' (checkSingleStep force ini_tbl target) aft_failover all_moves

-- | Compute the best next move.
checkMove :: AlgorithmOptions       -- ^ Algorithmic options for balancing
             -> [Ndx]               -- ^ Allowed target node indices
             -> Table               -- ^ The current solution
             -> [Instance.Instance] -- ^ List of instances still to move
             -> Table               -- ^ The new solution
checkMove opts nodes_idx ini_tbl victims =
  let Table _ _ _ ini_plc = ini_tbl
      -- we're using rwhnf from the Control.Parallel.Strategies
      -- package; we don't need to use rnf as that would force too
      -- much evaluation in single-threaded cases, and in
      -- multi-threaded case the weak head normal form is enough to
      -- spark the evaluation
      tables = parMap rwhnf (checkInstanceMove opts nodes_idx ini_tbl)
               victims
      -- iterate over all instances, computing the best move
      best_tbl = foldl' compareTables ini_tbl tables
      Table _ _ _ best_plc = best_tbl
  in if length best_plc == length ini_plc
       then ini_tbl -- no advancement
       else best_tbl

-- | Check if we are allowed to go deeper in the balancing.
doNextBalance :: Table     -- ^ The starting table
              -> Int       -- ^ Remaining length
              -> Score     -- ^ Score at which to stop
              -> Bool      -- ^ The resulting table and commands
doNextBalance ini_tbl max_rounds min_score =
  let Table _ _ ini_cv ini_plc = ini_tbl
      ini_plc_len = length ini_plc
  in (max_rounds < 0 || ini_plc_len < max_rounds) && ini_cv > min_score

-- | Run a balance move.
tryBalance :: AlgorithmOptions  -- ^ Algorithmic options for balancing
              -> Table          -- ^ The starting table
              -> Maybe Table    -- ^ The resulting table and commands
tryBalance opts ini_tbl =
    let evac_mode = algEvacMode opts
        mg_limit = algMinGainLimit opts
        min_gain = algMinGain opts
        Table ini_nl ini_il ini_cv _ = ini_tbl
        all_inst = Container.elems ini_il
        all_nodes = Container.elems ini_nl
        (offline_nodes, online_nodes) = partition Node.offline all_nodes
        all_inst' = if evac_mode
                      then let bad_nodes = map Node.idx offline_nodes
                           in filter (any (`elem` bad_nodes) .
                                          Instance.allNodes) all_inst
                      else all_inst
        reloc_inst = filter (\i -> Instance.movable i &&
                                   Instance.autoBalance i) all_inst'
        node_idx = map Node.idx online_nodes
        fin_tbl = checkMove opts node_idx ini_tbl reloc_inst
        (Table _ _ fin_cv _) = fin_tbl
    in
      if fin_cv < ini_cv && (ini_cv > mg_limit || ini_cv - fin_cv >= min_gain)
      then Just fin_tbl -- this round made success, return the new table
      else Nothing

-- * Allocation functions

-- | Build failure stats out of a list of failures.
collapseFailures :: [FailMode] -> FailStats
collapseFailures flst =
    map (\k -> (k, foldl' (\a e -> if e == k then a + 1 else a) 0 flst))
            [minBound..maxBound]

-- | Compares two Maybe AllocElement and chooses the best score.
bestAllocElement :: Maybe Node.AllocElement
                 -> Maybe Node.AllocElement
                 -> Maybe Node.AllocElement
bestAllocElement a Nothing = a
bestAllocElement Nothing b = b
bestAllocElement a@(Just (_, _, _, ascore)) b@(Just (_, _, _, bscore)) =
  if ascore < bscore then a else b

-- | Update current Allocation solution and failure stats with new
-- elements.
concatAllocs :: AllocSolution -> OpResult Node.AllocElement -> AllocSolution
concatAllocs as (Bad reason) = as { asFailures = reason : asFailures as }

concatAllocs as (Ok ns) =
  let -- Choose the old or new solution, based on the cluster score
    cntok = asAllocs as
    osols = asSolution as
    nsols = bestAllocElement osols (Just ns)
    nsuc = cntok + 1
    -- Note: we force evaluation of nsols here in order to keep the
    -- memory profile low - we know that we will need nsols for sure
    -- in the next cycle, so we force evaluation of nsols, since the
    -- foldl' in the caller will only evaluate the tuple, but not the
    -- elements of the tuple
  in nsols `seq` nsuc `seq` as { asAllocs = nsuc, asSolution = nsols }

-- | Sums two 'AllocSolution' structures.
sumAllocs :: AllocSolution -> AllocSolution -> AllocSolution
sumAllocs (AllocSolution aFails aAllocs aSols aLog)
          (AllocSolution bFails bAllocs bSols bLog) =
  -- note: we add b first, since usually it will be smaller; when
  -- fold'ing, a will grow and grow whereas b is the per-group
  -- result, hence smaller
  let nFails  = bFails ++ aFails
      nAllocs = aAllocs + bAllocs
      nSols   = bestAllocElement aSols bSols
      nLog    = bLog ++ aLog
  in AllocSolution nFails nAllocs nSols nLog

-- | Given a solution, generates a reasonable description for it.
describeSolution :: AllocSolution -> String
describeSolution as =
  let fcnt = asFailures as
      sols = asSolution as
      freasons =
        intercalate ", " . map (\(a, b) -> printf "%s: %d" (show a) b) .
        filter ((> 0) . snd) . collapseFailures $ fcnt
  in case sols of
     Nothing -> "No valid allocation solutions, failure reasons: " ++
                (if null fcnt then "unknown reasons" else freasons)
     Just (_, _, nodes, cv) ->
         printf ("score: %.8f, successes %d, failures %d (%s)" ++
                 " for node(s) %s") cv (asAllocs as) (length fcnt) freasons
               (intercalate "/" . map Node.name $ nodes)

-- | Annotates a solution with the appropriate string.
annotateSolution :: AllocSolution -> AllocSolution
annotateSolution as = as { asLog = describeSolution as : asLog as }

-- | Reverses an evacuation solution.
--
-- Rationale: we always concat the results to the top of the lists, so
-- for proper jobset execution, we should reverse all lists.
reverseEvacSolution :: EvacSolution -> EvacSolution
reverseEvacSolution (EvacSolution f m o) =
  EvacSolution (reverse f) (reverse m) (reverse o)

-- | Generate the valid node allocation singles or pairs for a new instance.
genAllocNodes :: Group.List        -- ^ Group list
              -> Node.List         -- ^ The node map
              -> Int               -- ^ The number of nodes required
              -> Bool              -- ^ Whether to drop or not
                                   -- unallocable nodes
              -> Result AllocNodes -- ^ The (monadic) result
genAllocNodes gl nl count drop_unalloc =
  let filter_fn = if drop_unalloc
                    then filter (Group.isAllocable .
                                 flip Container.find gl . Node.group)
                    else id
      all_nodes = filter_fn $ getOnline nl
      all_pairs = [(Node.idx p,
                    [Node.idx s | s <- all_nodes,
                                       Node.idx p /= Node.idx s,
                                       Node.group p == Node.group s]) |
                   p <- all_nodes]
  in case count of
       1 -> Ok (Left (map Node.idx all_nodes))
       2 -> Ok (Right (filter (not . null . snd) all_pairs))
       _ -> Bad "Unsupported number of nodes, only one or two  supported"

-- | Try to allocate an instance on the cluster.
tryAlloc :: (Monad m) =>
            Node.List         -- ^ The node list
         -> Instance.List     -- ^ The instance list
         -> Instance.Instance -- ^ The instance to allocate
         -> AllocNodes        -- ^ The allocation targets
         -> m AllocSolution   -- ^ Possible solution list
tryAlloc _  _ _    (Right []) = fail "Not enough online nodes"
tryAlloc nl _ inst (Right ok_pairs) =
  let cstat = compClusterStatistics $ Container.elems nl
      psols = parMap rwhnf (\(p, ss) ->
                              foldl' (\cstate ->
                                        concatAllocs cstate .
                                        allocateOnPair cstat nl inst p)
                              emptyAllocSolution ss) ok_pairs
      sols = foldl' sumAllocs emptyAllocSolution psols
  in return $ annotateSolution sols

tryAlloc _  _ _    (Left []) = fail "No online nodes"
tryAlloc nl _ inst (Left all_nodes) =
  let sols = foldl' (\cstate ->
                       concatAllocs cstate . allocateOnSingle nl inst
                    ) emptyAllocSolution all_nodes
  in return $ annotateSolution sols

-- | Given a group/result, describe it as a nice (list of) messages.
solutionDescription :: (Group.Group, Result AllocSolution)
                    -> [String]
solutionDescription (grp, result) =
  case result of
    Ok solution -> map (printf "Group %s (%s): %s" gname pol) (asLog solution)
    Bad message -> [printf "Group %s: error %s" gname message]
  where gname = Group.name grp
        pol = allocPolicyToRaw (Group.allocPolicy grp)

-- | From a list of possibly bad and possibly empty solutions, filter
-- only the groups with a valid result. Note that the result will be
-- reversed compared to the original list.
filterMGResults :: [(Group.Group, Result AllocSolution)]
                -> [(Group.Group, AllocSolution)]
filterMGResults = foldl' fn []
  where unallocable = not . Group.isAllocable
        fn accu (grp, rasol) =
          case rasol of
            Bad _ -> accu
            Ok sol | isNothing (asSolution sol) -> accu
                   | unallocable grp -> accu
                   | otherwise -> (grp, sol):accu

-- | Sort multigroup results based on policy and score.
sortMGResults :: [(Group.Group, AllocSolution)]
              -> [(Group.Group, AllocSolution)]
sortMGResults sols =
  let extractScore (_, _, _, x) = x
      solScore (grp, sol) = (Group.allocPolicy grp,
                             (extractScore . fromJust . asSolution) sol)
  in sortBy (comparing solScore) sols

-- | Determines if a group is connected to the networks required by the
-- | instance.
hasRequiredNetworks :: Group.Group -> Instance.Instance -> Bool
hasRequiredNetworks ng = all hasNetwork . Instance.nics
  where hasNetwork = maybe True (`elem` Group.networks ng) . Nic.network

-- | Removes node groups which can't accommodate the instance
filterValidGroups :: [(Group.Group, (Node.List, Instance.List))]
                  -> Instance.Instance
                  -> ([(Group.Group, (Node.List, Instance.List))], [String])
filterValidGroups [] _ = ([], [])
filterValidGroups (ng:ngs) inst =
  let (valid_ngs, msgs) = filterValidGroups ngs inst
  in if hasRequiredNetworks (fst ng) inst
      then (ng:valid_ngs, msgs)
      else (valid_ngs,
            ("group " ++ Group.name (fst ng) ++
             " is not connected to a network required by instance " ++
             Instance.name inst):msgs)

-- | Finds an allocation solution for an instance on a group
findAllocation :: Group.List           -- ^ The group list
               -> Node.List            -- ^ The node list
               -> Instance.List        -- ^ The instance list
               -> Gdx                  -- ^ The group to allocate to
               -> Instance.Instance    -- ^ The instance to allocate
               -> Int                  -- ^ Required number of nodes
               -> Result (AllocSolution, [String])
findAllocation mggl mgnl mgil gdx inst cnt = do
  let belongsTo nl' nidx = nidx `elem` map Node.idx (Container.elems nl')
      nl = Container.filter ((== gdx) . Node.group) mgnl
      il = Container.filter (belongsTo nl . Instance.pNode) mgil
      group' = Container.find gdx mggl
  unless (hasRequiredNetworks group' inst) . failError
         $ "The group " ++ Group.name group' ++ " is not connected to\
           \ a network required by instance " ++ Instance.name inst
  solution <- genAllocNodes mggl nl cnt False >>= tryAlloc nl il inst
  return (solution, solutionDescription (group', return solution))

-- | Finds the best group for an instance on a multi-group cluster.
--
-- Only solutions in @preferred@ and @last_resort@ groups will be
-- accepted as valid, and additionally if the allowed groups parameter
-- is not null then allocation will only be run for those group
-- indices.
findBestAllocGroup :: Group.List           -- ^ The group list
                   -> Node.List            -- ^ The node list
                   -> Instance.List        -- ^ The instance list
                   -> Maybe [Gdx]          -- ^ The allowed groups
                   -> Instance.Instance    -- ^ The instance to allocate
                   -> Int                  -- ^ Required number of nodes
                   -> Result (Group.Group, AllocSolution, [String])
findBestAllocGroup mggl mgnl mgil allowed_gdxs inst cnt =
  let groups_by_idx = splitCluster mgnl mgil
      groups = map (\(gid, d) -> (Container.find gid mggl, d)) groups_by_idx
      groups' = maybe groups
                (\gs -> filter ((`elem` gs) . Group.idx . fst) groups)
                allowed_gdxs
      (groups'', filter_group_msgs) = filterValidGroups groups' inst
      sols = map (\(gr, (nl, il)) ->
                   (gr, genAllocNodes mggl nl cnt False >>=
                        tryAlloc nl il inst))
             groups''::[(Group.Group, Result AllocSolution)]
      all_msgs = filter_group_msgs ++ concatMap solutionDescription sols
      goodSols = filterMGResults sols
      sortedSols = sortMGResults goodSols
  in case sortedSols of
       [] -> Bad $ if null groups'
                     then "no groups for evacuation: allowed groups was" ++
                          show allowed_gdxs ++ ", all groups: " ++
                          show (map fst groups)
                     else intercalate ", " all_msgs
       (final_group, final_sol):_ -> return (final_group, final_sol, all_msgs)

-- | Try to allocate an instance on a multi-group cluster.
tryMGAlloc :: Group.List           -- ^ The group list
           -> Node.List            -- ^ The node list
           -> Instance.List        -- ^ The instance list
           -> Instance.Instance    -- ^ The instance to allocate
           -> Int                  -- ^ Required number of nodes
           -> Result AllocSolution -- ^ Possible solution list
tryMGAlloc mggl mgnl mgil inst cnt = do
  (best_group, solution, all_msgs) <-
      findBestAllocGroup mggl mgnl mgil Nothing inst cnt
  let group_name = Group.name best_group
      selmsg = "Selected group: " ++ group_name
  return $ solution { asLog = selmsg:all_msgs }

-- | Try to allocate an instance to a group.
tryGroupAlloc :: Group.List           -- ^ The group list
              -> Node.List            -- ^ The node list
              -> Instance.List        -- ^ The instance list
              -> String               -- ^ The allocation group (name)
              -> Instance.Instance    -- ^ The instance to allocate
              -> Int                  -- ^ Required number of nodes
              -> Result AllocSolution -- ^ Solution
tryGroupAlloc mggl mgnl ngil gn inst cnt = do
  gdx <- Group.idx <$> Container.findByName mggl gn
  (solution, msgs) <- findAllocation mggl mgnl ngil gdx inst cnt
  return $ solution { asLog = msgs }

-- | Calculate the new instance list after allocation solution.
updateIl :: Instance.List           -- ^ The original instance list
         -> Maybe Node.AllocElement -- ^ The result of the allocation attempt
         -> Instance.List           -- ^ The updated instance list
updateIl il Nothing = il
updateIl il (Just (_, xi, _, _)) = Container.add (Container.size il) xi il

-- | Extract the the new node list from the allocation solution.
extractNl :: Node.List               -- ^ The original node list
          -> Maybe Node.AllocElement -- ^ The result of the allocation attempt
          -> Node.List               -- ^ The new node list
extractNl nl Nothing = nl
extractNl _ (Just (xnl, _, _, _)) = xnl

-- | Try to allocate a list of instances on a multi-group cluster.
allocList :: Group.List                                -- ^ The group list
          -> Node.List                                 -- ^ The node list
          -> Instance.List                             -- ^ The instance list
          -> [(Instance.Instance, AllocDetails)]       -- ^ The instance to
                                                       --   allocate
          -> AllocSolutionList                         -- ^ Possible solution
                                                       --   list
          -> Result (Node.List, Instance.List,
                     AllocSolutionList)                -- ^ The final solution
                                                       --   list
allocList _  nl il [] result = Ok (nl, il, result)
allocList gl nl il ((xi, AllocDetails xicnt mgn):xies) result = do
  ares <- case mgn of
    Nothing -> tryMGAlloc gl nl il xi xicnt
    Just gn -> tryGroupAlloc gl nl il gn xi xicnt
  let sol = asSolution ares
      nl' = extractNl nl sol
      il' = updateIl il sol
  allocList gl nl' il' xies ((xi, ares):result)

-- | Function which fails if the requested mode is change secondary.
--
-- This is useful since except DRBD, no other disk template can
-- execute change secondary; thus, we can just call this function
-- instead of always checking for secondary mode. After the call to
-- this function, whatever mode we have is just a primary change.
failOnSecondaryChange :: (Monad m) => EvacMode -> DiskTemplate -> m ()
failOnSecondaryChange ChangeSecondary dt =
  fail $ "Instances with disk template '" ++ diskTemplateToRaw dt ++
         "' can't execute change secondary"
failOnSecondaryChange _ _ = return ()

-- | Run evacuation for a single instance.
--
-- /Note:/ this function should correctly execute both intra-group
-- evacuations (in all modes) and inter-group evacuations (in the
-- 'ChangeAll' mode). Of course, this requires that the correct list
-- of target nodes is passed.
nodeEvacInstance :: AlgorithmOptions
                 -> Node.List         -- ^ The node list (cluster-wide)
                 -> Instance.List     -- ^ Instance list (cluster-wide)
                 -> EvacMode          -- ^ The evacuation mode
                 -> Instance.Instance -- ^ The instance to be evacuated
                 -> Gdx               -- ^ The group we're targetting
                 -> [Ndx]             -- ^ The list of available nodes
                                      -- for allocation
                 -> Result (Node.List, Instance.List, [OpCodes.OpCode])
nodeEvacInstance opts nl il mode inst@(Instance.Instance
                                    {Instance.diskTemplate = dt@DTDiskless})
                 gdx avail_nodes =
                   failOnSecondaryChange mode dt >>
                   evacOneNodeOnly opts nl il inst gdx avail_nodes

nodeEvacInstance _ _ _ _ (Instance.Instance
                          {Instance.diskTemplate = DTPlain}) _ _ =
                  fail "Instances of type plain cannot be relocated"

nodeEvacInstance _ _ _ _ (Instance.Instance
                          {Instance.diskTemplate = DTFile}) _ _ =
                  fail "Instances of type file cannot be relocated"

nodeEvacInstance opts nl il mode inst@(Instance.Instance
                                    {Instance.diskTemplate = dt@DTSharedFile})
                 gdx avail_nodes =
                   failOnSecondaryChange mode dt >>
                   evacOneNodeOnly opts nl il inst gdx avail_nodes

nodeEvacInstance opts nl il mode inst@(Instance.Instance
                                    {Instance.diskTemplate = dt@DTBlock})
                 gdx avail_nodes =
                   failOnSecondaryChange mode dt >>
                   evacOneNodeOnly opts nl il inst gdx avail_nodes

nodeEvacInstance opts nl il mode inst@(Instance.Instance
                                    {Instance.diskTemplate = dt@DTRbd})
                 gdx avail_nodes =
                   failOnSecondaryChange mode dt >>
                   evacOneNodeOnly opts nl il inst gdx avail_nodes

nodeEvacInstance opts nl il mode inst@(Instance.Instance
                                    {Instance.diskTemplate = dt@DTExt})
                 gdx avail_nodes =
                   failOnSecondaryChange mode dt >>
                   evacOneNodeOnly opts nl il inst gdx avail_nodes

nodeEvacInstance opts nl il mode inst@(Instance.Instance
                                    {Instance.diskTemplate = dt@DTGluster})
                 gdx avail_nodes =
                   failOnSecondaryChange mode dt >>
                   evacOneNodeOnly opts nl il inst gdx avail_nodes

nodeEvacInstance _ nl il ChangePrimary
                 inst@(Instance.Instance {Instance.diskTemplate = DTDrbd8})
                 _ _ =
  do
    (nl', inst', _, _) <- opToResult $ applyMove nl inst Failover
    let idx = Instance.idx inst
        il' = Container.add idx inst' il
        ops = iMoveToJob nl' il' idx Failover
    return (nl', il', ops)

nodeEvacInstance opts nl il ChangeSecondary
                 inst@(Instance.Instance {Instance.diskTemplate = DTDrbd8})
                 gdx avail_nodes =
  evacOneNodeOnly opts nl il inst gdx avail_nodes

-- The algorithm for ChangeAll is as follows:
--
-- * generate all (primary, secondary) node pairs for the target groups
-- * for each pair, execute the needed moves (r:s, f, r:s) and compute
--   the final node list state and group score
-- * select the best choice via a foldl that uses the same Either
--   String solution as the ChangeSecondary mode
nodeEvacInstance opts nl il ChangeAll
                 inst@(Instance.Instance {Instance.diskTemplate = DTDrbd8})
                 gdx avail_nodes =
  do
    let no_nodes = Left "no nodes available"
        node_pairs = [(p,s) | p <- avail_nodes, s <- avail_nodes, p /= s]
    (nl', il', ops, _) <-
        annotateResult "Can't find any good nodes for relocation" .
        eitherToResult $
        foldl'
        (\accu nodes -> case evacDrbdAllInner opts nl il inst gdx nodes of
                          Bad msg ->
                              case accu of
                                Right _ -> accu
                                -- we don't need more details (which
                                -- nodes, etc.) as we only selected
                                -- this group if we can allocate on
                                -- it, hence failures will not
                                -- propagate out of this fold loop
                                Left _ -> Left $ "Allocation failed: " ++ msg
                          Ok result@(_, _, _, new_cv) ->
                              let new_accu = Right result in
                              case accu of
                                Left _ -> new_accu
                                Right (_, _, _, old_cv) ->
                                    if old_cv < new_cv
                                    then accu
                                    else new_accu
        ) no_nodes node_pairs

    return (nl', il', ops)

-- | Generic function for changing one node of an instance.
--
-- This is similar to 'nodeEvacInstance' but will be used in a few of
-- its sub-patterns. It folds the inner function 'evacOneNodeInner'
-- over the list of available nodes, which results in the best choice
-- for relocation.
evacOneNodeOnly :: AlgorithmOptions
                -> Node.List         -- ^ The node list (cluster-wide)
                -> Instance.List     -- ^ Instance list (cluster-wide)
                -> Instance.Instance -- ^ The instance to be evacuated
                -> Gdx               -- ^ The group we're targetting
                -> [Ndx]             -- ^ The list of available nodes
                                      -- for allocation
                -> Result (Node.List, Instance.List, [OpCodes.OpCode])
evacOneNodeOnly opts nl il inst gdx avail_nodes = do
  op_fn <- case Instance.mirrorType inst of
             MirrorNone -> Bad "Can't relocate/evacuate non-mirrored instances"
             MirrorInternal -> Ok ReplaceSecondary
             MirrorExternal -> Ok FailoverToAny
  (nl', inst', _, ndx) <- annotateResult "Can't find any good node" .
                          eitherToResult $
                          foldl' (evacOneNodeInner opts nl inst gdx op_fn)
                          (Left "") avail_nodes
  let idx = Instance.idx inst
      il' = Container.add idx inst' il
      ops = iMoveToJob nl' il' idx (op_fn ndx)
  return (nl', il', ops)

-- | Inner fold function for changing one node of an instance.
--
-- Depending on the instance disk template, this will either change
-- the secondary (for DRBD) or the primary node (for shared
-- storage). However, the operation is generic otherwise.
--
-- The running solution is either a @Left String@, which means we
-- don't have yet a working solution, or a @Right (...)@, which
-- represents a valid solution; it holds the modified node list, the
-- modified instance (after evacuation), the score of that solution,
-- and the new secondary node index.
evacOneNodeInner :: AlgorithmOptions
                 -> Node.List         -- ^ Cluster node list
                 -> Instance.Instance -- ^ Instance being evacuated
                 -> Gdx               -- ^ The group index of the instance
                 -> (Ndx -> IMove)    -- ^ Operation constructor
                 -> EvacInnerState    -- ^ Current best solution
                 -> Ndx               -- ^ Node we're evaluating as target
                 -> EvacInnerState    -- ^ New best solution
evacOneNodeInner opts nl inst gdx op_fn accu ndx =
  case applyMoveEx (algIgnoreSoftErrors opts) nl inst (op_fn ndx) of
    Bad fm -> let fail_msg = " Node " ++ Container.nameOf nl ndx ++
                             " failed: " ++ show fm ++ ";"
              in either (Left . (++ fail_msg)) Right accu
    Ok (nl', inst', _, _) ->
      let nodes = Container.elems nl'
          -- The fromJust below is ugly (it can fail nastily), but
          -- at this point we should have any internal mismatches,
          -- and adding a monad here would be quite involved
          grpnodes = fromJust (gdx `lookup` Node.computeGroups nodes)
          new_cv = compCVNodes grpnodes
          new_accu = Right (nl', inst', new_cv, ndx)
      in case accu of
           Left _ -> new_accu
           Right (_, _, old_cv, _) ->
             if old_cv < new_cv
               then accu
               else new_accu

-- | Compute result of changing all nodes of a DRBD instance.
--
-- Given the target primary and secondary node (which might be in a
-- different group or not), this function will 'execute' all the
-- required steps and assuming all operations succceed, will return
-- the modified node and instance lists, the opcodes needed for this
-- and the new group score.
evacDrbdAllInner :: AlgorithmOptions
                 -> Node.List         -- ^ Cluster node list
                 -> Instance.List     -- ^ Cluster instance list
                 -> Instance.Instance -- ^ The instance to be moved
                 -> Gdx               -- ^ The target group index
                                      -- (which can differ from the
                                      -- current group of the
                                      -- instance)
                 -> (Ndx, Ndx)        -- ^ Tuple of new
                                      -- primary\/secondary nodes
                 -> Result (Node.List, Instance.List, [OpCodes.OpCode], Score)
evacDrbdAllInner opts nl il inst gdx (t_pdx, t_sdx) = do
  let primary = Container.find (Instance.pNode inst) nl
      idx = Instance.idx inst
      apMove = applyMoveEx $ algIgnoreSoftErrors opts
  -- if the primary is offline, then we first failover
  (nl1, inst1, ops1) <-
    if Node.offline primary
      then do
        (nl', inst', _, _) <-
          annotateResult "Failing over to the secondary" .
          opToResult $ apMove nl inst Failover
        return (nl', inst', [Failover])
      else return (nl, inst, [])
  let (o1, o2, o3) = (ReplaceSecondary t_pdx,
                      Failover,
                      ReplaceSecondary t_sdx)
  -- we now need to execute a replace secondary to the future
  -- primary node
  (nl2, inst2, _, _) <-
    annotateResult "Changing secondary to new primary" .
    opToResult $
    apMove nl1 inst1 o1
  let ops2 = o1:ops1
  -- we now execute another failover, the primary stays fixed now
  (nl3, inst3, _, _) <- annotateResult "Failing over to new primary" .
                        opToResult $ apMove nl2 inst2 o2
  let ops3 = o2:ops2
  -- and finally another replace secondary, to the final secondary
  (nl4, inst4, _, _) <-
    annotateResult "Changing secondary to final secondary" .
    opToResult $
    apMove nl3 inst3 o3
  let ops4 = o3:ops3
      il' = Container.add idx inst4 il
      ops = concatMap (iMoveToJob nl4 il' idx) $ reverse ops4
  let nodes = Container.elems nl4
      -- The fromJust below is ugly (it can fail nastily), but
      -- at this point we should have any internal mismatches,
      -- and adding a monad here would be quite involved
      grpnodes = fromJust (gdx `lookup` Node.computeGroups nodes)
      new_cv = compCVNodes grpnodes
  return (nl4, il', ops, new_cv)

-- | Computes the nodes in a given group which are available for
-- allocation.
availableGroupNodes :: [(Gdx, [Ndx])] -- ^ Group index/node index assoc list
                    -> IntSet.IntSet  -- ^ Nodes that are excluded
                    -> Gdx            -- ^ The group for which we
                                      -- query the nodes
                    -> Result [Ndx]   -- ^ List of available node indices
availableGroupNodes group_nodes excl_ndx gdx = do
  local_nodes <- maybe (Bad $ "Can't find group with index " ++ show gdx)
                 Ok (lookup gdx group_nodes)
  let avail_nodes = filter (not . flip IntSet.member excl_ndx) local_nodes
  return avail_nodes

-- | Updates the evac solution with the results of an instance
-- evacuation.
updateEvacSolution :: (Node.List, Instance.List, EvacSolution)
                   -> Idx
                   -> Result (Node.List, Instance.List, [OpCodes.OpCode])
                   -> (Node.List, Instance.List, EvacSolution)
updateEvacSolution (nl, il, es) idx (Bad msg) =
  (nl, il, es { esFailed = (idx, msg):esFailed es})
updateEvacSolution (_, _, es) idx (Ok (nl, il, opcodes)) =
  (nl, il, es { esMoved = new_elem:esMoved es
              , esOpCodes = opcodes:esOpCodes es })
    where inst = Container.find idx il
          new_elem = (idx,
                      instancePriGroup nl inst,
                      Instance.allNodes inst)

-- | Node-evacuation IAllocator mode main function.
tryNodeEvac :: AlgorithmOptions
            -> Group.List    -- ^ The cluster groups
            -> Node.List     -- ^ The node list (cluster-wide, not per group)
            -> Instance.List -- ^ Instance list (cluster-wide)
            -> EvacMode      -- ^ The evacuation mode
            -> [Idx]         -- ^ List of instance (indices) to be evacuated
            -> Result (Node.List, Instance.List, EvacSolution)
tryNodeEvac opts _ ini_nl ini_il mode idxs =
  let evac_ndx = nodesToEvacuate ini_il mode idxs
      offline = map Node.idx . filter Node.offline $ Container.elems ini_nl
      excl_ndx = foldl' (flip IntSet.insert) evac_ndx offline
      group_ndx = map (\(gdx, (nl, _)) -> (gdx, map Node.idx
                                           (Container.elems nl))) $
                  splitCluster ini_nl ini_il
      (fin_nl, fin_il, esol) =
        foldl' (\state@(nl, il, _) inst ->
                  let gdx = instancePriGroup nl inst
                      pdx = Instance.pNode inst in
                  updateEvacSolution state (Instance.idx inst) $
                  availableGroupNodes group_ndx
                    (IntSet.insert pdx excl_ndx) gdx >>=
                      nodeEvacInstance opts nl il mode inst gdx
               )
        (ini_nl, ini_il, emptyEvacSolution)
        (map (`Container.find` ini_il) idxs)
  in return (fin_nl, fin_il, reverseEvacSolution esol)

-- | Change-group IAllocator mode main function.
--
-- This is very similar to 'tryNodeEvac', the only difference is that
-- we don't choose as target group the current instance group, but
-- instead:
--
--   1. at the start of the function, we compute which are the target
--   groups; either no groups were passed in, in which case we choose
--   all groups out of which we don't evacuate instance, or there were
--   some groups passed, in which case we use those
--
--   2. for each instance, we use 'findBestAllocGroup' to choose the
--   best group to hold the instance, and then we do what
--   'tryNodeEvac' does, except for this group instead of the current
--   instance group.
--
-- Note that the correct behaviour of this function relies on the
-- function 'nodeEvacInstance' to be able to do correctly both
-- intra-group and inter-group moves when passed the 'ChangeAll' mode.
tryChangeGroup :: Group.List    -- ^ The cluster groups
               -> Node.List     -- ^ The node list (cluster-wide)
               -> Instance.List -- ^ Instance list (cluster-wide)
               -> [Gdx]         -- ^ Target groups; if empty, any
                                -- groups not being evacuated
               -> [Idx]         -- ^ List of instance (indices) to be evacuated
               -> Result (Node.List, Instance.List, EvacSolution)
tryChangeGroup gl ini_nl ini_il gdxs idxs =
  let evac_gdxs = nub $ map (instancePriGroup ini_nl .
                             flip Container.find ini_il) idxs
      target_gdxs = (if null gdxs
                       then Container.keys gl
                       else gdxs) \\ evac_gdxs
      offline = map Node.idx . filter Node.offline $ Container.elems ini_nl
      excl_ndx = foldl' (flip IntSet.insert) IntSet.empty offline
      group_ndx = map (\(gdx, (nl, _)) -> (gdx, map Node.idx
                                           (Container.elems nl))) $
                  splitCluster ini_nl ini_il
      (fin_nl, fin_il, esol) =
        foldl' (\state@(nl, il, _) inst ->
                  let solution = do
                        let ncnt = Instance.requiredNodes $
                                   Instance.diskTemplate inst
                        (grp, _, _) <- findBestAllocGroup gl nl il
                                       (Just target_gdxs) inst ncnt
                        let gdx = Group.idx grp
                        av_nodes <- availableGroupNodes group_ndx
                                    excl_ndx gdx
                        nodeEvacInstance defaultOptions
                                         nl il ChangeAll inst gdx av_nodes
                  in updateEvacSolution state (Instance.idx inst) solution
               )
        (ini_nl, ini_il, emptyEvacSolution)
        (map (`Container.find` ini_il) idxs)
  in return (fin_nl, fin_il, reverseEvacSolution esol)

-- | Standard-sized allocation method.
--
-- This places instances of the same size on the cluster until we're
-- out of space. The result will be a list of identically-sized
-- instances.
iterateAlloc :: AllocMethod
iterateAlloc nl il limit newinst allocnodes ixes cstats =
  let depth = length ixes
      newname = printf "new-%d" depth::String
      newidx = Container.size il
      newi2 = Instance.setIdx (Instance.setName newinst newname) newidx
      newlimit = fmap (flip (-) 1) limit
  in case tryAlloc nl il newi2 allocnodes of
       Bad s -> Bad s
       Ok (AllocSolution { asFailures = errs, asSolution = sols3 }) ->
         let newsol = Ok (collapseFailures errs, nl, il, ixes, cstats) in
         case sols3 of
           Nothing -> newsol
           Just (xnl, xi, _, _) ->
             if limit == Just 0
               then newsol
               else iterateAlloc xnl (Container.add newidx xi il)
                      newlimit newinst allocnodes (xi:ixes)
                      (totalResources xnl:cstats)

-- | Predicate whether shrinking a single resource can lead to a valid
-- allocation.
sufficesShrinking :: (Instance.Instance -> AllocSolution) -> Instance.Instance
                     -> FailMode  -> Maybe Instance.Instance
sufficesShrinking allocFn inst fm =
  case dropWhile (isNothing . asSolution . fst)
       . takeWhile (liftA2 (||) (elem fm . asFailures . fst)
                                (isJust . asSolution . fst))
       . map (allocFn &&& id) $
       iterateOk (`Instance.shrinkByType` fm) inst
  of x:_ -> Just . snd $ x
     _ -> Nothing

-- | Tiered allocation method.
--
-- This places instances on the cluster, and decreases the spec until
-- we can allocate again. The result will be a list of decreasing
-- instance specs.
tieredAlloc :: AllocMethod
tieredAlloc nl il limit newinst allocnodes ixes cstats =
  case iterateAlloc nl il limit newinst allocnodes ixes cstats of
    Bad s -> Bad s
    Ok (errs, nl', il', ixes', cstats') ->
      let newsol = Ok (errs, nl', il', ixes', cstats')
          ixes_cnt = length ixes'
          (stop, newlimit) = case limit of
                               Nothing -> (False, Nothing)
                               Just n -> (n <= ixes_cnt,
                                            Just (n - ixes_cnt))
          sortedErrs = map fst $ sortBy (comparing snd) errs
          suffShrink = sufficesShrinking (fromMaybe emptyAllocSolution
                                          . flip (tryAlloc nl' il') allocnodes)
                       newinst
          bigSteps = filter isJust . map suffShrink . reverse $ sortedErrs
          progress (Ok (_, _, _, newil', _)) (Ok (_, _, _, newil, _)) =
            length newil' > length newil
          progress _ _ = False
      in if stop then newsol else
           let newsol' = case Instance.shrinkByType newinst . last
                                $ sortedErrs of
                 Bad _ -> newsol
                 Ok newinst' -> tieredAlloc nl' il' newlimit
                                newinst' allocnodes ixes' cstats'
           in if progress newsol' newsol then newsol' else
                case bigSteps of
                  Just newinst':_ -> tieredAlloc nl' il' newlimit
                                     newinst' allocnodes ixes' cstats'
                  _ -> newsol

-- * Formatting functions

-- | Given the original and final nodes, computes the relocation description.
computeMoves :: Instance.Instance -- ^ The instance to be moved
             -> String -- ^ The instance name
             -> IMove  -- ^ The move being performed
             -> String -- ^ New primary
             -> String -- ^ New secondary
             -> (String, [String])
                -- ^ Tuple of moves and commands list; moves is containing
                -- either @/f/@ for failover or @/r:name/@ for replace
                -- secondary, while the command list holds gnt-instance
                -- commands (without that prefix), e.g \"@failover instance1@\"
computeMoves i inam mv c d =
  case mv of
    Failover -> ("f", [mig])
    FailoverToAny _ -> (printf "fa:%s" c, [mig_any])
    FailoverAndReplace _ -> (printf "f r:%s" d, [mig, rep d])
    ReplaceSecondary _ -> (printf "r:%s" d, [rep d])
    ReplaceAndFailover _ -> (printf "r:%s f" c, [rep c, mig])
    ReplacePrimary _ -> (printf "f r:%s f" c, [mig, rep c, mig])
  where morf = if Instance.isRunning i then "migrate" else "failover"
        mig = printf "%s -f %s" morf inam::String
        mig_any = printf "%s -f -n %s %s" morf c inam::String
        rep n = printf "replace-disks -n %s %s" n inam::String

-- | Converts a placement to string format.
printSolutionLine :: Node.List     -- ^ The node list
                  -> Instance.List -- ^ The instance list
                  -> Int           -- ^ Maximum node name length
                  -> Int           -- ^ Maximum instance name length
                  -> Placement     -- ^ The current placement
                  -> Int           -- ^ The index of the placement in
                                   -- the solution
                  -> (String, [String])
printSolutionLine nl il nmlen imlen plc pos =
  let pmlen = (2*nmlen + 1)
      (i, p, s, mv, c) = plc
      old_sec = Instance.sNode inst
      inst = Container.find i il
      inam = Instance.alias inst
      npri = Node.alias $ Container.find p nl
      nsec = Node.alias $ Container.find s nl
      opri = Node.alias $ Container.find (Instance.pNode inst) nl
      osec = Node.alias $ Container.find old_sec nl
      (moves, cmds) =  computeMoves inst inam mv npri nsec
      -- FIXME: this should check instead/also the disk template
      ostr = if old_sec == Node.noSecondary
               then printf "%s" opri::String
               else printf "%s:%s" opri osec::String
      nstr = if s == Node.noSecondary
               then printf "%s" npri::String
               else printf "%s:%s" npri nsec::String
  in (printf "  %3d. %-*s %-*s => %-*s %12.8f a=%s"
      pos imlen inam pmlen ostr pmlen nstr c moves,
      cmds)

-- | Return the instance and involved nodes in an instance move.
--
-- Note that the output list length can vary, and is not required nor
-- guaranteed to be of any specific length.
involvedNodes :: Instance.List -- ^ Instance list, used for retrieving
                               -- the instance from its index; note
                               -- that this /must/ be the original
                               -- instance list, so that we can
                               -- retrieve the old nodes
              -> Placement     -- ^ The placement we're investigating,
                               -- containing the new nodes and
                               -- instance index
              -> [Ndx]         -- ^ Resulting list of node indices
involvedNodes il plc =
  let (i, np, ns, _, _) = plc
      inst = Container.find i il
  in nub . filter (>= 0) $ [np, ns] ++ Instance.allNodes inst

-- | From two adjacent cluster tables get the list of moves that transitions
-- from to the other
getMoves :: (Table, Table) -> [MoveJob]
getMoves (Table _ initial_il _ initial_plc, Table final_nl _ _ final_plc) =
  let
    plctoMoves (plc@(idx, p, s, mv, _)) =
      let inst = Container.find idx initial_il
          inst_name = Instance.name inst
          affected = involvedNodes initial_il plc
          np = Node.alias $ Container.find p final_nl
          ns = Node.alias $ Container.find s final_nl
          (_, cmds) = computeMoves inst inst_name mv np ns
      in (affected, idx, mv, cmds)
  in map plctoMoves . reverse . drop (length initial_plc) $ reverse final_plc
             
-- | Inner function for splitJobs, that either appends the next job to
-- the current jobset, or starts a new jobset.
mergeJobs :: ([JobSet], [Ndx]) -> MoveJob -> ([JobSet], [Ndx])
mergeJobs ([], _) n@(ndx, _, _, _) = ([[n]], ndx)
mergeJobs (cjs@(j:js), nbuf) n@(ndx, _, _, _)
  | null (ndx `intersect` nbuf) = ((n:j):js, ndx ++ nbuf)
  | otherwise = ([n]:cjs, ndx)

-- | Break a list of moves into independent groups. Note that this
-- will reverse the order of jobs.
splitJobs :: [MoveJob] -> [JobSet]
splitJobs = fst . foldl mergeJobs ([], [])

-- | Given a list of commands, prefix them with @gnt-instance@ and
-- also beautify the display a little.
formatJob :: Int -> Int -> (Int, MoveJob) -> [String]
formatJob jsn jsl (sn, (_, _, _, cmds)) =
  let out =
        printf "  echo job %d/%d" jsn sn:
        printf "  check":
        map ("  gnt-instance " ++) cmds
  in if sn == 1
       then ["", printf "echo jobset %d, %d jobs" jsn jsl] ++ out
       else out

-- | Given a list of commands, prefix them with @gnt-instance@ and
-- also beautify the display a little.
formatCmds :: [JobSet] -> String
formatCmds =
  unlines .
  concatMap (\(jsn, js) -> concatMap (formatJob jsn (length js))
                           (zip [1..] js)) .
  zip [1..]

-- | Print the node list.
printNodes :: Node.List -> [String] -> String
printNodes nl fs =
  let fields = case fs of
                 [] -> Node.defaultFields
                 "+":rest -> Node.defaultFields ++ rest
                 _ -> fs
      snl = sortBy (comparing Node.idx) (Container.elems nl)
      (header, isnum) = unzip $ map Node.showHeader fields
  in printTable "" header (map (Node.list fields) snl) isnum

-- | Print the instance list.
printInsts :: Node.List -> Instance.List -> String
printInsts nl il =
  let sil = sortBy (comparing Instance.idx) (Container.elems il)
      helper inst = [ if Instance.isRunning inst then "R" else " "
                    , Instance.name inst
                    , Container.nameOf nl (Instance.pNode inst)
                    , let sdx = Instance.sNode inst
                      in if sdx == Node.noSecondary
                           then  ""
                           else Container.nameOf nl sdx
                    , if Instance.autoBalance inst then "Y" else "N"
                    , printf "%3d" $ Instance.vcpus inst
                    , printf "%5d" $ Instance.mem inst
                    , printf "%5d" $ Instance.dsk inst `div` 1024
                    , printf "%5.3f" lC
                    , printf "%5.3f" lM
                    , printf "%5.3f" lD
                    , printf "%5.3f" lN
                    ]
          where DynUtil lC lM lD lN = Instance.util inst
      header = [ "F", "Name", "Pri_node", "Sec_node", "Auto_bal"
               , "vcpu", "mem" , "dsk", "lCpu", "lMem", "lDsk", "lNet" ]
      isnum = False:False:False:False:False:repeat True
  in printTable "" header (map helper sil) isnum

-- | Shows statistics for a given node list.
printStats :: String -> Node.List -> String
printStats lp nl =
  let dcvs = compDetailedCV $ Container.elems nl
      (weights, names) = unzip detailedCVInfo
      hd = zip3 (weights ++ repeat 1) (names ++ repeat "unknown") dcvs
      header = [ "Field", "Value", "Weight" ]
      formatted = map (\(w, h, val) ->
                         [ h
                         , printf "%.8f" val
                         , printf "x%.2f" w
                         ]) hd
  in printTable lp header formatted $ False:repeat True

-- | Convert a placement into a list of OpCodes (basically a job).
iMoveToJob :: Node.List        -- ^ The node list; only used for node
                               -- names, so any version is good
                               -- (before or after the operation)
           -> Instance.List    -- ^ The instance list; also used for
                               -- names only
           -> Idx              -- ^ The index of the instance being
                               -- moved
           -> IMove            -- ^ The actual move to be described
           -> [OpCodes.OpCode] -- ^ The list of opcodes equivalent to
                               -- the given move
iMoveToJob nl il idx move =
  let inst = Container.find idx il
      iname = Instance.name inst
      lookNode  n = case mkNonEmpty (Container.nameOf nl n) of
                      -- FIXME: convert htools codebase to non-empty strings
                      Bad msg -> error $ "Empty node name for idx " ++
                                 show n ++ ": " ++ msg ++ "??"
                      Ok ne -> Just ne
      opF = OpCodes.OpInstanceMigrate
              { OpCodes.opInstanceName        = iname
              , OpCodes.opInstanceUuid        = Nothing
              , OpCodes.opMigrationMode       = Nothing -- default
              , OpCodes.opOldLiveMode         = Nothing -- default as well
              , OpCodes.opTargetNode          = Nothing -- this is drbd
              , OpCodes.opTargetNodeUuid      = Nothing
              , OpCodes.opAllowRuntimeChanges = False
              , OpCodes.opIgnoreIpolicy       = False
              , OpCodes.opMigrationCleanup    = False
              , OpCodes.opIallocator          = Nothing
              , OpCodes.opAllowFailover       = True
              , OpCodes.opIgnoreHvversions    = True
              }
      opFA n = opF { OpCodes.opTargetNode = lookNode n } -- not drbd
      opR n = OpCodes.OpInstanceReplaceDisks
                { OpCodes.opInstanceName     = iname
                , OpCodes.opInstanceUuid     = Nothing
                , OpCodes.opEarlyRelease     = False
                , OpCodes.opIgnoreIpolicy    = False
                , OpCodes.opReplaceDisksMode = OpCodes.ReplaceNewSecondary
                , OpCodes.opReplaceDisksList = []
                , OpCodes.opRemoteNode       = lookNode n
                , OpCodes.opRemoteNodeUuid   = Nothing
                , OpCodes.opIallocator       = Nothing
                }
  in case move of
       Failover -> [ opF ]
       FailoverToAny np -> [ opFA np ]
       ReplacePrimary np -> [ opF, opR np, opF ]
       ReplaceSecondary ns -> [ opR ns ]
       ReplaceAndFailover np -> [ opR np, opF ]
       FailoverAndReplace ns -> [ opF, opR ns ]

-- * Node group functions

-- | Computes the group of an instance.
instanceGroup :: Node.List -> Instance.Instance -> Result Gdx
instanceGroup nl i =
  let sidx = Instance.sNode i
      pnode = Container.find (Instance.pNode i) nl
      snode = if sidx == Node.noSecondary
              then pnode
              else Container.find sidx nl
      pgroup = Node.group pnode
      sgroup = Node.group snode
  in if pgroup /= sgroup
       then fail ("Instance placed accross two node groups, primary " ++
                  show pgroup ++ ", secondary " ++ show sgroup)
       else return pgroup

-- | Computes the group of an instance per the primary node.
instancePriGroup :: Node.List -> Instance.Instance -> Gdx
instancePriGroup nl i =
  let pnode = Container.find (Instance.pNode i) nl
  in  Node.group pnode

-- | Compute the list of badly allocated instances (split across node
-- groups).
findSplitInstances :: Node.List -> Instance.List -> [Instance.Instance]
findSplitInstances nl =
  filter (not . isOk . instanceGroup nl) . Container.elems

-- | Splits a cluster into the component node groups.
splitCluster :: Node.List -> Instance.List ->
                [(Gdx, (Node.List, Instance.List))]
splitCluster nl il =
  let ngroups = Node.computeGroups (Container.elems nl)
  in map (\(gdx, nodes) ->
           let nidxs = map Node.idx nodes
               nodes' = zip nidxs nodes
               instances = Container.filter ((`elem` nidxs) . Instance.pNode) il
           in (gdx, (Container.fromList nodes', instances))) ngroups

-- | Compute the list of nodes that are to be evacuated, given a list
-- of instances and an evacuation mode.
nodesToEvacuate :: Instance.List -- ^ The cluster-wide instance list
                -> EvacMode      -- ^ The evacuation mode we're using
                -> [Idx]         -- ^ List of instance indices being evacuated
                -> IntSet.IntSet -- ^ Set of node indices
nodesToEvacuate il mode =
  IntSet.delete Node.noSecondary .
  foldl' (\ns idx ->
            let i = Container.find idx il
                pdx = Instance.pNode i
                sdx = Instance.sNode i
                dt = Instance.diskTemplate i
                withSecondary = case dt of
                                  DTDrbd8 -> IntSet.insert sdx ns
                                  _ -> ns
            in case mode of
                 ChangePrimary   -> IntSet.insert pdx ns
                 ChangeSecondary -> withSecondary
                 ChangeAll       -> IntSet.insert pdx withSecondary
         ) IntSet.empty

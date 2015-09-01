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
  , Table(..)
  , CStats(..)
  , AllocNodes
  , AllocResult
  , AllocMethod
  , GenericAllocSolutionList
  , AllocSolutionList
  -- * Generic functions
  , totalResources
  , computeAllocationDelta
  , hasRequiredNetworks
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
  , iMoveToJob
  -- * IAllocator functions
  , genAllocNodes
  , tryAlloc
  , tryGroupAlloc
  , tryMGAlloc
  , filterMGResults
  , sortMGResults
  , tryChangeGroup
  , allocList
  -- * Allocation functions
  , iterateAlloc
  , tieredAlloc
  -- * Node group functions
  , instanceGroup
  , findSplitInstances
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
import Ganeti.HTools.Cluster.AllocatePrimitives ( allocateOnSingle
                                                , allocateOnPair)
import Ganeti.HTools.Cluster.AllocationSolution
    ( GenericAllocSolution(..) , AllocSolution, emptyAllocSolution
    , sumAllocs, extractNl, updateIl
    , annotateSolution, solutionDescription, collapseFailures
    , emptyAllocCollection, concatAllocCollections, collectionToSolution )
import Ganeti.HTools.Cluster.Evacuate ( EvacSolution(..), emptyEvacSolution
                                      , updateEvacSolution, reverseEvacSolution
                                      , nodeEvacInstance)
import Ganeti.HTools.Cluster.Metrics (compCV, compClusterStatistics)
import Ganeti.HTools.Cluster.Moves (applyMoveEx)
import Ganeti.HTools.Cluster.Utils (splitCluster, instancePriGroup
                                   , availableGroupNodes, iMoveToJob)
import Ganeti.HTools.GlobalN1 (allocGlobalN1, redundant)
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Nic as Nic
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group
import Ganeti.HTools.Types
import Ganeti.Compat
import Ganeti.Utils
import Ganeti.Types (EvacMode(..))

-- * Types

-- | Allocation details for an instance, specifying
-- required number of nodes, and
-- an optional group (name) to allocate to
data AllocDetails = AllocDetails Int (Maybe String)
                    deriving (Show)

-- | Allocation results, as used in 'iterateAlloc' and 'tieredAlloc'.
type AllocResult = (FailStats, Node.List, Instance.List,
                    [Instance.Instance], [CStats])

-- | Type alias for easier handling.
type GenericAllocSolutionList a =
  [(Instance.Instance, GenericAllocSolution a)]
type AllocSolutionList = GenericAllocSolutionList Score

-- | A type denoting the valid allocation mode/pairs.
--
-- For a one-node allocation, this will be a @Left ['Ndx']@, whereas
-- for a two-node allocation, this will be a @Right [('Ndx',
-- ['Ndx'])]@. In the latter case, the list is basically an
-- association list, grouped by primary node and holding the potential
-- secondary nodes in the sub-list.
type AllocNodes = Either [Ndx] [(Ndx, [Ndx])]

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

-- | Compute online nodes from a 'Node.List'.
getOnline :: Node.List -> [Node.Node]
getOnline = filter (not . Node.offline) . Container.elems

-- * Balancing functions

-- | Compute best table. Note that the ordering of the arguments is important.
compareTables :: Table -> Table -> Table
compareTables a@(Table _ _ a_cv _) b@(Table _ _ b_cv _ ) =
  if a_cv > b_cv then b else a

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
              -> Bool       -- ^ Whether we alowed to move disks
              -> (Bool, Bool) -- ^ Whether migration is restricted and whether
                              -- the instance primary is offline
              -> Ndx        -- ^ Target node candidate
              -> [IMove]    -- ^ List of valid result moves

possibleMoves MirrorNone _ _ _ _ _ = []

possibleMoves MirrorExternal _ False _ _ _ = []

possibleMoves MirrorExternal _ True _ _ tdx =
  [ FailoverToAny tdx ]

possibleMoves MirrorInternal _ _ False _ _ = []

possibleMoves MirrorInternal _ False True _ tdx =
  [ ReplaceSecondary tdx ]

possibleMoves MirrorInternal _ _ True (True, False) tdx =
  [ ReplaceSecondary tdx
  ]

possibleMoves MirrorInternal True True True (False, _) tdx =
  [ ReplaceSecondary tdx
  , ReplaceAndFailover tdx
  , ReplacePrimary tdx
  , FailoverAndReplace tdx
  ]

possibleMoves MirrorInternal True True True (True, True) tdx =
  [ ReplaceSecondary tdx
  , ReplaceAndFailover tdx
  , FailoverAndReplace tdx
  ]

possibleMoves MirrorInternal False True True _ tdx =
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
      all_moves = concatMap (possibleMoves mir_type use_secondary inst_moves
                             disk_moves (rest_mig, primary_drained)) nodes
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

-- | Generate the valid node allocation singles or pairs for a new instance.
genAllocNodes :: AlgorithmOptions  -- ^ algorithmic options to honor
              -> Group.List        -- ^ Group list
              -> Node.List         -- ^ The node map
              -> Int               -- ^ The number of nodes required
              -> Bool              -- ^ Whether to drop or not
                                   -- unallocable nodes
              -> Result AllocNodes -- ^ The (monadic) result
genAllocNodes opts gl nl count drop_unalloc =
  let filter_fn = if drop_unalloc
                    then filter (Group.isAllocable .
                                 flip Container.find gl . Node.group)
                    else id
      restrict_fn = maybe id (\ns -> filter (flip elem ns . Node.name))
                    $ algRestrictToNodes opts
      all_nodes = restrict_fn . filter_fn $ getOnline nl
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
            AlgorithmOptions
         -> Node.List         -- ^ The node list
         -> Instance.List     -- ^ The instance list
         -> Instance.Instance -- ^ The instance to allocate
         -> AllocNodes        -- ^ The allocation targets
         -> m AllocSolution   -- ^ Possible solution list
tryAlloc _ _  _ _    (Right []) = fail "Not enough online nodes"
tryAlloc opts nl il inst (Right ok_pairs) =
  let cstat = compClusterStatistics $ Container.elems nl
      n1pred = if algCapacity opts
                 then allocGlobalN1 opts nl il
                 else const True
      psols = parMap rwhnf (\(p, ss) ->
                              collectionToSolution FailN1 n1pred $
                              foldl (\cstate ->
                                      concatAllocCollections cstate
                                      . allocateOnPair opts cstat nl inst p)
                              emptyAllocCollection ss) ok_pairs
      sols = foldl' sumAllocs emptyAllocSolution psols
  in return $ annotateSolution sols

tryAlloc _ _  _ _    (Left []) = fail "No online nodes"
tryAlloc opts nl il inst (Left all_nodes) =
  let sols = foldl (\cstate ->
                       concatAllocCollections cstate
                       . allocateOnSingle opts nl inst
                   ) emptyAllocCollection all_nodes
      n1pred = if algCapacity opts
                 then allocGlobalN1 opts nl il
                 else const True
  in return . annotateSolution
       $ collectionToSolution FailN1 n1pred sols

-- | From a list of possibly bad and possibly empty solutions, filter
-- only the groups with a valid result. Note that the result will be
-- reversed compared to the original list.
filterMGResults :: [(Group.Group, Result (GenericAllocSolution a))]
                -> [(Group.Group, GenericAllocSolution a)]
filterMGResults = foldl' fn []
  where unallocable = not . Group.isAllocable
        fn accu (grp, rasol) =
          case rasol of
            Bad _ -> accu
            Ok sol | isNothing (asSolution sol) -> accu
                   | unallocable grp -> accu
                   | otherwise -> (grp, sol):accu

-- | Sort multigroup results based on policy and score.
sortMGResults :: Ord a
              => [(Group.Group, GenericAllocSolution a)]
              -> [(Group.Group, GenericAllocSolution a)]
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
findAllocation :: AlgorithmOptions
               -> Group.List           -- ^ The group list
               -> Node.List            -- ^ The node list
               -> Instance.List        -- ^ The instance list
               -> Gdx                  -- ^ The group to allocate to
               -> Instance.Instance    -- ^ The instance to allocate
               -> Int                  -- ^ Required number of nodes
               -> Result (AllocSolution, [String])
findAllocation opts mggl mgnl mgil gdx inst cnt = do
  let belongsTo nl' nidx = nidx `elem` map Node.idx (Container.elems nl')
      nl = Container.filter ((== gdx) . Node.group) mgnl
      il = Container.filter (belongsTo nl . Instance.pNode) mgil
      group' = Container.find gdx mggl
  unless (hasRequiredNetworks group' inst) . failError
         $ "The group " ++ Group.name group' ++ " is not connected to\
           \ a network required by instance " ++ Instance.name inst
  solution <- genAllocNodes opts mggl nl cnt False >>= tryAlloc opts nl il inst
  return (solution, solutionDescription (group', return solution))

-- | Finds the best group for an instance on a multi-group cluster.
--
-- Only solutions in @preferred@ and @last_resort@ groups will be
-- accepted as valid, and additionally if the allowed groups parameter
-- is not null then allocation will only be run for those group
-- indices.
findBestAllocGroup :: AlgorithmOptions
                   -> Group.List           -- ^ The group list
                   -> Node.List            -- ^ The node list
                   -> Instance.List        -- ^ The instance list
                   -> Maybe [Gdx]          -- ^ The allowed groups
                   -> Instance.Instance    -- ^ The instance to allocate
                   -> Int                  -- ^ Required number of nodes
                   -> Result (Group.Group, AllocSolution, [String])
findBestAllocGroup opts mggl mgnl mgil allowed_gdxs inst cnt =
  let groups_by_idx = splitCluster mgnl mgil
      groups = map (\(gid, d) -> (Container.find gid mggl, d)) groups_by_idx
      groups' = maybe groups
                (\gs -> filter ((`elem` gs) . Group.idx . fst) groups)
                allowed_gdxs
      (groups'', filter_group_msgs) = filterValidGroups groups' inst
      sols = map (\(gr, (nl, _)) ->
                   (gr, genAllocNodes opts mggl nl cnt False >>=
                        tryAlloc opts mgnl mgil inst))
             groups''::[(Group.Group, Result AllocSolution)]
      all_msgs = filter_group_msgs ++ concatMap solutionDescription sols
      goodSols = filterMGResults sols
      sortedSols = sortMGResults goodSols
  in case sortedSols of
       [] -> Bad $ if null groups'
                     then "no groups for evacuation: allowed groups was " ++
                          show allowed_gdxs ++ ", all groups: " ++
                          show (map fst groups)
                     else intercalate ", " all_msgs
       (final_group, final_sol):_ -> return (final_group, final_sol, all_msgs)

-- | Try to allocate an instance on a multi-group cluster.
tryMGAlloc :: AlgorithmOptions
           -> Group.List           -- ^ The group list
           -> Node.List            -- ^ The node list
           -> Instance.List        -- ^ The instance list
           -> Instance.Instance    -- ^ The instance to allocate
           -> Int                  -- ^ Required number of nodes
           -> Result AllocSolution -- ^ Possible solution list
tryMGAlloc opts mggl mgnl mgil inst cnt = do
  (best_group, solution, all_msgs) <-
      findBestAllocGroup opts mggl mgnl mgil Nothing inst cnt
  let group_name = Group.name best_group
      selmsg = "Selected group: " ++ group_name
  return $ solution { asLog = selmsg:all_msgs }

-- | Try to allocate an instance to a group.
tryGroupAlloc :: AlgorithmOptions
              -> Group.List           -- ^ The group list
              -> Node.List            -- ^ The node list
              -> Instance.List        -- ^ The instance list
              -> String               -- ^ The allocation group (name)
              -> Instance.Instance    -- ^ The instance to allocate
              -> Int                  -- ^ Required number of nodes
              -> Result AllocSolution -- ^ Solution
tryGroupAlloc opts mggl mgnl ngil gn inst cnt = do
  gdx <- Group.idx <$> Container.findByName mggl gn
  (solution, msgs) <- findAllocation opts mggl mgnl ngil gdx inst cnt
  return $ solution { asLog = msgs }


-- | Try to allocate a list of instances on a multi-group cluster.
allocList :: AlgorithmOptions
          -> Group.List                                -- ^ The group list
          -> Node.List                                 -- ^ The node list
          -> Instance.List                             -- ^ The instance list
          -> [(Instance.Instance, AllocDetails)]       -- ^ The instance to
                                                       --   allocate
          -> AllocSolutionList                         -- ^ Possible solution
                                                       --   list
          -> Result (Node.List, Instance.List,
                     AllocSolutionList)                -- ^ The final solution
                                                       --   list
allocList _ _  nl il [] result = Ok (nl, il, result)
allocList opts gl nl il ((xi, AllocDetails xicnt mgn):xies) result = do
  ares <- case mgn of
    Nothing -> tryMGAlloc opts gl nl il xi xicnt
    Just gn -> tryGroupAlloc opts gl nl il gn xi xicnt
  let sol = asSolution ares
      nl' = extractNl nl il sol
      il' = updateIl il sol
  allocList opts gl nl' il' xies ((xi, ares):result)



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
tryChangeGroup :: AlgorithmOptions
               -> Group.List    -- ^ The cluster groups
               -> Node.List     -- ^ The node list (cluster-wide)
               -> Instance.List -- ^ Instance list (cluster-wide)
               -> [Gdx]         -- ^ Target groups; if empty, any
                                -- groups not being evacuated
               -> [Idx]         -- ^ List of instance (indices) to be evacuated
               -> Result (Node.List, Instance.List, EvacSolution)
tryChangeGroup opts gl ini_nl ini_il gdxs idxs =
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
                        (grp, _, _) <- findBestAllocGroup opts gl nl il
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
iterateAllocSmallStep :: AlgorithmOptions -> AllocMethod
iterateAllocSmallStep opts nl il limit newinst allocnodes ixes cstats =
  let depth = length ixes
      newname = printf "new-%d" depth::String
      newidx = Container.size il
      newi2 = Instance.setIdx (Instance.setName newinst newname) newidx
      newlimit = fmap (flip (-) 1) limit
      opts' = if Instance.diskTemplate newi2 == DTDrbd8
                then opts { algCapacity = False }
                else opts
  in case tryAlloc opts' nl il newi2 allocnodes of
       Bad s -> Bad s
       Ok (AllocSolution { asFailures = errs, asSolution = sols3 }) ->
         let newsol = Ok (collapseFailures errs, nl, il, ixes, cstats) in
         case sols3 of
           Nothing -> newsol
           Just (xnl, xi, _, _) ->
             if limit == Just 0
               then newsol
               else iterateAllocSmallStep opts xnl (Container.add newidx xi il)
                      newlimit newinst allocnodes (xi:ixes)
                      (totalResources xnl:cstats)

-- | Guess a number of machines worth trying to put on the cluster in one step.
-- The goal is to guess a number close to the actual capacity of the cluster but
-- preferrably not bigger, unless it is quite small (as we don't want to do
-- big steps smaller than 10).
guessBigstepSize :: Node.List -> Instance.Instance -> Int
guessBigstepSize nl inst =
  let nodes = Container.elems nl
      totalUnusedMemory = sum $ map Node.fMem nodes
      reserved = round . maximum $ map Node.tMem nodes
      capacity = (totalUnusedMemory - reserved) `div` Instance.mem inst
      -- however, at every node we might lose almost an instance if it just
      -- doesn't fit by a tiny margin
      guess = capacity - Container.size nl
  in if guess < 20 then 20 else guess

-- | A speed-up version of `iterateAllocSmallStep`.
--
-- This function returns precisely the same result as `iterateAllocSmallStep`.
-- However the computation is speed up by the following heuristic: allocate
-- a group of instances iteratively without considering global N+1 redundancy;
-- if the result of this is globally N+1 redundant, then everything was OK
-- inbetween and we can continue from there. Only if that fails, do a
-- step-by-step iterative allocation.
-- In order to further speed up the computation while keeping it robust, we
-- first try (if the first argument is True) a number of steps guessed from
-- the node capacity, then, if that failed, a fixed step size and only as last
-- restort step-by-step iterative allocation.
iterateAlloc' :: Bool -> AlgorithmOptions -> AllocMethod
iterateAlloc' tryHugestep opts nl il limit newinst allocnodes ixes cstats =
  if not $ algCapacity opts
    then iterateAllocSmallStep opts nl il limit newinst allocnodes ixes cstats
    else let bigstepsize = if tryHugestep
                             then guessBigstepSize nl newinst
                             else 10
             (limit', newlimit) = maybe (Just bigstepsize, Nothing)
                                    (Just . min bigstepsize
                                     &&& Just . max 0 . flip (-) bigstepsize)
                                    limit
             opts' = opts { algCapacity = False }
         in case iterateAllocSmallStep opts' nl il limit'
                                       newinst allocnodes ixes cstats of
            Bad s -> Bad s
            Ok res@(_, nl', il', ixes', cstats') | redundant opts nl' il' ->
              if newlimit == Just 0 || length ixes' == length ixes
                then return res
                else iterateAlloc' tryHugestep opts nl' il' newlimit newinst
                                   allocnodes ixes' cstats'
            _ -> if tryHugestep
                   then iterateAlloc' False opts nl il limit newinst allocnodes
                                      ixes cstats
                   else iterateAllocSmallStep opts nl il limit newinst
                                              allocnodes ixes cstats

-- | A speed-up version of `iterateAllocSmallStep`.
iterateAlloc :: AlgorithmOptions -> AllocMethod
iterateAlloc = iterateAlloc' True

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
tieredAlloc :: AlgorithmOptions -> AllocMethod
tieredAlloc opts nl il limit newinst allocnodes ixes cstats =
  case iterateAlloc opts nl il limit newinst allocnodes ixes cstats of
    Bad s -> Bad s
    Ok (errs, nl', il', ixes', cstats') ->
      let newsol = Ok (errs, nl', il', ixes', cstats')
          ixes_cnt = length ixes'
          (stop, newlimit) = case limit of
                               Nothing -> (False, Nothing)
                               Just n -> (n <= ixes_cnt,
                                            Just (n - ixes_cnt))
          sortedErrs = map fst $ sortBy (comparing snd) errs
          suffShrink = sufficesShrinking
                         (fromMaybe emptyAllocSolution
                          . flip (tryAlloc opts nl' il') allocnodes)
                       newinst
          bigSteps = filter isJust . map suffShrink . reverse $ sortedErrs
          progress (Ok (_, _, _, newil', _)) (Ok (_, _, _, newil, _)) =
            length newil' > length newil
          progress _ _ = False
      in if stop then newsol else
           let newsol' = case Instance.shrinkByType newinst . last
                                $ sortedErrs of
                 Bad _ -> newsol
                 Ok newinst' -> tieredAlloc opts nl' il' newlimit
                                newinst' allocnodes ixes' cstats'
           in if progress newsol' newsol then newsol' else
                case bigSteps of
                  Just newinst':_ -> tieredAlloc opts nl' il' newlimit
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

-- | Compute the list of badly allocated instances (split across node
-- groups).
findSplitInstances :: Node.List -> Instance.List -> [Instance.Instance]
findSplitInstances nl =
  filter (not . isOk . instanceGroup nl) . Container.elems

{-| Implementation of cluster-wide logic.

This module holds all pure cluster-logic; I\/O related functionality
goes into the "Main" module for the individual binaries.

-}

{-

Copyright (C) 2009 Google Inc.

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

module Ganeti.HTools.Cluster
    (
     -- * Types
      AllocSolution
    , Table(..)
    , CStats(..)
    -- * Generic functions
    , totalResources
    -- * First phase functions
    , computeBadItems
    -- * Second phase functions
    , printSolution
    , printSolutionLine
    , formatCmds
    , involvedNodes
    , splitJobs
    -- * Display functions
    , printNodes
    , printInsts
    -- * Balacing functions
    , checkMove
    , doNextBalance
    , tryBalance
    , compCV
    , printStats
    , iMoveToJob
    -- * IAllocator functions
    , tryAlloc
    , tryReloc
    , collapseFailures
    ) where

import Data.List
import Text.Printf (printf)
import Data.Function
import Control.Monad

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types
import Ganeti.HTools.Utils
import qualified Ganeti.OpCodes as OpCodes

-- * Types

-- | Allocation\/relocation solution.
type AllocSolution = ([FailMode], Int, Maybe (Score, AllocElement))

-- | Allocation\/relocation element.
type AllocElement = (Node.List, Instance.Instance, [Node.Node])

-- | The complete state for the balancing solution
data Table = Table Node.List Instance.List Score [Placement]
             deriving (Show)

data CStats = CStats { csFmem :: Int    -- ^ Cluster free mem
                     , csFdsk :: Int    -- ^ Cluster free disk
                     , csAmem :: Int    -- ^ Cluster allocatable mem
                     , csAdsk :: Int    -- ^ Cluster allocatable disk
                     , csAcpu :: Int    -- ^ Cluster allocatable cpus
                     , csMmem :: Int    -- ^ Max node allocatable mem
                     , csMdsk :: Int    -- ^ Max node allocatable disk
                     , csMcpu :: Int    -- ^ Max node allocatable cpu
                     , csImem :: Int    -- ^ Instance used mem
                     , csIdsk :: Int    -- ^ Instance used disk
                     , csIcpu :: Int    -- ^ Instance used cpu
                     , csTmem :: Double -- ^ Cluster total mem
                     , csTdsk :: Double -- ^ Cluster total disk
                     , csTcpu :: Double -- ^ Cluster total cpus
                     , csXmem :: Int    -- ^ Unnacounted for mem
                     , csNmem :: Int    -- ^ Node own memory
                     , csScore :: Score -- ^ The cluster score
                     , csNinst :: Int   -- ^ The total number of instances
                     }

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
      bad_instances = map (\idx -> Container.find idx il) .
                      sort . nub $
                      concatMap (\ n -> Node.sList n ++ Node.pList n) bad_nodes
  in
    (bad_nodes, bad_instances)

-- | Zero-initializer for the CStats type
emptyCStats :: CStats
emptyCStats = CStats 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0

-- | Update stats with data from a new node
updateCStats :: CStats -> Node.Node -> CStats
updateCStats cs node =
    let CStats { csFmem = x_fmem, csFdsk = x_fdsk,
                 csAmem = x_amem, csAcpu = x_acpu, csAdsk = x_adsk,
                 csMmem = x_mmem, csMdsk = x_mdsk, csMcpu = x_mcpu,
                 csImem = x_imem, csIdsk = x_idsk, csIcpu = x_icpu,
                 csTmem = x_tmem, csTdsk = x_tdsk, csTcpu = x_tcpu,
                 csXmem = x_xmem, csNmem = x_nmem, csNinst = x_ninst
               }
            = cs
        inc_amem = Node.fMem node - Node.rMem node
        inc_amem' = if inc_amem > 0 then inc_amem else 0
        inc_adsk = Node.availDisk node
        inc_imem = truncate (Node.tMem node) - Node.nMem node
                   - Node.xMem node - Node.fMem node
        inc_icpu = Node.uCpu node
        inc_idsk = truncate (Node.tDsk node) - Node.fDsk node

    in cs { csFmem = x_fmem + Node.fMem node
          , csFdsk = x_fdsk + Node.fDsk node
          , csAmem = x_amem + inc_amem'
          , csAdsk = x_adsk + inc_adsk
          , csAcpu = x_acpu
          , csMmem = max x_mmem inc_amem'
          , csMdsk = max x_mdsk inc_adsk
          , csMcpu = x_mcpu
          , csImem = x_imem + inc_imem
          , csIdsk = x_idsk + inc_idsk
          , csIcpu = x_icpu + inc_icpu
          , csTmem = x_tmem + Node.tMem node
          , csTdsk = x_tdsk + Node.tDsk node
          , csTcpu = x_tcpu + Node.tCpu node
          , csXmem = x_xmem + Node.xMem node
          , csNmem = x_nmem + Node.nMem node
          , csNinst = x_ninst + length (Node.pList node)
          }

-- | Compute the total free disk and memory in the cluster.
totalResources :: Node.List -> CStats
totalResources nl =
    let cs = foldl' updateCStats emptyCStats . Container.elems $ nl
    in cs { csScore = compCV nl }

-- | The names of the individual elements in the CV list
detailedCVNames :: [String]
detailedCVNames = [ "free_mem_cv"
                  , "free_disk_cv"
                  , "n1_cnt"
                  , "reserved_mem_cv"
                  , "offline_all_cnt"
                  , "offline_pri_cnt"
                  , "vcpu_ratio_cv"
                  , "cpu_load_cv"
                  , "mem_load_cv"
                  , "disk_load_cv"
                  , "net_load_cv"
                  , "pri_tags_score"
                  ]

-- | Compute the mem and disk covariance.
compDetailedCV :: Node.List -> [Double]
compDetailedCV nl =
    let
        all_nodes = Container.elems nl
        (offline, nodes) = partition Node.offline all_nodes
        mem_l = map Node.pMem nodes
        dsk_l = map Node.pDsk nodes
        -- metric: memory covariance
        mem_cv = varianceCoeff mem_l
        -- metric: disk covariance
        dsk_cv = varianceCoeff dsk_l
        n1_l = length $ filter Node.failN1 nodes
        -- metric: count of failN1 nodes
        n1_score = fromIntegral n1_l::Double
        res_l = map Node.pRem nodes
        -- metric: reserved memory covariance
        res_cv = varianceCoeff res_l
        -- offline instances metrics
        offline_ipri = sum . map (length . Node.pList) $ offline
        offline_isec = sum . map (length . Node.sList) $ offline
        -- metric: count of instances on offline nodes
        off_score = fromIntegral (offline_ipri + offline_isec)::Double
        -- metric: count of primary instances on offline nodes (this
        -- helps with evacuation/failover of primary instances on
        -- 2-node clusters with one node offline)
        off_pri_score = fromIntegral offline_ipri::Double
        cpu_l = map Node.pCpu nodes
        -- metric: covariance of vcpu/pcpu ratio
        cpu_cv = varianceCoeff cpu_l
        -- metrics: covariance of cpu, memory, disk and network load
        (c_load, m_load, d_load, n_load) = unzip4 $
            map (\n ->
                     let DynUtil c1 m1 d1 n1 = Node.utilLoad n
                         DynUtil c2 m2 d2 n2 = Node.utilPool n
                     in (c1/c2, m1/m2, d1/d2, n1/n2)
                ) nodes
        -- metric: conflicting instance count
        pri_tags_inst = sum $ map Node.conflictingPrimaries nodes
        pri_tags_score = fromIntegral pri_tags_inst::Double
    in [ mem_cv, dsk_cv, n1_score, res_cv, off_score, off_pri_score, cpu_cv
       , varianceCoeff c_load, varianceCoeff m_load
       , varianceCoeff d_load, varianceCoeff n_load
       , pri_tags_score ]

-- | Compute the /total/ variance.
compCV :: Node.List -> Double
compCV = sum . compDetailedCV

-- | Compute online nodes from a Node.List
getOnline :: Node.List -> [Node.Node]
getOnline = filter (not . Node.offline) . Container.elems

-- * hbal functions

-- | Compute best table. Note that the ordering of the arguments is important.
compareTables :: Table -> Table -> Table
compareTables a@(Table _ _ a_cv _) b@(Table _ _ b_cv _ ) =
    if a_cv > b_cv then b else a

-- | Applies an instance move to a given node list and instance.
applyMove :: Node.List -> Instance.Instance
          -> IMove -> OpResult (Node.List, Instance.Instance, Ndx, Ndx)
-- Failover (f)
applyMove nl inst Failover =
    let old_pdx = Instance.pNode inst
        old_sdx = Instance.sNode inst
        old_p = Container.find old_pdx nl
        old_s = Container.find old_sdx nl
        int_p = Node.removePri old_p inst
        int_s = Node.removeSec old_s inst
        new_nl = do -- Maybe monad
          new_p <- Node.addPri int_s inst
          new_s <- Node.addSec int_p inst old_sdx
          let new_inst = Instance.setBoth inst old_sdx old_pdx
          return (Container.addTwo old_pdx new_s old_sdx new_p nl,
                  new_inst, old_sdx, old_pdx)
    in new_nl

-- Replace the primary (f:, r:np, f)
applyMove nl inst (ReplacePrimary new_pdx) =
    let old_pdx = Instance.pNode inst
        old_sdx = Instance.sNode inst
        old_p = Container.find old_pdx nl
        old_s = Container.find old_sdx nl
        tgt_n = Container.find new_pdx nl
        int_p = Node.removePri old_p inst
        int_s = Node.removeSec old_s inst
        new_nl = do -- Maybe monad
          -- check that the current secondary can host the instance
          -- during the migration
          tmp_s <- Node.addPri int_s inst
          let tmp_s' = Node.removePri tmp_s inst
          new_p <- Node.addPri tgt_n inst
          new_s <- Node.addSec tmp_s' inst new_pdx
          let new_inst = Instance.setPri inst new_pdx
          return (Container.add new_pdx new_p $
                  Container.addTwo old_pdx int_p old_sdx new_s nl,
                  new_inst, new_pdx, old_sdx)
    in new_nl

-- Replace the secondary (r:ns)
applyMove nl inst (ReplaceSecondary new_sdx) =
    let old_pdx = Instance.pNode inst
        old_sdx = Instance.sNode inst
        old_s = Container.find old_sdx nl
        tgt_n = Container.find new_sdx nl
        int_s = Node.removeSec old_s inst
        new_inst = Instance.setSec inst new_sdx
        new_nl = Node.addSec tgt_n inst old_pdx >>=
                 \new_s -> return (Container.addTwo new_sdx
                                   new_s old_sdx int_s nl,
                                   new_inst, old_pdx, new_sdx)
    in new_nl

-- Replace the secondary and failover (r:np, f)
applyMove nl inst (ReplaceAndFailover new_pdx) =
    let old_pdx = Instance.pNode inst
        old_sdx = Instance.sNode inst
        old_p = Container.find old_pdx nl
        old_s = Container.find old_sdx nl
        tgt_n = Container.find new_pdx nl
        int_p = Node.removePri old_p inst
        int_s = Node.removeSec old_s inst
        new_nl = do -- Maybe monad
          new_p <- Node.addPri tgt_n inst
          new_s <- Node.addSec int_p inst new_pdx
          let new_inst = Instance.setBoth inst new_pdx old_pdx
          return (Container.add new_pdx new_p $
                  Container.addTwo old_pdx new_s old_sdx int_s nl,
                  new_inst, new_pdx, old_pdx)
    in new_nl

-- Failver and replace the secondary (f, r:ns)
applyMove nl inst (FailoverAndReplace new_sdx) =
    let old_pdx = Instance.pNode inst
        old_sdx = Instance.sNode inst
        old_p = Container.find old_pdx nl
        old_s = Container.find old_sdx nl
        tgt_n = Container.find new_sdx nl
        int_p = Node.removePri old_p inst
        int_s = Node.removeSec old_s inst
        new_nl = do -- Maybe monad
          new_p <- Node.addPri int_s inst
          new_s <- Node.addSec tgt_n inst old_sdx
          let new_inst = Instance.setBoth inst old_sdx new_sdx
          return (Container.add new_sdx new_s $
                  Container.addTwo old_sdx new_p old_pdx int_p nl,
                  new_inst, old_sdx, new_sdx)
    in new_nl

-- | Tries to allocate an instance on one given node.
allocateOnSingle :: Node.List -> Instance.Instance -> Node.Node
                 -> OpResult AllocElement
allocateOnSingle nl inst p =
    let new_pdx = Node.idx p
        new_inst = Instance.setBoth inst new_pdx Node.noSecondary
        new_nl = Node.addPri p inst >>= \new_p ->
                 return (Container.add new_pdx new_p nl, new_inst, [new_p])
    in new_nl

-- | Tries to allocate an instance on a given pair of nodes.
allocateOnPair :: Node.List -> Instance.Instance -> Node.Node -> Node.Node
               -> OpResult AllocElement
allocateOnPair nl inst tgt_p tgt_s =
    let new_pdx = Node.idx tgt_p
        new_sdx = Node.idx tgt_s
        new_nl = do -- Maybe monad
          new_p <- Node.addPri tgt_p inst
          new_s <- Node.addSec tgt_s inst new_pdx
          let new_inst = Instance.setBoth inst new_pdx new_sdx
          return (Container.addTwo new_pdx new_p new_sdx new_s nl, new_inst,
                 [new_p, new_s])
    in new_nl

-- | Tries to perform an instance move and returns the best table
-- between the original one and the new one.
checkSingleStep :: Table -- ^ The original table
                -> Instance.Instance -- ^ The instance to move
                -> Table -- ^ The current best table
                -> IMove -- ^ The move to apply
                -> Table -- ^ The final best table
checkSingleStep ini_tbl target cur_tbl move =
    let
        Table ini_nl ini_il _ ini_plc = ini_tbl
        tmp_resu = applyMove ini_nl target move
    in
      case tmp_resu of
        OpFail _ -> cur_tbl
        OpGood (upd_nl, new_inst, pri_idx, sec_idx) ->
            let tgt_idx = Instance.idx target
                upd_cvar = compCV upd_nl
                upd_il = Container.add tgt_idx new_inst ini_il
                upd_plc = (tgt_idx, pri_idx, sec_idx, move, upd_cvar):ini_plc
                upd_tbl = Table upd_nl upd_il upd_cvar upd_plc
            in
              compareTables cur_tbl upd_tbl

-- | Given the status of the current secondary as a valid new node and
-- the current candidate target node, generate the possible moves for
-- a instance.
possibleMoves :: Bool      -- ^ Whether the secondary node is a valid new node
              -> Ndx       -- ^ Target node candidate
              -> [IMove]   -- ^ List of valid result moves
possibleMoves True tdx =
    [ReplaceSecondary tdx,
     ReplaceAndFailover tdx,
     ReplacePrimary tdx,
     FailoverAndReplace tdx]

possibleMoves False tdx =
    [ReplaceSecondary tdx,
     ReplaceAndFailover tdx]

-- | Compute the best move for a given instance.
checkInstanceMove :: [Ndx]             -- ^ Allowed target node indices
                  -> Bool              -- ^ Whether disk moves are allowed
                  -> Table             -- ^ Original table
                  -> Instance.Instance -- ^ Instance to move
                  -> Table             -- ^ Best new table for this instance
checkInstanceMove nodes_idx disk_moves ini_tbl target =
    let
        opdx = Instance.pNode target
        osdx = Instance.sNode target
        nodes = filter (\idx -> idx /= opdx && idx /= osdx) nodes_idx
        use_secondary = elem osdx nodes_idx
        aft_failover = if use_secondary -- if allowed to failover
                       then checkSingleStep ini_tbl target ini_tbl Failover
                       else ini_tbl
        all_moves = if disk_moves
                    then concatMap (possibleMoves use_secondary) nodes
                    else []
    in
      -- iterate over the possible nodes for this instance
      foldl' (checkSingleStep ini_tbl target) aft_failover all_moves

-- | Compute the best next move.
checkMove :: [Ndx]               -- ^ Allowed target node indices
          -> Bool                -- ^ Whether disk moves are allowed
          -> Table               -- ^ The current solution
          -> [Instance.Instance] -- ^ List of instances still to move
          -> Table               -- ^ The new solution
checkMove nodes_idx disk_moves ini_tbl victims =
    let Table _ _ _ ini_plc = ini_tbl
        -- iterate over all instances, computing the best move
        best_tbl =
            foldl'
            (\ step_tbl em ->
                 if Instance.sNode em == Node.noSecondary then step_tbl
                    else compareTables step_tbl $
                         checkInstanceMove nodes_idx disk_moves ini_tbl em)
            ini_tbl victims
        Table _ _ _ best_plc = best_tbl
    in
      if length best_plc == length ini_plc then -- no advancement
          ini_tbl
      else
          best_tbl

-- | Check if we are allowed to go deeper in the balancing

doNextBalance :: Table       -- ^ The starting table
              -> Int         -- ^ Remaining length
              -> Score       -- ^ Score at which to stop
              -> Bool -- ^ The resulting table and commands
doNextBalance ini_tbl max_rounds min_score =
    let Table _ _ ini_cv ini_plc = ini_tbl
        ini_plc_len = length ini_plc
    in (max_rounds < 0 || ini_plc_len < max_rounds) && ini_cv > min_score

-- | Run a balance move

tryBalance :: Table       -- ^ The starting table
           -> Bool        -- ^ Allow disk moves
           -> Maybe Table -- ^ The resulting table and commands
tryBalance ini_tbl disk_moves =
    let Table ini_nl ini_il ini_cv _ = ini_tbl
        all_inst = Container.elems ini_il
        node_idx = map Node.idx . filter (not . Node.offline) $
                   Container.elems ini_nl
        fin_tbl = checkMove node_idx disk_moves ini_tbl all_inst
        (Table _ _ fin_cv _) = fin_tbl
    in
      if fin_cv < ini_cv
      then Just fin_tbl -- this round made success, return the new table
      else Nothing

-- * Allocation functions

-- | Build failure stats out of a list of failures
collapseFailures :: [FailMode] -> FailStats
collapseFailures flst =
    map (\k -> (k, length $ filter ((==) k) flst)) [minBound..maxBound]

-- | Update current Allocation solution and failure stats with new
-- elements
concatAllocs :: AllocSolution -> OpResult AllocElement -> AllocSolution
concatAllocs (flst, cntok, sols) (OpFail reason) = (reason:flst, cntok, sols)

concatAllocs (flst, cntok, osols) (OpGood ns@(nl, _, _)) =
    let nscore = compCV nl
        -- Choose the old or new solution, based on the cluster score
        nsols = case osols of
                  Nothing -> Just (nscore, ns)
                  Just (oscore, _) ->
                      if oscore < nscore
                      then osols
                      else Just (nscore, ns)
        nsuc = cntok + 1
    -- Note: we force evaluation of nsols here in order to keep the
    -- memory profile low - we know that we will need nsols for sure
    -- in the next cycle, so we force evaluation of nsols, since the
    -- foldl' in the caller will only evaluate the tuple, but not the
    -- elements of the tuple
    in nsols `seq` nsuc `seq` (flst, nsuc, nsols)

-- | Try to allocate an instance on the cluster.
tryAlloc :: (Monad m) =>
            Node.List         -- ^ The node list
         -> Instance.List     -- ^ The instance list
         -> Instance.Instance -- ^ The instance to allocate
         -> Int               -- ^ Required number of nodes
         -> m AllocSolution   -- ^ Possible solution list
tryAlloc nl _ inst 2 =
    let all_nodes = getOnline nl
        all_pairs = liftM2 (,) all_nodes all_nodes
        ok_pairs = filter (\(x, y) -> Node.idx x /= Node.idx y) all_pairs
        sols = foldl' (\cstate (p, s) ->
                           concatAllocs cstate $ allocateOnPair nl inst p s
                      ) ([], 0, Nothing) ok_pairs
    in return sols

tryAlloc nl _ inst 1 =
    let all_nodes = getOnline nl
        sols = foldl' (\cstate ->
                           concatAllocs cstate . allocateOnSingle nl inst
                      ) ([], 0, Nothing) all_nodes
    in return sols

tryAlloc _ _ _ reqn = fail $ "Unsupported number of allocation \
                             \destinations required (" ++ show reqn ++
                                               "), only two supported"

-- | Try to allocate an instance on the cluster.
tryReloc :: (Monad m) =>
            Node.List       -- ^ The node list
         -> Instance.List   -- ^ The instance list
         -> Idx             -- ^ The index of the instance to move
         -> Int             -- ^ The number of nodes required
         -> [Ndx]           -- ^ Nodes which should not be used
         -> m AllocSolution -- ^ Solution list
tryReloc nl il xid 1 ex_idx =
    let all_nodes = getOnline nl
        inst = Container.find xid il
        ex_idx' = Instance.pNode inst:ex_idx
        valid_nodes = filter (not . flip elem ex_idx' . Node.idx) all_nodes
        valid_idxes = map Node.idx valid_nodes
        sols1 = foldl' (\cstate x ->
                            let em = do
                                  (mnl, i, _, _) <-
                                      applyMove nl inst (ReplaceSecondary x)
                                  return (mnl, i, [Container.find x mnl])
                            in concatAllocs cstate em
                       ) ([], 0, Nothing) valid_idxes
    in return sols1

tryReloc _ _ _ reqn _  = fail $ "Unsupported number of relocation \
                                \destinations required (" ++ show reqn ++
                                                  "), only one supported"

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
      FailoverAndReplace _ -> (printf "f r:%s" d, [mig, rep d])
      ReplaceSecondary _ -> (printf "r:%s" d, [rep d])
      ReplaceAndFailover _ -> (printf "r:%s f" c, [rep c, mig])
      ReplacePrimary _ -> (printf "f r:%s f" c, [mig, rep c, mig])
    where morf = if Instance.running i then "migrate" else "failover"
          mig = printf "%s -f %s" morf inam::String
          rep n = printf "replace-disks -n %s %s" n inam

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
    let
        pmlen = (2*nmlen + 1)
        (i, p, s, mv, c) = plc
        inst = Container.find i il
        inam = Instance.name inst
        npri = Container.nameOf nl p
        nsec = Container.nameOf nl s
        opri = Container.nameOf nl $ Instance.pNode inst
        osec = Container.nameOf nl $ Instance.sNode inst
        (moves, cmds) =  computeMoves inst inam mv npri nsec
        ostr = printf "%s:%s" opri osec::String
        nstr = printf "%s:%s" npri nsec::String
    in
      (printf "  %3d. %-*s %-*s => %-*s %.8f a=%s"
       pos imlen inam pmlen ostr
       pmlen nstr c moves,
       cmds)

-- | Return the instance and involved nodes in an instance move.
involvedNodes :: Instance.List -> Placement -> [Ndx]
involvedNodes il plc =
    let (i, np, ns, _, _) = plc
        inst = Container.find i il
        op = Instance.pNode inst
        os = Instance.sNode inst
    in nub [np, ns, op, os]

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

-- | Converts a solution to string format.
printSolution :: Node.List
              -> Instance.List
              -> [Placement]
              -> ([String], [[String]])
printSolution nl il sol =
    let
        nmlen = Container.maxNameLen nl
        imlen = Container.maxNameLen il
    in
      unzip $ zipWith (printSolutionLine nl il nmlen imlen) sol [1..]

-- | Print the node list.
printNodes :: Node.List -> [String] -> String
printNodes nl fs =
    let fields = if null fs
                 then Node.defaultFields
                 else fs
        snl = sortBy (compare `on` Node.idx) (Container.elems nl)
        (header, isnum) = unzip $ map Node.showHeader fields
    in unlines . map ((:) ' ' .  intercalate " ") $
       formatTable (header:map (Node.list fields) snl) isnum

-- | Print the instance list.
printInsts :: Node.List -> Instance.List -> String
printInsts nl il =
    let sil = sortBy (compare `on` Instance.idx) (Container.elems il)
        helper inst = [ if Instance.running inst then "R" else " "
                      , Instance.name inst
                      , Container.nameOf nl (Instance.pNode inst)
                      , (let sdx = Instance.sNode inst
                         in if sdx == Node.noSecondary
                            then  ""
                            else Container.nameOf nl sdx)
                      , printf "%3d" $ Instance.vcpus inst
                      , printf "%5d" $ Instance.mem inst
                      , printf "%5d" $ Instance.dsk inst `div` 1024
                      , printf "%5.3f" lC
                      , printf "%5.3f" lM
                      , printf "%5.3f" lD
                      , printf "%5.3f" lN
                      ]
            where DynUtil lC lM lD lN = Instance.util inst
        header = [ "F", "Name", "Pri_node", "Sec_node", "vcpu", "mem"
                 , "dsk", "lCpu", "lMem", "lDsk", "lNet" ]
        isnum = False:False:False:False:repeat True
    in unlines . map ((:) ' ' . intercalate " ") $
       formatTable (header:map helper sil) isnum

-- | Shows statistics for a given node list.
printStats :: Node.List -> String
printStats nl =
    let dcvs = compDetailedCV nl
        hd = zip (detailedCVNames ++ repeat "unknown") dcvs
        formatted = map (\(header, val) ->
                             printf "%s=%.8f" header val::String) hd
    in intercalate ", " formatted

-- | Convert a placement into a list of OpCodes (basically a job).
iMoveToJob :: String -> Node.List -> Instance.List
          -> Idx -> IMove -> [OpCodes.OpCode]
iMoveToJob csf nl il idx move =
    let inst = Container.find idx il
        iname = Instance.name inst ++ csf
        lookNode n = Just (Container.nameOf nl n ++ csf)
        opF = if Instance.running inst
              then OpCodes.OpMigrateInstance iname True False
              else OpCodes.OpFailoverInstance iname False
        opR n = OpCodes.OpReplaceDisks iname (lookNode n)
                OpCodes.ReplaceNewSecondary [] Nothing
    in case move of
         Failover -> [ opF ]
         ReplacePrimary np -> [ opF, opR np, opF ]
         ReplaceSecondary ns -> [ opR ns ]
         ReplaceAndFailover np -> [ opR np, opF ]
         FailoverAndReplace ns -> [ opF, opR ns ]

{-| Implementation of node evacuation

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

module Ganeti.HTools.Cluster.Evacuate
  ( EvacSolution(..)
  , nodeEvacInstance
  , tryNodeEvac
  , emptyEvacSolution
  , updateEvacSolution
  , reverseEvacSolution
  ) where

import qualified Data.IntSet as IntSet
import Data.List (foldl')
import Data.Maybe (fromJust)

import Ganeti.BasicTypes
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..))
import Ganeti.HTools.Cluster.Metrics (compCVNodes)
import Ganeti.HTools.Cluster.Moves (applyMoveEx)
import Ganeti.HTools.Cluster.Utils ( splitCluster, iMoveToJob
                                   , instancePriGroup, availableGroupNodes)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types
import qualified Ganeti.OpCodes as OpCodes
import Ganeti.Types

-- | Node evacuation/group change iallocator result type. This result
-- type consists of actual opcodes (a restricted subset) that are
-- transmitted back to Ganeti.
data EvacSolution = EvacSolution
  { esMoved   :: [(Idx, Gdx, [Ndx])]  -- ^ Instances moved successfully
  , esFailed  :: [(Idx, String)]      -- ^ Instances which were not
                                      -- relocated
  , esOpCodes :: [[OpCodes.OpCode]]   -- ^ List of jobs
  } deriving (Show)

-- | The empty evac solution.
emptyEvacSolution :: EvacSolution
emptyEvacSolution = EvacSolution { esMoved = []
                                 , esFailed = []
                                 , esOpCodes = []
                                 }

-- | Reverses an evacuation solution.
--
-- Rationale: we always concat the results to the top of the lists, so
-- for proper jobset execution, we should reverse all lists.
reverseEvacSolution :: EvacSolution -> EvacSolution
reverseEvacSolution (EvacSolution f m o) =
  EvacSolution (reverse f) (reverse m) (reverse o)

-- | A simple type for the running solution of evacuations.
type EvacInnerState =
  Either String (Node.List, Instance.Instance, Score, Ndx)

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

nodeEvacInstance opts nl il ChangePrimary
                 inst@(Instance.Instance {Instance.diskTemplate = DTDrbd8})
                 _ _ =
  do
    (nl', inst', _, _) <- opToResult
                          $ applyMoveEx (algIgnoreSoftErrors opts) nl inst
                            Failover
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

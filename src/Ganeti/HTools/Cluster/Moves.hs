{-| Implementation of instance moves in a cluster.

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

module Ganeti.HTools.Cluster.Moves
  ( applyMoveEx
  , setInstanceLocationScore
  , move
  ) where

import qualified Data.Set as Set

import Ganeti.HTools.Types
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node

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

-- | Sets the location score of an instance, given its primary
-- and secondary node.
setInstanceLocationScore :: Instance.Instance -- ^ the original instance
                         -> Node.Node -- ^ the primary node of the instance
                         -> Node.Node -- ^ the secondary node of the instance
                         -> Instance.Instance -- ^ the instance with the
                                              -- location score updated
setInstanceLocationScore t p s =
  t { Instance.locationScore =
         Set.size $ Node.locationTags p `Set.intersection` Node.locationTags s }

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
        new_s <- Node.addSecExEx (Node.offline old_p)
                   (Node.offline old_p || force) int_p inst old_sdx
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
      new_inst = Instance.setPri (setInstanceLocationScore inst tgt_n int_s)
                 new_pdx
      force_p = Node.offline old_p || force
      new_nl = do -- OpResult
                  -- check that the current secondary can host the instance
                  -- during the migration
        Node.checkMigration old_p old_s
        Node.checkMigration old_s tgt_n
        tmp_s <- Node.addPriEx force_p int_s new_inst
        let tmp_s' = Node.removePri tmp_s new_inst
        new_p <- Node.addPriEx force_p tgt_n new_inst
        new_s <- Node.addSecEx force_p tmp_s' new_inst new_pdx
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
      pnode = Container.find old_pdx nl
      pnode' = Node.removePri pnode inst
      int_s = Node.removeSec old_s inst
      force_s = Node.offline old_s || force
      new_inst = Instance.setSec (setInstanceLocationScore inst pnode tgt_n)
                 new_sdx
      new_nl = do
        new_s <- Node.addSecEx force_s tgt_n new_inst old_pdx
        pnode'' <- Node.addPriEx True pnode' new_inst
        return (Container.add old_pdx pnode'' $
                Container.addTwo new_sdx new_s old_sdx int_s nl,
                new_inst, old_pdx, new_sdx)
  in new_nl

-- Replace the secondary and failover (r:np, f)
applyMoveEx force nl inst (ReplaceAndFailover new_pdx) =
  let (old_pdx, old_sdx, old_p, old_s) = instanceNodes nl inst
      tgt_n = Container.find new_pdx nl
      int_p = Node.removePri old_p inst
      int_s = Node.removeSec old_s inst
      new_inst = Instance.setBoth (setInstanceLocationScore inst tgt_n int_p)
                 new_pdx old_pdx
      force_s = Node.offline old_s || force
      new_nl = do -- OpResult
        Node.checkMigration old_p tgt_n
        new_p <- Node.addPriEx force tgt_n new_inst
        new_s <- Node.addSecEx force_s int_p new_inst new_pdx
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
      new_inst = Instance.setBoth (setInstanceLocationScore inst int_s tgt_n)
                 old_sdx new_sdx
      new_nl = do -- OpResult
        Node.checkMigration old_p old_s
        new_p <- Node.addPriEx force_p int_s new_inst
        new_s <- Node.addSecEx force_p tgt_n new_inst old_sdx
        return (Container.add new_sdx new_s $
                Container.addTwo old_sdx new_p old_pdx int_p nl,
                new_inst, old_sdx, new_sdx)
  in new_nl

-- | Apply a move to an instance, ignoring soft errors. This is a
-- variant of `applyMoveEx True` suitable for folding.
move :: (Node.List, Instance.List)
        -> (Idx, IMove)
        -> OpResult (Node.List, Instance.List)
move (nl, il) (idx, mv) = do
  let inst = Container.find idx il
  (nl', inst', _, _) <- applyMoveEx True nl inst mv
  return (nl', Container.add idx inst' il)

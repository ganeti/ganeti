{-| Implementation of global N+1 redundancy

-}

{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.HTools.GlobalN1
  ( canEvacuateNode
  , redundant
  , redundantGrp
  , allocGlobalN1
  ) where

import Control.Monad (foldM, foldM_)
import qualified Data.Foldable as Foldable
import Data.Function (on)
import Data.List (partition, sortBy)

import Ganeti.BasicTypes (isOk, Result)
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..), defaultOptions)
import Ganeti.HTools.Cluster.AllocatePrimitives (allocateOnSingle)
import qualified Ganeti.HTools.Cluster.AllocationSolution as AllocSol
import qualified Ganeti.HTools.Cluster.Evacuate as Evacuate
import Ganeti.HTools.Cluster.Moves (move)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types ( IMove(Failover), Ndx, Gdx, Idx, opToResult,
                             FailMode(FailN1) )
import Ganeti.Types ( DiskTemplate(DTDrbd8), diskTemplateMovable
                    , EvacMode(ChangePrimary))

-- | Foldable function describing how a non-DRBD instance
-- is to be evacuated.
evac :: Gdx -> [Ndx]
     -> (Node.List, Instance.List) -> Idx -> Result (Node.List, Instance.List)
evac gdx ndxs (nl, il) idx = do
  let opts = defaultOptions { algIgnoreSoftErrors = True, algEvacMode = True }
      inst = Container.find idx il
  (nl', il', _) <- Evacuate.nodeEvacInstance opts nl il ChangePrimary inst
                     gdx ndxs
  return (nl', il')

-- | Foldable function describing how a non-movable instance is to
-- be recreated on one of the given nodes.
recreate :: [Ndx]
         -> (Node.List, Instance.List)
         -> Instance.Instance
         -> Result (Node.List, Instance.List)
recreate targetnodes (nl, il) inst = do
  let opts = defaultOptions { algIgnoreSoftErrors = True, algEvacMode = True }
      sols = foldl (\cstate ->
                       AllocSol.concatAllocCollections cstate
                       . allocateOnSingle opts nl inst
                   ) AllocSol.emptyAllocCollection targetnodes
      sol = AllocSol.collectionToSolution FailN1 (const True) sols
  alloc <- maybe (fail "No solution found") return $ AllocSol.asSolution sol
  let il' = AllocSol.updateIl il $ Just alloc
      nl' = AllocSol.extractNl nl il $ Just alloc
  return (nl', il')

-- | Decide if a node can be evacuated, i.e., all DRBD instances
-- failed over and all shared/external storage instances moved off
-- to other nodes.
canEvacuateNode :: (Node.List, Instance.List) -> Node.Node -> Bool
canEvacuateNode (nl, il) n = isOk $ do
  let (drbdIdxs, otherIdxs) = partition ((==) DTDrbd8
                                         . Instance.diskTemplate
                                         . flip Container.find il)
                              $ Node.pList n
      (sharedIdxs, nonMoveIdxs) = partition (diskTemplateMovable
                                  . Instance.diskTemplate
                                  . flip Container.find il) otherIdxs
  -- failover all DRBD instances with primaries on n
  (nl', il') <- opToResult
                . foldM move (nl, il) $ map (flip (,) Failover) drbdIdxs
  -- evacuate other instances
  let grp = Node.group n
      escapenodes = filter (/= Node.idx n)
                    . map Node.idx
                    . filter ((== grp) . Node.group)
                    $ Container.elems nl'
  (nl'', il'') <- foldM (evac grp escapenodes) (nl',il') sharedIdxs
  let recreateInstances = sortBy (flip compare `on` Instance.mem)
                          $ map (`Container.find` il'') nonMoveIdxs
  foldM_ (recreate escapenodes) (nl'', il'') recreateInstances

-- | Predicate on wheter a given situation is globally N+1 redundant.
redundant :: AlgorithmOptions -> Node.List -> Instance.List -> Bool
redundant opts nl il =
  let filterFun = if algAcceptExisting opts
                    then Container.filter (not . Node.offline)
                    else id
  in Foldable.all (canEvacuateNode (nl, il))
       . Container.filter (not . (`elem` algCapacityIgnoreGroups opts)
                               . Node.group)
       $ filterFun nl

-- | Predicate on wheter a given group is globally N+1 redundant.
redundantGrp :: AlgorithmOptions -> Node.List -> Instance.List -> Gdx -> Bool
redundantGrp opts nl il gdx =
  redundant opts (Container.filter ((==) gdx . Node.group) nl) il

-- | Predicate on wheter an allocation element leads to a globally N+1 redundant
-- state.
allocGlobalN1 :: AlgorithmOptions
              -> Node.List -- ^ the original list of nodes
              -> Instance.List -- ^ the original list of instances
              -> AllocSol.GenericAllocElement a -> Bool
allocGlobalN1 opts nl il alloc =
  let il' = AllocSol.updateIl il $ Just alloc
      nl' = AllocSol.extractNl nl il $ Just alloc
  in redundant opts nl' il'

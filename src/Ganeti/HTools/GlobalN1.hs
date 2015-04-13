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
  ) where

import Control.Monad (foldM)
import qualified Data.IntMap as IntMap
import Data.List (partition)

import Ganeti.BasicTypes (isOk, Result)
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..), defaultOptions)
import qualified Ganeti.HTools.Cluster.Evacuate as Evacuate
import Ganeti.HTools.Cluster.Moves (move)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types ( IMove(Failover), Ndx, Gdx, Idx, opToResult)
import Ganeti.Types ( DiskTemplate(DTDrbd8, DTPlain, DTFile)
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

-- | Decide if a node can be evacuated, i.e., all DRBD instances
-- failed over and all shared/external storage instances moved off
-- to other nodes.
canEvacuateNode :: (Node.List, Instance.List) -> Node.Node -> Bool
canEvacuateNode (nl, il) n = isOk $ do
  let (drbdIdxs, otherIdxs) = partition ((==) DTDrbd8
                                         . Instance.diskTemplate
                                         . flip Container.find il)
                              $ Node.pList n
      sharedIdxs = filter (not . (`elem` [DTPlain, DTFile])
                           . Instance.diskTemplate
                           . flip Container.find il) otherIdxs
  -- failover all DRBD instances with primaries on n
  (nl', il') <- opToResult
                . foldM move (nl, il) $ map (flip (,) Failover) drbdIdxs
  -- evacuate other instances
  let n' = Node.setOffline n True
      nl'' = Container.add (Node.idx n') n' nl'
  _ <- foldM (evac (Node.group n') . map Node.idx $ IntMap.elems nl'')
             (nl'',il') sharedIdxs
  return ()

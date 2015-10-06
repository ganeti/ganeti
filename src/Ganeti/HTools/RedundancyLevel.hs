{-| Implementation of the computation of the cluster redundancy level

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

module Ganeti.HTools.RedundancyLevel
  ( redundancy
  ) where

import Control.Applicative (liftA2)
import Control.Arrow ((&&&))
import Data.Function (on)
import qualified Data.IntMap as IntMap
import Data.List (sortBy)

import Ganeti.BasicTypes (runListHead)
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions)
import Ganeti.HTools.GlobalN1 (redundant)
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.Utils (iterateJust)

-- | Estimate the level of redundancy of node group given
-- by its nodes and instances.
redundancy :: AlgorithmOptions -> Node.List -> Instance.List -> Int
redundancy _    nl _  | any (liftA2 (&&) Node.offline $ not . null . Node.pList)
                        $ IntMap.elems nl = -1
redundancy opts nl il | not $ redundant opts nl il = 0
redundancy opts nl il =
  let sortedNodes =
        sortBy (compare `on` ((Node.tMem . snd) &&& fst))
        . filter (not . Node.offline . snd)
        $ IntMap.toAscList nl
   in case sortedNodes of
     [] -> 0
     (indexBigNode, bigNode):_ ->
       let bigNode' = bigNode { Node.offline = True }
           nl' = Container.add indexBigNode bigNode' nl
           initialMetrics = Metrics.compCV nl'
           initialTable = Cluster.Table nl' il initialMetrics []
           Cluster.Table nl'' il' _ _ =
             runListHead initialTable id . reverse
             $ iterateJust (Cluster.tryBalance opts) initialTable
       in 1 + redundancy opts nl'' il'

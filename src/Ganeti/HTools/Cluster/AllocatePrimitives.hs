{-| Implementation of the primitives of instance allocation

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013, 2015 Google Inc.
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

module Ganeti.HTools.Cluster.AllocatePrimitives
  ( allocateOnSingle
  , allocateOnPair
  ) where

import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..))
import Ganeti.HTools.Cluster.AllocationSolution (AllocElement)
import Ganeti.HTools.Cluster.Metrics ( compCV, compCVfromStats
                                     , updateClusterStatisticsTwice)
import Ganeti.HTools.Cluster.Moves (setInstanceLocationScore)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types
import Ganeti.Utils.Statistics

-- | Tries to allocate an instance on one given node.
allocateOnSingle :: AlgorithmOptions
                 -> Node.List -> Instance.Instance -> Ndx
                 -> OpResult AllocElement
allocateOnSingle opts nl inst new_pdx =
  let p = Container.find new_pdx nl
      new_inst = Instance.setBoth inst new_pdx Node.noSecondary
      force = algIgnoreSoftErrors opts
  in do
    Instance.instMatchesPolicy inst (Node.iPolicy p) (Node.exclStorage p)
    new_p <- Node.addPriEx force p inst
    let new_nl = Container.add new_pdx new_p nl
        new_score = compCV new_nl
    return (new_nl, new_inst, [new_p], new_score)

-- | Tries to allocate an instance on a given pair of nodes.
allocateOnPair :: AlgorithmOptions
               -> [Statistics]
               -> Node.List -> Instance.Instance -> Ndx -> Ndx
               -> OpResult AllocElement
allocateOnPair opts stats nl inst new_pdx new_sdx =
  let tgt_p = Container.find new_pdx nl
      tgt_s = Container.find new_sdx nl
      force = algIgnoreSoftErrors opts
  in do
    Instance.instMatchesPolicy inst (Node.iPolicy tgt_p)
      (Node.exclStorage tgt_p)
    let new_inst = Instance.setBoth (setInstanceLocationScore inst tgt_p
                                                              (Just tgt_s))
                   new_pdx new_sdx
    new_p <- Node.addPriEx force tgt_p new_inst
    new_s <- Node.addSec tgt_s new_inst new_pdx
    let new_nl = Container.addTwo new_pdx new_p new_sdx new_s nl
        new_stats = updateClusterStatisticsTwice stats
                      (tgt_p, new_p) (tgt_s, new_s)
    return (new_nl, new_inst, [new_p, new_s], compCVfromStats new_stats)

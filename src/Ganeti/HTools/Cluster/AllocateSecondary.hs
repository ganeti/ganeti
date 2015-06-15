{-| Implementation of finding a secondary for disk template conversion

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

module Ganeti.HTools.Cluster.AllocateSecondary
  ( tryAllocateSecondary
  ) where

import Control.Monad (unless)

import Ganeti.BasicTypes
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..))
import qualified Ganeti.HTools.Cluster as Cluster
import Ganeti.HTools.Cluster.AllocationSolution (AllocSolution)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types

tryAllocateSecondary :: AlgorithmOptions
                     -> Group.List    -- ^ The cluster groups
                     -> Node.List     -- ^ The node list (cluster-wide,
                                      -- not per group)
                     -> Instance.List -- ^ Instance list (cluster-wide)
                     -> Idx
                     -> Result AllocSolution
tryAllocateSecondary opts _ nl il idx = do
  let inst = Container.find idx il
  unless (Instance.sNode inst < 0)
    $ fail "Instance already has a secondary"
  let pidx = Instance.pNode inst
      pnode = Container.find pidx nl
      pnode' = Node.removePri pnode inst
      nl' = Container.add pidx pnode' nl
      inst' = inst { Instance.diskTemplate = DTDrbd8 }
      gidx = Node.group pnode'
      sidxs = filter (/= pidx) . Container.keys
              $ Container.filter ((==) gidx . Node.group) nl'
  Cluster.tryAlloc opts nl' il inst' $ Right [(pidx, sidxs)]

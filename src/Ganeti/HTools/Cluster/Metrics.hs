{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the cluster metric

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

module Ganeti.HTools.Cluster.Metrics
  ( ClusterStatistics
  , compCV
  , compCVfromStats
  , compCVNodes
  , compClusterStatistics
  , updateClusterStatisticsTwice
  , optimalCVScore
  , printStats
  ) where

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Cluster.MetricsComponents as M
import Ganeti.HTools.Cluster.MetricsTH

$(declareStatistics M.metricComponents)

-- | Update a cluster statistics twice.
updateClusterStatisticsTwice :: ClusterStatistics
                                -> (Node.Node, Node.Node)
                                -> (Node.Node, Node.Node)
                                -> ClusterStatistics
updateClusterStatisticsTwice s a =
  updateClusterStatistics (updateClusterStatistics s a)

-- | Compute the total cluster store given the nodes.
compCVNodes :: [Node.Node] -> Double
compCVNodes = compCVfromStats . compClusterStatistics

-- | Wrapper over 'compCVNodes' for callers that have a 'Node.List'.
compCV :: Node.List -> Double
compCV = compCVNodes . Container.elems

-- | Shows statistics for a given node list.
printStats :: String -> Node.List -> String
printStats lp =
  showClusterStatistics lp . compClusterStatistics . Container.elems

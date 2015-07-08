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
  ( compCV
  , compCVfromStats
  , compCVNodes
  , compClusterStatistics
  , updateClusterStatisticsTwice
  , optimalCVScore
  , printStats
  ) where

import Control.Monad (guard)
import Data.List (partition, transpose)
import Data.Maybe (fromMaybe)
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.PeerMap as P
import Ganeti.HTools.Types
import Ganeti.Utils (printTable)
import Ganeti.Utils.Statistics

-- | Coefficient for the total reserved memory in the cluster metric. We
-- use a (local) constant here, as it is also used in the computation of
-- the best possible cluster score.
reservedMemRtotalCoeff :: Double
reservedMemRtotalCoeff = 0.25

-- | The names and weights of the individual elements in the CV list, together
-- with their statistical accumulation function and a bit to decide whether it
-- is a statistics for online nodes.
detailedCVInfoExt :: [((Double, String)
                     , ([AggregateComponent] -> Statistics, Bool))]
detailedCVInfoExt = [ ((0.5,  "free_mem_cv"), (getStdDevStatistics, True))
                    , ((0.5,  "free_disk_cv"), (getStdDevStatistics, True))
                    , ((1,  "n1_cnt"), (getSumStatistics, True))
                    , ((1,  "reserved_mem_cv"), (getStdDevStatistics, True))
                    , ((4,  "offline_all_cnt"), (getSumStatistics, False))
                    , ((16, "offline_pri_cnt"), (getSumStatistics, False))
                    , ( (0.5,  "vcpu_ratio_cv")
                      , (getStdDevStatistics, True))
                    , ((1,  "cpu_load_cv"), (getStdDevStatistics, True))
                    , ((1,  "mem_load_cv"), (getStdDevStatistics, True))
                    , ((1,  "disk_load_cv"), (getStdDevStatistics, True))
                    , ((1,  "net_load_cv"), (getStdDevStatistics, True))
                    , ((2,  "pri_tags_score"), (getSumStatistics, True))
                    , ((0.5,  "spindles_cv"), (getStdDevStatistics, True))
                    , ((0.5,  "free_mem_cv_forth"), (getStdDevStatistics, True))
                    , ( (0.5,  "free_disk_cv_forth")
                      , (getStdDevStatistics, True))
                    , ( (0.5,  "vcpu_ratio_cv_forth")
                      , (getStdDevStatistics, True))
                    , ((0.5,  "spindles_cv_forth"), (getStdDevStatistics, True))
                    , ((1,  "location_score"), (getSumStatistics, True))
                    , ( (1,  "location_exclusion_score")
                      , (getMapStatistics, True))
                    , ( (reservedMemRtotalCoeff,  "reserved_mem_rtotal")
                      , (getSumStatistics, True))
                    ]

-- | Compute the lower bound of the cluster score, i.e., the sum of the minimal
-- values for all cluster score values that are not 0 on a perfectly balanced
-- cluster.
optimalCVScore :: Node.List -> Double
optimalCVScore nodelist = fromMaybe 0 $ do
  let nodes = Container.elems nodelist
  guard $ length nodes > 1
  let nodeMems = map Node.tMem nodes
      totalMem = sum nodeMems
      totalMemOneLessNode = totalMem - maximum nodeMems
  guard $ totalMemOneLessNode > 0
  let totalDrbdMem = fromIntegral . sum $ map (P.sumElems . Node.peers) nodes
      optimalUsage = totalDrbdMem / totalMem
      optimalUsageOneLessNode = totalDrbdMem / totalMemOneLessNode
      relativeReserved = optimalUsageOneLessNode - optimalUsage
  return $ reservedMemRtotalCoeff * relativeReserved

-- | The names and weights of the individual elements in the CV list.
detailedCVInfo :: [(Double, String)]
detailedCVInfo = map fst detailedCVInfoExt

-- | Holds the weights used by 'compCVNodes' for each metric.
detailedCVWeights :: [Double]
detailedCVWeights = map fst detailedCVInfo

-- | The aggregation functions for the weights
detailedCVAggregation :: [([AggregateComponent] -> Statistics, Bool)]
detailedCVAggregation = map snd detailedCVInfoExt

-- | The bit vector describing which parts of the statistics are
-- for online nodes.
detailedCVOnlineStatus :: [Bool]
detailedCVOnlineStatus = map snd detailedCVAggregation

-- | Compute statistical measures of a single node.
compDetailedCVNode  :: Node.Node -> [AggregateComponent]
compDetailedCVNode node =
  let mem = Node.pMem node
      memF = Node.pMemForth node
      dsk = Node.pDsk node
      dskF = Node.pDskForth node
      n1 = fromIntegral
           $ if Node.failN1 node
               then length (Node.sList node) + length (Node.pList node)
               else 0
      res = Node.pRem node
      ipri = fromIntegral . length $ Node.pList node
      isec = fromIntegral . length $ Node.sList node
      ioff = ipri + isec
      cpu = Node.pCpuEff node
      cpuF = Node.pCpuEffForth node
      DynUtil c1 m1 d1 nn1 = Node.utilLoad node
      DynUtil c2 m2 d2 nn2 = Node.utilPool node
      (c_load, m_load, d_load, n_load) = (c1/c2, m1/m2, d1/d2, nn1/nn2)
      pri_tags = fromIntegral $ Node.conflictingPrimaries node
      spindles = Node.instSpindles node / Node.hiSpindles node
      spindlesF = Node.instSpindlesForth node / Node.hiSpindles node
      location_score = fromIntegral $ Node.locationScore node
      location_exclusion_score = Node.instanceMap node
  in [ SimpleNumber mem, SimpleNumber dsk, SimpleNumber n1, SimpleNumber res
     , SimpleNumber ioff, SimpleNumber ipri, SimpleNumber cpu
     , SimpleNumber c_load, SimpleNumber m_load, SimpleNumber d_load
     , SimpleNumber n_load
     , SimpleNumber pri_tags, SimpleNumber spindles
     , SimpleNumber memF, SimpleNumber dskF, SimpleNumber cpuF
     , SimpleNumber spindlesF
     , SimpleNumber location_score
     , SpreadValues location_exclusion_score
     , SimpleNumber res
     ]

-- | Compute the statistics of a cluster.
compClusterStatistics :: [Node.Node] -> [Statistics]
compClusterStatistics all_nodes =
  let (offline, nodes) = partition Node.offline all_nodes
      offline_values = transpose (map compDetailedCVNode offline)
                       ++ repeat []
      -- transpose of an empty list is empty and not k times the empty list, as
      -- would be the transpose of a 0 x k matrix
      online_values = transpose $ map compDetailedCVNode nodes
      aggregate (f, True) (onNodes, _) = f onNodes
      aggregate (f, False) (_, offNodes) = f offNodes
  in zipWith aggregate detailedCVAggregation
       $ zip online_values offline_values

-- | Update a cluster statistics by replacing the contribution of one
-- node by that of another.
updateClusterStatistics :: [Statistics]
                           -> (Node.Node, Node.Node) -> [Statistics]
updateClusterStatistics stats (old, new) =
  let update = zip (compDetailedCVNode old) (compDetailedCVNode new)
      online = not $ Node.offline old
      updateStat forOnline stat upd = if forOnline == online
                                        then updateStatistics stat upd
                                        else stat
  in zipWith3 updateStat detailedCVOnlineStatus stats update

-- | Update a cluster statistics twice.
updateClusterStatisticsTwice :: [Statistics]
                                -> (Node.Node, Node.Node)
                                -> (Node.Node, Node.Node)
                                -> [Statistics]
updateClusterStatisticsTwice s a =
  updateClusterStatistics (updateClusterStatistics s a)

-- | Compute cluster statistics
compDetailedCV :: [Node.Node] -> [Double]
compDetailedCV = map getStatisticValue . compClusterStatistics

-- | Compute the cluster score from its statistics
compCVfromStats :: [Statistics] -> Double
compCVfromStats = sum . zipWith (*) detailedCVWeights . map getStatisticValue

-- | Compute the /total/ variance.
compCVNodes :: [Node.Node] -> Double
compCVNodes = sum . zipWith (*) detailedCVWeights . compDetailedCV

-- | Wrapper over 'compCVNodes' for callers that have a 'Node.List'.
compCV :: Node.List -> Double
compCV = compCVNodes . Container.elems

-- | Shows statistics for a given node list.
printStats :: String -> Node.List -> String
printStats lp nl =
  let dcvs = compDetailedCV $ Container.elems nl
      (weights, names) = unzip detailedCVInfo
      hd = zip3 (weights ++ repeat 1) (names ++ repeat "unknown") dcvs
      header = [ "Field", "Value", "Weight" ]
      formatted = map (\(w, h, val) ->
                         [ h
                         , printf "%.8f" val
                         , printf "x%.2f" w
                         ]) hd
  in printTable lp header formatted $ False:repeat True

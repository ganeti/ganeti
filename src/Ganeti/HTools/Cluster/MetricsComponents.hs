{-# LANGUAGE TemplateHaskell #-}

{-| Module describing cluster metrics components.

    Metrics components are used for generation of functions deaing with cluster
    statistics.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013, 2014, 2015 Google Inc.
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

module Ganeti.HTools.Cluster.MetricsComponents
  ( metricComponents
  ) where


import Control.Monad (guard)
import Data.Maybe (fromMaybe)
import Language.Haskell.TH

import Ganeti.HTools.Cluster.MetricsTH (MetricComponent(..))
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.PeerMap as P
import Ganeti.HTools.Types
import Ganeti.Utils.Statistics

-- | Coefficient that is used for optimal value computation.
-- reservedMemRTotal :: Double
-- reservedMemRTotal = 0.25

-- | Type alias decreasing table size below
type D = Double

-- | List containing all currently enabled cluster metrics components
metricComponents :: [MetricComponent]
metricComponents =
  [ stdDevComp "free_mem_cv"               [| 0.5  :: D |] True [| Node.pMem |]
  , stdDevComp "free_disk_cv"              [| 0.5  :: D |] True [| Node.pDsk |]
  , stdDevComp "vcpu_ratio_cv"             [| 0.5  :: D |] True
    [| Node.pCpuEff |]
  , sumComp    "spindles_cv"               [| 0.5  :: D |] True
    [| \n -> Node.instSpindles n / Node.hiSpindles n |]
  , sumComp    "fail_n1"                   [| 0.5  :: D |] True
    [| \n -> if Node.failN1 n
               then toDouble  $ length (Node.sList n) + length (Node.pList n)
               else 0 |]
  , stdDevComp "reserved_mem_cv"           [| 1    :: D |] True [| Node.pRem |]
  , sumComp    "offline_all_cnt"           [| 4    :: D |] False
    [| \n -> toDouble $ length (Node.pList n) + length (Node.sList n) |]
  , sumComp    "offline_pri_cnt"           [| 16   :: D |] False
    [| toDouble . length . Node.pList |]
  , stdDevComp "cpu_load_cv"               [| 1    :: D |] True
    [| \n -> let DynUtil c1 _ _ _ = Node.utilLoad n
                 DynUtil c2 _ _ _ = Node.utilPool n
             in c1/c2 |]
  , stdDevComp "mem_load_cv"               [| 1    :: D |] True
    [| \n -> let DynUtil _ m1 _ _ = Node.utilLoad n
                 DynUtil _ m2 _ _ = Node.utilPool n
             in m1/m2 |]
  , stdDevComp "disk_load_cv"              [| 1    :: D |] True
    [| \n -> let DynUtil _ _ d1 _ = Node.utilLoad n
                 DynUtil _ _ d2 _ = Node.utilPool n
             in d1/d2 |]
  , stdDevComp "net_load_cv"               [| 1    :: D |] True
    [| \n -> let DynUtil _ _ _ n1 = Node.utilLoad n
                 DynUtil _ _ _ n2 = Node.utilPool n
             in n1/n2 |]
  , sumComp     "pri_tags_score"           [| 2    :: D |] True
    [| toDouble . Node.conflictingPrimaries |]
  , sumComp     "location_score"           [| 1    :: D |] True
    [| toDouble . Node.locationScore |]
  , mapComp     "location_exclusion_score" [| 0.5  :: D |] True
    [| MapData . Node.instanceMap |]
  , stdDevComp "free_mem_cv_forth"         [| 0.5  :: D |] True
    [| Node.pMemForth    |]
  , stdDevComp "free_disk_cv_forth"        [| 0.5  :: D |] True
    [| Node.pDskForth    |]
  , stdDevComp "vcpu_ratio_cv_forth"       [| 0.5  :: D |] True
    [| Node.pCpuEffForth |]
  , sumComp    "spindles_cv_forth"         [| 0.5  :: D |] True
    [| \n -> Node.instSpindlesForth n / Node.hiSpindles n |]
  , reservedMemRTotal
  ]

-- | Function to be used as a short MetricComponent constructor for SumStat.
sumComp :: String -> ExpQ -> Bool -> ExpQ -> MetricComponent
sumComp nm w on f = MetricComponent { name = nm
                                    , weight = w
                                    , fromNode = f
                                    , fromNodeType = [t| Double |]
                                    , statisticsType = [t| SumStat |]
                                    , forOnlineNodes = on
                                    , optimalValue = [| zeroOptValueFunc |]
                                    }

-- | Function to be used as a short MetricComponent constructor for StdDevStat.
stdDevComp :: String -> ExpQ -> Bool -> ExpQ -> MetricComponent
stdDevComp nm w on f = MetricComponent { name = nm
                                       , weight = w
                                       , fromNode = f
                                       , fromNodeType = [t| Double |]
                                       , statisticsType = [t| StdDevStat |]
                                       , forOnlineNodes = on
                                       , optimalValue = [| zeroOptValueFunc |]
                                       }

-- | Function to be used as a short MetricComponent constructor for MapStat.
mapComp :: String -> ExpQ -> Bool -> ExpQ -> MetricComponent
mapComp nm w on f = MetricComponent { name = nm
                                    , weight = w
                                    , fromNode = f
                                    , fromNodeType = [t| MapData |]
                                    , statisticsType = [t| MapStat |]
                                    , forOnlineNodes = on
                                    , optimalValue = [| zeroOptValueFunc |]
                                    }

-- | Function is supposed to be used in MericComponent.hs as a most widepread
-- optimalValue function
zeroOptValueFunc :: Node.List -> Double
zeroOptValueFunc _ = 0

-- | Weight of reservedMemRTotal component
wReservedMemRTotal :: Double
wReservedMemRTotal = 0.25

reservedMemRTotal :: MetricComponent
reservedMemRTotal = MetricComponent
  { name = "reserved_mem_rtotal"
  , weight = [| wReservedMemRTotal :: D |]
  , fromNode =  [| Node.pRem |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = True
  , optimalValue = [| reservedMemRTotalOptValue |]
  }

-- | Computes theoretical opimal value for reservedMemRTotal component
reservedMemRTotalOptValue :: Node.List -> Double
reservedMemRTotalOptValue nodelist = fromMaybe 0 $ do
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
  return $ wReservedMemRTotal * relativeReserved

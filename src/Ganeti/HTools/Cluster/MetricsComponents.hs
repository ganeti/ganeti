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
  ( MetricComponent
  , metricComponents
  , reservedMemRTotal
  , name
  , weight
  , fromNode
  , fromNodeType
  , statisticsType
  , forOnlineNodes
  ) where

import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Cluster.MetricsTH (MetricComponent(..))
import Ganeti.HTools.Types
import Ganeti.Utils.Statistics

-- | List containing all currently enabled cluster metrics components
metricComponents :: [MetricComponent]
metricComponents = [ freeMemPercent
                   , freeDiskPercent
                   , cpuEffRatio
                   , spindlesUsageRatio
                   , n1FailsCount
                   , reservedMemPercent
                   , offlineInstCount
                   , offlinePriInstCount
                   , cpuLoadRatio
                   , memLoadRatio
                   , diskLoadRatio
                   , netLoadRatio
                   , priTagsScore
                   , locationScore
                   , locationExclusionScore
                   , reservedMemRTotal
                   , freeMemPercentForth
                   , freeDiskPercentForth
                   , cpuEffRatioForth
                   , spindlesUsageRatioForth
                   ]

freeMemPercent :: MetricComponent
freeMemPercent = MetricComponent
  { name = "free_mem_cv"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| Node.pMem |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

freeDiskPercent :: MetricComponent
freeDiskPercent = MetricComponent
  { name = "free_disk_cv"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| Node.pDsk |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

cpuEffRatio :: MetricComponent
cpuEffRatio = MetricComponent
  { name = "vcpu_ratio_cv"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| Node.pCpuEff |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

spindlesUsageRatio :: MetricComponent
spindlesUsageRatio = MetricComponent
  { name = "spindles_cv"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| \n -> Node.instSpindles n / Node.hiSpindles n |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = True
  }

n1FailsCount :: MetricComponent
n1FailsCount = MetricComponent
  { name = "fail_n1"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| \n -> if Node.failN1 n
                          then toDouble $
                               length (Node.sList n) + length (Node.pList n)
                          else 0 |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = True
  }

reservedMemPercent :: MetricComponent
reservedMemPercent = MetricComponent
  { name = "reserved_mem_cv"
  , weight = [| 1 :: Double |]
  , fromNode = [| Node.pRem |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

offlineInstCount :: MetricComponent
offlineInstCount = MetricComponent
  { name = "offline_all_cnt"
  , weight = [| 4 :: Double |]
  , fromNode = [| \n -> toDouble $
                        length (Node.pList n) + length (Node.sList n) |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = False
  }

offlinePriInstCount :: MetricComponent
offlinePriInstCount = MetricComponent
  { name = "offline_pri_cnt"
  , weight = [| 16 :: Double |]
  , fromNode = [| toDouble . length . Node.pList |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = False
  }

cpuLoadRatio :: MetricComponent
cpuLoadRatio = MetricComponent
  { name = "cpu_load_cv"
  , weight = [| 1 :: Double |]
  , fromNode = [| \n -> let DynUtil c1 _ _ _ = Node.utilLoad n
                            DynUtil c2 _ _ _ = Node.utilPool n
                        in c1/c2 |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

memLoadRatio :: MetricComponent
memLoadRatio = MetricComponent
  { name = "mem_load_cv"
  , weight = [| 1 :: Double |]
  , fromNode = [| \n -> let DynUtil _ m1 _ _ = Node.utilLoad n
                            DynUtil _ m2 _ _ = Node.utilPool n
                        in m1/m2 |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

diskLoadRatio :: MetricComponent
diskLoadRatio = MetricComponent
  { name = "disk_load_cv"
  , weight = [| 1 :: Double |]
  , fromNode = [| \n -> let DynUtil _ _ d1 _ = Node.utilLoad n
                            DynUtil _ _ d2 _ = Node.utilPool n
                        in d1/d2 |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

netLoadRatio :: MetricComponent
netLoadRatio = MetricComponent
  { name = "net_load_cv"
  , weight = [| 1 :: Double |]
  , fromNode = [| \n -> let DynUtil _ _ _ n1 = Node.utilLoad n
                            DynUtil _ _ _ n2 = Node.utilPool n
                        in n1/n2 |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

priTagsScore :: MetricComponent
priTagsScore = MetricComponent
  { name = "pri_tags_score"
  , weight = [| 2 :: Double |]
  , fromNode = [| toDouble . Node.conflictingPrimaries |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = True
  }

locationScore :: MetricComponent
locationScore = MetricComponent
  { name = "location_score"
  , weight = [| 1 :: Double |]
  , fromNode = [| toDouble . Node.locationScore |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = True
  }

locationExclusionScore :: MetricComponent
locationExclusionScore = MetricComponent
  { name = "location_exclusion_score"
  , weight = [| 1 :: Double |]
  , fromNode = [| MapData . Node.instanceMap |]
  , fromNodeType = [t| MapData |]
  , statisticsType = [t| MapStat |]
  , forOnlineNodes = True
  }

reservedMemRTotal :: MetricComponent
reservedMemRTotal = MetricComponent
  { name = "reserved_mem_rtotal"
  , weight = [| 0.25 :: Double |]
  , fromNode = [| Node.pRem |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = True
  }

freeMemPercentForth :: MetricComponent
freeMemPercentForth = MetricComponent
  { name = "free_mem_cv_forth"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| Node.pMemForth |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

freeDiskPercentForth :: MetricComponent
freeDiskPercentForth = MetricComponent
  { name = "free_disk_cv_forth"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| Node.pDskForth |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

cpuEffRatioForth :: MetricComponent
cpuEffRatioForth = MetricComponent
  { name = "vcpu_ratio_cv_forth"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| Node.pCpuEffForth |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| StdDevStat |]
  , forOnlineNodes = True
  }

spindlesUsageRatioForth :: MetricComponent
spindlesUsageRatioForth = MetricComponent
  { name = "spindles_cv_forth"
  , weight = [| 0.5 :: Double |]
  , fromNode = [| \n -> Node.instSpindlesForth n / Node.hiSpindles n |]
  , fromNodeType = [t| Double |]
  , statisticsType = [t| SumStat |]
  , forOnlineNodes = True
  }

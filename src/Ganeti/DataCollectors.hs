{-| Definition of the data collectors used by MonD.

-}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.DataCollectors( collectors ) where

import Data.Map (findWithDefault)
import Data.Monoid (mempty)

import qualified Ganeti.DataCollectors.CPUload as CPUload
import qualified Ganeti.DataCollectors.Diskstats as Diskstats
import qualified Ganeti.DataCollectors.Drbd as Drbd
import qualified Ganeti.DataCollectors.InstStatus as InstStatus
import qualified Ganeti.DataCollectors.Lv as Lv
import qualified Ganeti.DataCollectors.XenCpuLoad as XenCpuLoad
import Ganeti.DataCollectors.Types (DataCollector(..),ReportBuilder(..))
import Ganeti.JSON (GenericContainer(..))
import Ganeti.Objects
import Ganeti.Types

-- | The list of available builtin data collectors.
collectors :: [DataCollector]
collectors =
  [ cpuLoadCollector
  , xenCpuLoadCollector
  , diskStatsCollector
  , drdbCollector
  , instStatusCollector
  , lvCollector
  ]
  where
    f .&&. g = \x y -> f x y && g x y
    xenHypervisor = flip elem [XenPvm, XenHvm]
    xenCluster _ cfg =
      any xenHypervisor . clusterEnabledHypervisors $ configCluster cfg
    collectorConfig name cfg =
      let config = fromContainer . clusterDataCollectors $ configCluster cfg
      in  findWithDefault mempty name config
    updateInterval name cfg = dataCollectorInterval $ collectorConfig name cfg
    activeConfig name cfg = dataCollectorActive $ collectorConfig name cfg
    diskStatsCollector =
      DataCollector Diskstats.dcName Diskstats.dcCategory
        Diskstats.dcKind (StatelessR Diskstats.dcReport) Nothing activeConfig
        updateInterval
    drdbCollector =
      DataCollector Drbd.dcName Drbd.dcCategory Drbd.dcKind
        (StatelessR Drbd.dcReport) Nothing activeConfig updateInterval
    instStatusCollector =
      DataCollector InstStatus.dcName InstStatus.dcCategory
        InstStatus.dcKind (StatelessR InstStatus.dcReport) Nothing
        (xenCluster .&&. activeConfig)  updateInterval
    lvCollector =
      DataCollector Lv.dcName Lv.dcCategory Lv.dcKind
        (StatelessR Lv.dcReport) Nothing activeConfig updateInterval
    cpuLoadCollector =
      DataCollector CPUload.dcName CPUload.dcCategory CPUload.dcKind
        (StatefulR CPUload.dcReport) (Just CPUload.dcUpdate) activeConfig
        updateInterval
    xenCpuLoadCollector =
      DataCollector XenCpuLoad.dcName XenCpuLoad.dcCategory XenCpuLoad.dcKind
        (StatefulR XenCpuLoad.dcReport) (Just XenCpuLoad.dcUpdate) activeConfig
        updateInterval

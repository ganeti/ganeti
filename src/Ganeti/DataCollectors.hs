{-| Definition of the data collectors used by MonD.

-}

{-

Copyright (C) 2014 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.DataCollectors( collectors ) where

import Data.Map (findWithDefault)
import Data.Monoid (mempty)

import qualified Ganeti.DataCollectors.CPUload as CPUload
import qualified Ganeti.DataCollectors.Diskstats as Diskstats
import qualified Ganeti.DataCollectors.Drbd as Drbd
import qualified Ganeti.DataCollectors.InstStatus as InstStatus
import qualified Ganeti.DataCollectors.Lv as Lv
import Ganeti.DataCollectors.Types (DataCollector(..),ReportBuilder(..))
import Ganeti.JSON (GenericContainer(..))
import Ganeti.Objects
import Ganeti.Types

-- | The list of available builtin data collectors.
collectors :: [DataCollector]
collectors =
  [ cpuLoadCollector
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
    activeConfig name cfg =
      let config = fromContainer . clusterDataCollectors $ configCluster cfg
          collectorConfig = findWithDefault mempty name config
      in  dataCollectorActive collectorConfig
    diskStatsCollector =
      DataCollector Diskstats.dcName Diskstats.dcCategory
        Diskstats.dcKind (StatelessR Diskstats.dcReport) Nothing activeConfig
    drdbCollector =
      DataCollector Drbd.dcName Drbd.dcCategory Drbd.dcKind
        (StatelessR Drbd.dcReport) Nothing activeConfig
    instStatusCollector =
      DataCollector InstStatus.dcName InstStatus.dcCategory
        InstStatus.dcKind (StatelessR InstStatus.dcReport) Nothing
        $ xenCluster .&&. activeConfig
    lvCollector =
      DataCollector Lv.dcName Lv.dcCategory Lv.dcKind
        (StatelessR Lv.dcReport) Nothing activeConfig
    cpuLoadCollector =
      DataCollector CPUload.dcName CPUload.dcCategory CPUload.dcKind
        (StatefulR CPUload.dcReport) (Just CPUload.dcUpdate) activeConfig

{-# LANGUAGE BangPatterns #-}

{-| Monitoring daemon backend

This module holds implements the querying of the monitoring daemons
for dynamic utilisation data.

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


module Ganeti.HTools.Backend.MonD
  ( queryAllMonDDCs
  , pMonDData
  ) where

import Control.Monad
import Control.Monad.Writer
import qualified Data.List as L
import qualified Data.IntMap as IntMap
import qualified Data.Map as Map
import Data.Maybe (catMaybes, mapMaybe)
import qualified Data.Set as Set
import Network.Curl
import qualified Text.JSON as J

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Cpu.Types
import qualified Ganeti.DataCollectors.XenCpuLoad as XenCpuLoad
import qualified Ganeti.DataCollectors.CPUload as CPUload
import Ganeti.DataCollectors.Types ( DCReport, DCCategory
                                   , dcReportData, dcReportName
                                   , getCategoryName )
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Loader (ClusterData(..))
import Ganeti.HTools.Types
import Ganeti.HTools.CLI
import Ganeti.JSON (fromJVal, tryFromObj, JSRecord, loadJSArray, maybeParseMap)
import Ganeti.Logging.Lifted (logWarning)
import Ganeti.Utils (exitIfBad)

-- * General definitions

-- | The actual data types for MonD's Data Collectors.
data Report = CPUavgloadReport CPUavgload
            | InstanceCpuReport (Map.Map String Double)

-- | Type describing a data collector basic information.
data DataCollector = DataCollector
  { dName     :: String           -- ^ Name of the data collector
  , dCategory :: Maybe DCCategory -- ^ The name of the category
  , dMkReport :: DCReport -> Maybe Report -- ^ How to parse a monitor report
  , dUse      :: [(Node.Node, Report)]
                 -> (Node.List, Instance.List)
                 -> Result (Node.List, Instance.List)
                 -- ^ How the collector reports are to be used to bring dynamic
                 -- data into a cluster
  }

-- * Node-total CPU load average data collector

-- | Parse a DCReport for the node-total CPU collector.
mkCpuReport :: DCReport -> Maybe Report
mkCpuReport dcr =
  case fromJVal (dcReportData dcr) :: Result CPUavgload of
    Ok cav -> Just $ CPUavgloadReport cav
    Bad _ -> Nothing

-- | Take reports of node CPU values and update a node accordingly.
updateNodeCpuFromReport :: (Node.Node, Report) -> Node.Node
updateNodeCpuFromReport (node, CPUavgloadReport cav) =
  let ct = cavCpuTotal cav
      du = Node.utilLoad node
      du' = du {cpuWeight = ct}
  in node { Node.utilLoad = du' }
updateNodeCpuFromReport (node, _) = node

-- | Update the instance CPU-utilization data, asuming that each virtual
-- CPU contributes equally to the node CPU load.
updateCpuUtilDataFromNode :: Instance.List -> Node.Node -> Instance.List
updateCpuUtilDataFromNode il node =
  let ct = cpuWeight (Node.utilLoad node)
      n_uCpu = Node.uCpu node
      upd inst =
        if Node.idx node == Instance.pNode inst
          then
            let i_vcpus = Instance.vcpus inst
                i_util = ct / fromIntegral n_uCpu * fromIntegral i_vcpus
                i_du = Instance.util inst
                i_du' = i_du {cpuWeight = i_util}
            in inst {Instance.util = i_du'}
          else inst
  in Container.map upd il

-- | Update cluster data from node CPU load reports.
useNodeTotalCPU :: [(Node.Node, Report)]
                -> (Node.List, Instance.List)
                -> Result (Node.List, Instance.List)
useNodeTotalCPU reports (nl, il) =
  let newnodes = map updateNodeCpuFromReport reports
      il' = foldl updateCpuUtilDataFromNode il newnodes
      nl' = zip (Container.keys nl) newnodes
  in return (Container.fromList nl', il')

-- | The node-total CPU collector.
totalCPUCollector :: DataCollector
totalCPUCollector = DataCollector { dName = CPUload.dcName
                                  , dCategory = CPUload.dcCategory
                                  , dMkReport = mkCpuReport
                                  , dUse = useNodeTotalCPU
                                  }

-- * Xen instance CPU-usage collector

-- | Parse results of the Xen-Cpu-load data collector.
mkXenCpuReport :: DCReport -> Maybe Report
mkXenCpuReport =
  liftM InstanceCpuReport . maybeParseMap . dcReportData

-- | Update cluster data based on the per-instance CPU usage
-- reports
useInstanceCpuData :: [(Node.Node, Report)]
                   -> (Node.List, Instance.List)
                   -> Result (Node.List, Instance.List)
useInstanceCpuData reports (nl, il) = do
  let toMap (InstanceCpuReport m) = Just m
      toMap _ = Nothing
  let usage = Map.unions $ mapMaybe (toMap . snd) reports
      missingData = (Set.fromList . map Instance.name $ IntMap.elems il)
                    Set.\\ Map.keysSet usage
  unless (Set.null missingData)
    . Bad . (++) "No CPU information available for "
    . show $ Set.elems missingData
  let updateInstance inst =
        let cpu = Map.lookup (Instance.name inst) usage
            dynU = Instance.util inst
            dynU' = maybe dynU (\c -> dynU { cpuWeight = c }) cpu
        in inst { Instance.util = dynU' }
  let il' = IntMap.map updateInstance il
  let updateNode node =
        let cpu = sum
                  . map (\ idx -> maybe 0 (cpuWeight . Instance.util)
                                  $ IntMap.lookup idx il')
                  $ Node.pList node
            dynU = Node.utilLoad node
            dynU' = dynU { cpuWeight = cpu }
        in node { Node.utilLoad = dynU' }
  let nl' = IntMap.map updateNode nl
  return (nl', il')

-- | Collector for per-instance CPU data as observed by Xen
xenCPUCollector :: DataCollector
xenCPUCollector = DataCollector { dName = XenCpuLoad.dcName
                                , dCategory = XenCpuLoad.dcCategory
                                , dMkReport = mkXenCpuReport
                                , dUse = useInstanceCpuData
                                }

-- * Collector choice

-- | The list of Data Collectors used by hail and hbal.
collectors :: Options -> [DataCollector]
collectors opts
  | optIgnoreDynu opts = []
  | optMonDXen opts = [ xenCPUCollector ]
  | otherwise = [ totalCPUCollector ]

-- * Querying infrastructure

-- | Return the data from correct combination of a Data Collector
-- and a DCReport.
mkReport :: DataCollector -> Maybe DCReport -> Maybe Report
mkReport dc = (>>= dMkReport dc)

-- | MonDs Data parsed by a mock file. Representing (node name, list of reports
-- produced by MonDs Data Collectors).
type MonDData = (String, [DCReport])

-- | A map storing MonDs data.
type MapMonDData = Map.Map String [DCReport]

-- | Get data report for the specified Data Collector and Node from the map.
fromFile :: DataCollector -> Node.Node -> MapMonDData -> Maybe DCReport
fromFile dc node m =
  let matchDCName dcr = dName dc == dcReportName dcr
  in maybe Nothing (L.find matchDCName) $ Map.lookup (Node.name node) m

-- | Get Category Name.
getDCCName :: Maybe DCCategory -> String
getDCCName dcc =
  case dcc of
    Nothing -> "default"
    Just c -> getCategoryName c

-- | Prepare url to query a single collector.
prepareUrl :: DataCollector -> Node.Node -> URLString
prepareUrl dc node =
  Node.name node ++ ":" ++ show C.defaultMondPort ++ "/"
  ++ show C.mondLatestApiVersion ++ "/report/" ++
  getDCCName (dCategory dc) ++ "/" ++ dName dc

-- | Query a specified MonD for a Data Collector.
fromCurl :: DataCollector -> Node.Node -> IO (Maybe DCReport)
fromCurl dc node = do
  (code, !body) <-  curlGetString (prepareUrl dc node) []
  case code of
    CurlOK ->
      case J.decodeStrict body :: J.Result DCReport of
        J.Ok r -> return $ Just r
        J.Error _ -> return Nothing
    _ -> do
      logWarning $ "Failed to contact node's " ++ Node.name node
                   ++ " MonD for DC " ++ dName dc
      return Nothing

-- | Parse a node's JSON record.
pMonDN :: JSRecord -> Result MonDData
pMonDN a = do
  node <- tryFromObj "Parsing node's name" a "node"
  reports <- tryFromObj "Parsing node's reports" a "reports"
  return (node, reports)

-- | Parse MonD data file contents.
pMonDData :: String -> Result [MonDData]
pMonDData input =
  loadJSArray "Parsing MonD's answer" input >>=
  mapM (pMonDN . J.fromJSObject)

-- | Query a single MonD for a single Data Collector.
queryAMonD :: Maybe MapMonDData -> DataCollector -> Node.Node
              -> IO (Maybe Report)
queryAMonD m dc node =
  liftM (mkReport dc) $ case m of
      Nothing -> fromCurl dc node
      Just m' -> return $ fromFile dc node m'

-- | Query all MonDs for a single Data Collector. Return the updated
-- cluster, as well as a bit inidicating wether the collector succeeded.
queryAllMonDs :: Maybe MapMonDData -> (Node.List, Instance.List)
                 -> DataCollector -> WriterT All IO (Node.List, Instance.List)
queryAllMonDs m (nl, il) dc = do
  elems <- liftIO $ mapM (queryAMonD m dc) (Container.elems nl)
  let elems' = catMaybes elems
  if length elems == length elems'
    then
      let results = zip (Container.elems nl) elems'
      in case dUse dc results (nl, il) of
        Ok (nl', il') -> return (nl', il')
        Bad s -> do
          logWarning s
          tell $ All False
          return (nl, il)
    else do
      logWarning $ "Didn't receive an answer by all MonDs, " ++ dName dc
                   ++ "'s data will be ignored."
      tell $ All False
      return (nl,il)

-- | Query all MonDs for all Data Collector. Return the cluster enriched
-- by dynamic data, as well as a bit indicating wether all collectors
-- could be queried successfully.
queryAllMonDDCs :: ClusterData -> Options -> WriterT All IO ClusterData
queryAllMonDDCs cdata opts = do
  map_mDD <-
    case optMonDFile opts of
      Nothing -> return Nothing
      Just fp -> do
        monDData_contents <- liftIO $ readFile fp
        monDData <- liftIO . exitIfBad "can't parse MonD data"
                    . pMonDData $ monDData_contents
        return . Just $ Map.fromList monDData
  let (ClusterData _ nl il _ _) = cdata
  (nl', il') <- foldM (queryAllMonDs map_mDD) (nl, il) (collectors opts)
  return $ cdata {cdNodes = nl', cdInstances = il'}

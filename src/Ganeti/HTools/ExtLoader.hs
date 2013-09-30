{-# LANGUAGE BangPatterns #-}

{-| External data loader.

This module holds the external data loading, and thus is the only one
depending (via the specialized Text\/Rapi\/Luxi modules) on the actual
libraries implementing the low-level protocols.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Ganeti.HTools.ExtLoader
  ( loadExternalData
  , commonSuffix
  , maybeSaveData
  , queryAllMonDDCs
  , pMonDData
  ) where

import Control.Monad
import Control.Exception
import Data.Maybe (isJust, fromJust, catMaybes)
import Network.Curl
import System.FilePath
import System.IO
import System.Time (getClockTime)
import Text.Printf (hPrintf)

import qualified Text.JSON as J
import qualified Data.Map as Map
import qualified Data.List as L

import qualified Ganeti.Constants as C
import qualified Ganeti.DataCollectors.CPUload as CPUload
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Backend.Luxi as Luxi
import qualified Ganeti.HTools.Backend.Rapi as Rapi
import qualified Ganeti.HTools.Backend.Simu as Simu
import qualified Ganeti.HTools.Backend.Text as Text
import qualified Ganeti.HTools.Backend.IAlloc as IAlloc
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Loader (mergeData, checkData, ClusterData(..)
                            , commonSuffix, clearDynU)

import Ganeti.BasicTypes
import Ganeti.Cpu.Types
import Ganeti.DataCollectors.Types
import Ganeti.HTools.Types
import Ganeti.HTools.CLI
import Ganeti.JSON
import Ganeti.Logging (logWarning)
import Ganeti.Utils (sepSplit, tryRead, exitIfBad, exitWhen)

-- | Error beautifier.
wrapIO :: IO (Result a) -> IO (Result a)
wrapIO = handle (\e -> return . Bad . show $ (e::IOException))

-- | Parses a user-supplied utilisation string.
parseUtilisation :: String -> Result (String, DynUtil)
parseUtilisation line =
  case sepSplit ' ' line of
    [name, cpu, mem, dsk, net] ->
      do
        rcpu <- tryRead name cpu
        rmem <- tryRead name mem
        rdsk <- tryRead name dsk
        rnet <- tryRead name net
        let du = DynUtil { cpuWeight = rcpu, memWeight = rmem
                         , dskWeight = rdsk, netWeight = rnet }
        return (name, du)
    _ -> Bad $ "Cannot parse line " ++ line

-- | External tool data loader from a variety of sources.
loadExternalData :: Options
                 -> IO ClusterData
loadExternalData opts = do
  let mhost = optMaster opts
      lsock = optLuxi opts
      tfile = optDataFile opts
      simdata = optNodeSim opts
      iallocsrc = optIAllocSrc opts
      setRapi = mhost /= ""
      setLuxi = isJust lsock
      setSim = (not . null) simdata
      setFile = isJust tfile
      setIAllocSrc = isJust iallocsrc
      allSet = filter id [setRapi, setLuxi, setFile]
      exTags = case optExTags opts of
                 Nothing -> []
                 Just etl -> map (++ ":") etl
      selInsts = optSelInst opts
      exInsts = optExInst opts

  exitWhen (length allSet > 1) "Only one of the rapi, luxi, and data\
                               \ files options should be given."

  util_contents <- maybe (return "") readFile (optDynuFile opts)
  util_data <- exitIfBad "can't parse utilisation data" .
               mapM parseUtilisation $ lines util_contents
  input_data <-
    case () of
      _ | setRapi -> wrapIO $ Rapi.loadData mhost
        | setLuxi -> wrapIO . Luxi.loadData $ fromJust lsock
        | setSim -> Simu.loadData simdata
        | setFile -> wrapIO . Text.loadData $ fromJust tfile
        | setIAllocSrc -> wrapIO . IAlloc.loadData $ fromJust iallocsrc
        | otherwise -> return $ Bad "No backend selected! Exiting."
  now <- getClockTime

  let ignoreDynU = optIgnoreDynu opts
      eff_u = if ignoreDynU then [] else util_data
      ldresult = input_data >>= (if ignoreDynU then clearDynU else return)
                            >>= mergeData eff_u exTags selInsts exInsts now
  cdata <- exitIfBad "failed to load data, aborting" ldresult
  cdata' <- if optMonD opts then queryAllMonDDCs cdata opts else return cdata
  let (fix_msgs, nl) = checkData (cdNodes cdata') (cdInstances cdata')

  unless (optVerbose opts == 0) $ maybeShowWarnings fix_msgs

  return cdata' {cdNodes = nl}

-- | Function to save the cluster data to a file.
maybeSaveData :: Maybe FilePath -- ^ The file prefix to save to
              -> String         -- ^ The suffix (extension) to add
              -> String         -- ^ Informational message
              -> ClusterData    -- ^ The cluster data
              -> IO ()
maybeSaveData Nothing _ _ _ = return ()
maybeSaveData (Just path) ext msg cdata = do
  let adata = Text.serializeCluster cdata
      out_path = path <.> ext
  writeFile out_path adata
  hPrintf stderr "The cluster state %s has been written to file '%s'\n"
          msg out_path

-- | Type describing a data collector basic information.
data DataCollector = DataCollector
  { dName     :: String           -- ^ Name of the data collector
  , dCategory :: Maybe DCCategory -- ^ The name of the category
  }

-- | The actual data types for MonD's Data Collectors.
data Report = CPUavgloadReport CPUavgload

-- | The list of Data Collectors used by hail and hbal.
collectors :: Options -> [DataCollector]
collectors opts =
  if optIgnoreDynu opts
    then []
    else [ DataCollector CPUload.dcName CPUload.dcCategory ]

-- | MonDs Data parsed by a mock file. Representing (node name, list of reports
-- produced by MonDs Data Collectors).
type MonDData = (String, [DCReport])

-- | A map storing MonDs data.
type MapMonDData = Map.Map String [DCReport]

-- | Parse MonD data file contents.
pMonDData :: String -> Result [MonDData]
pMonDData input =
  loadJSArray "Parsing MonD's answer" input >>=
  mapM (pMonDN . J.fromJSObject)

-- | Parse a node's JSON record.
pMonDN :: JSRecord -> Result MonDData
pMonDN a = do
  node <- tryFromObj "Parsing node's name" a "node"
  reports <- tryFromObj "Parsing node's reports" a "reports"
  return (node, reports)

-- | Query all MonDs for all Data Collector.
queryAllMonDDCs :: ClusterData -> Options -> IO ClusterData
queryAllMonDDCs cdata opts = do
  map_mDD <-
    case optMonDFile opts of
      Nothing -> return Nothing
      Just fp -> do
        monDData_contents <- readFile fp
        monDData <- exitIfBad "can't parse MonD data"
                    . pMonDData $ monDData_contents
        return . Just $ Map.fromList monDData
  let (ClusterData _ nl il _ _) = cdata
  (nl', il') <- foldM (queryAllMonDs map_mDD) (nl, il) (collectors opts)
  return $ cdata {cdNodes = nl', cdInstances = il'}

-- | Query all MonDs for a single Data Collector.
queryAllMonDs :: Maybe MapMonDData -> (Node.List, Instance.List)
                 -> DataCollector -> IO (Node.List, Instance.List)
queryAllMonDs m (nl, il) dc = do
  elems <- mapM (queryAMonD m dc) (Container.elems nl)
  let elems' = catMaybes elems
  if length elems == length elems'
    then
      let il' = foldl updateUtilData il elems'
          nl' = zip (Container.keys nl) elems'
      in return (Container.fromList nl', il')
    else do
      logWarning $ "Didn't receive an answer by all MonDs, " ++ dName dc
                   ++ "'s data will be ignored."
      return (nl,il)

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

-- | Return the data from correct combination of a Data Collector
-- and a DCReport.
mkReport :: DataCollector -> Maybe DCReport -> Maybe Report
mkReport dc dcr =
  case dcr of
    Nothing -> Nothing
    Just dcr' ->
      case () of
           _ | CPUload.dcName == dName dc ->
                 case fromJVal (dcReportData dcr') :: Result CPUavgload of
                   Ok cav -> Just $ CPUavgloadReport cav
                   Bad _ -> Nothing
             | otherwise -> Nothing

-- | Get data report for the specified Data Collector and Node from the map.
fromFile :: DataCollector -> Node.Node -> MapMonDData -> Maybe DCReport
fromFile dc node m =
  let matchDCName dcr = dName dc == dcReportName dcr
  in maybe Nothing (L.find matchDCName) $ Map.lookup (Node.name node) m

-- | Query a MonD for a single Data Collector.
queryAMonD :: Maybe MapMonDData -> DataCollector -> Node.Node
              -> IO (Maybe Node.Node)
queryAMonD m dc node = do
  dcReport <-
    case m of
      Nothing -> fromCurl dc node
      Just m' -> return $ fromFile dc node m'
  case mkReport dc dcReport of
    Nothing -> return Nothing
    Just report ->
      case report of
        CPUavgloadReport cav ->
          let ct = cavCpuTotal cav
              du = Node.utilLoad node
              du' = du {cpuWeight = ct}
          in return $ Just node {Node.utilLoad = du'}

-- | Update utilization data.
updateUtilData :: Instance.List -> Node.Node -> Instance.List
updateUtilData il node =
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

-- | Prepare url to query a single collector.
prepareUrl :: DataCollector -> Node.Node -> URLString
prepareUrl dc node =
  Node.name node ++ ":" ++ show C.defaultMondPort ++ "/"
  ++ show C.mondLatestApiVersion ++ "/report/" ++
  getDCCName (dCategory dc) ++ "/" ++ dName dc

-- | Get Category Name.
getDCCName :: Maybe DCCategory -> String
getDCCName dcc =
  case dcc of
    Nothing -> "default"
    Just c -> getCategoryName c

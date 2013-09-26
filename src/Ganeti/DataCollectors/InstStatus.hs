{-| Instance status data collector.

-}

{-

Copyright (C) 2013 Google Inc.

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

module Ganeti.DataCollectors.InstStatus
  ( main
  , options
  , arguments
  , dcName
  , dcVersion
  , dcFormatVersion
  , dcCategory
  , dcKind
  , dcReport
  ) where


import Control.Exception.Base
import Data.List
import Data.Maybe
import qualified Data.Map as Map
import Network.BSD (getHostName)
import qualified Text.JSON as J

import Ganeti.BasicTypes as BT
import Ganeti.Confd.ClientFunctions
import Ganeti.Common
import Ganeti.DataCollectors.CLI
import Ganeti.DataCollectors.InstStatusTypes
import Ganeti.DataCollectors.Types
import Ganeti.Hypervisor.Xen
import Ganeti.Hypervisor.Xen.Types
import Ganeti.Logging
import Ganeti.Objects
import Ganeti.Path
import Ganeti.Types
import Ganeti.Utils


-- | The name of this data collector.
dcName :: String
dcName = "inst-status-xen"

-- | The version of this data collector.
dcVersion :: DCVersion
dcVersion = DCVerBuiltin

-- | The version number for the data format of this data collector.
dcFormatVersion :: Int
dcFormatVersion = 1

-- | The category of this data collector.
dcCategory :: Maybe DCCategory
dcCategory = Just DCInstance

-- | The kind of this data collector.
dcKind :: DCKind
dcKind = DCKStatus

-- | The report of this data collector.
dcReport :: IO DCReport
dcReport = buildInstStatusReport Nothing Nothing

-- * Command line options

options :: IO [OptType]
options = return
  [ oConfdAddr
  , oConfdPort
  ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Try to get the reason trail for an instance. In case it is not possible,
-- log the failure and return an empty list instead.
getReasonTrail :: String -> IO ReasonTrail
getReasonTrail instanceName = do
  fileName <- getInstReasonFilename instanceName
  content <- try $ readFile fileName
  case content of
    Left e -> do
      logWarning $
        "Unable to open the reason trail for instance " ++ instanceName ++
        " expected at " ++ fileName ++ ": " ++ show (e :: IOException)
      return []
    Right trailString ->
      case J.decode trailString of
        J.Ok t -> return t
        J.Error msg -> do
          logWarning $ "Unable to parse the reason trail: " ++ msg
          return []

-- | Determine the value of the status field for the report of one instance
computeStatusField :: AdminState -> ActualState -> DCStatus
computeStatusField AdminDown actualState =
  if actualState `notElem` [ActualShutdown, ActualDying]
    then DCStatus DCSCBad "The instance is not stopped as it should be"
    else DCStatus DCSCOk ""
computeStatusField AdminUp ActualHung =
  DCStatus DCSCUnknown "Instance marked as running, but it appears to be hung"
computeStatusField AdminUp actualState =
  if actualState `notElem` [ActualRunning, ActualBlocked]
    then DCStatus DCSCBad "The instance is not running as it should be"
    else DCStatus DCSCOk ""
computeStatusField AdminOffline _ =
  -- FIXME: The "offline" status seems not to be used anywhere in the source
  -- code, but it is defined, so we have to consider it anyway here.
  DCStatus DCSCUnknown "The instance is marked as offline"

-- Builds the status of an instance using runtime information about the Xen
-- Domains, their uptime information and the static information provided by
-- the ConfD server.
buildStatus :: Map.Map String Domain -> Map.Map Int UptimeInfo -> Instance
  -> IO InstStatus
buildStatus domains uptimes inst = do
  let name = instName inst
      currDomain = Map.lookup name domains
      idNum = fmap domId currDomain
      currUInfo = idNum >>= (`Map.lookup` uptimes)
      uptime = fmap uInfoUptime currUInfo
      adminState = instAdminState inst
      actualState =
        if adminState == AdminDown && isNothing currDomain
          then ActualShutdown
          else case currDomain of
            (Just dom@(Domain _ _ _ _ (Just isHung))) ->
              if isHung
                then ActualHung
                else domState dom
            _ -> ActualUnknown
      status = computeStatusField adminState actualState
  trail <- getReasonTrail name
  return $
    InstStatus
      name
      (instUuid inst)
      adminState
      actualState
      uptime
      (instMtime inst)
      trail
      status

-- | Compute the status code and message, given the current DRBD data
-- The final state will have the code corresponding to the worst code of
-- all the devices, and the error message given from the concatenation of the
-- non-empty error messages.
computeGlobalStatus :: [InstStatus] -> DCStatus
computeGlobalStatus instStatusList =
  let dcstatuses = map iStatStatus instStatusList
      statuses = map (\s -> (dcStatusCode s, dcStatusMessage s)) dcstatuses
      (code, strList) = foldr mergeStatuses (DCSCOk, [""]) statuses
  in DCStatus code $ intercalate "\n" strList

-- | Build the report of this data collector, containing all the information
-- about the status of the instances.
buildInstStatusReport :: Maybe String -> Maybe Int -> IO DCReport
buildInstStatusReport srvAddr srvPort = do
  node <- getHostName
  answer <- getInstances node srvAddr srvPort
  inst <- exitIfBad "Can't get instance info from ConfD" answer
  d <- getInferredDomInfo
  reportData <-
    case d of
      BT.Ok domains -> do
        uptimes <- getUptimeInfo
        let primaryInst =  fst inst
        iStatus <- mapM (buildStatus domains uptimes) primaryInst
        let globalStatus = computeGlobalStatus iStatus
        return $ ReportData iStatus globalStatus
      BT.Bad m ->
        return . ReportData [] . DCStatus DCSCBad $
          "Unable to receive the list of instances: " ++ m
  let jsonReport = J.showJSON reportData
  buildReport dcName dcVersion dcFormatVersion dcCategory dcKind jsonReport

-- | Main function.
main :: Options -> [String] -> IO ()
main opts _ = do
  report <- buildInstStatusReport (optConfdAddr opts) (optConfdPort opts)
  putStrLn $ J.encode report

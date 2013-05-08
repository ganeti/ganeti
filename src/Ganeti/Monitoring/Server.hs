{-# LANGUAGE OverloadedStrings #-}

{-| Implementation of the Ganeti confd server functionality.

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

module Ganeti.Monitoring.Server
  ( main
  , checkMain
  , prepMain
  ) where

import Control.Applicative
import Control.Monad
import Control.Monad.IO.Class
import Data.ByteString.Char8 hiding (map, filter, find)
import Data.List
import Snap.Core
import Snap.Http.Server
import qualified Text.JSON as J

import qualified Ganeti.BasicTypes as BT
import Ganeti.Daemon
import qualified Ganeti.DataCollectors.Drbd as Drbd
import qualified Ganeti.DataCollectors.InstStatus as InstStatus
import Ganeti.DataCollectors.Types
import qualified Ganeti.Constants as C

-- * Types and constants definitions

-- | Type alias for checkMain results.
type CheckResult = ()

-- | Type alias for prepMain results.
type PrepResult = Config Snap ()

-- | Version of the latest supported http API.
latestAPIVersion :: Int
latestAPIVersion = 1

-- | Type describing a data collector basic information
data DataCollector = DataCollector
  { dName     :: String           -- ^ Name of the data collector
  , dCategory :: Maybe DCCategory -- ^ Category (storage, instance, ecc)
                                  --   of the collector
  , dKind     :: DCKind           -- ^ Kind (performance or status reporting) of
                                  --   the data collector
  , dReport   :: IO DCReport      -- ^ Report produced by the collector
  }

-- | The list of available builtin data collectors.
collectors :: [DataCollector]
collectors =
  [ DataCollector Drbd.dcName Drbd.dcCategory Drbd.dcKind Drbd.dcReport
  , DataCollector InstStatus.dcName InstStatus.dcCategory InstStatus.dcKind
      InstStatus.dcReport
  ]

-- * Configuration handling

-- | The default configuration for the HTTP server.
defaultHttpConf :: Config Snap ()
defaultHttpConf =
  setAccessLog (ConfigFileLog C.daemonsExtraLogfilesGanetiMondAccess) .
  setCompression False .
  setErrorLog (ConfigFileLog C.daemonsExtraLogfilesGanetiMondError) $
  setVerbose False
  emptyConfig

-- * Helper functions

-- | Check function for the monitoring agent.
checkMain :: CheckFn CheckResult
checkMain _ = return $ Right ()

-- | Prepare function for monitoring agent.
prepMain :: PrepFn CheckResult PrepResult
prepMain opts _ =
  return $
    setPort (maybe C.defaultMondPort fromIntegral (optPort opts))
      defaultHttpConf

-- * Query answers

-- | Reply to the supported API version numbers query.
versionQ :: Snap ()
versionQ = writeBS . pack $ J.encode [latestAPIVersion]

-- | Version 1 of the monitoring HTTP API.
version1Api :: Snap ()
version1Api =
  let returnNull = writeBS . pack $ J.encode J.JSNull :: Snap ()
  in ifTop returnNull <|>
     route
       [ ("list", listHandler)
       , ("report", reportHandler)
       ]

-- | Get the JSON representation of a data collector to be used in the collector
-- list.
dcListItem :: DataCollector -> J.JSValue
dcListItem dc =
  J.JSArray
    [ J.showJSON $ dName dc
    , maybe J.JSNull J.showJSON $ dCategory dc
    , J.showJSON $ dKind dc
    ]

-- | Handler for returning lists.
listHandler :: Snap ()
listHandler =
  dir "collectors" . writeBS . pack . J.encode $ map dcListItem collectors

-- | Handler for returning data collector reports.
reportHandler :: Snap ()
reportHandler =
  route
    [ ("all", allReports)
    , (":category/:collector", oneReport)
    ] <|>
  errorReport

-- | Return the report of all the available collectors.
allReports :: Snap ()
allReports = do
  reports <- mapM (liftIO . dReport) collectors
  writeBS . pack . J.encode $ reports

-- | Returns a category given its name.
-- If "collector" is given as the name, the collector has no category, and
-- Nothing will be returned.
catFromName :: String -> BT.Result (Maybe DCCategory)
catFromName "instance"   = BT.Ok $ Just DCInstance
catFromName "storage"    = BT.Ok $ Just DCStorage
catFromName "daemon"     = BT.Ok $ Just DCDaemon
catFromName "hypervisor" = BT.Ok $ Just DCHypervisor
catFromName "default"    = BT.Ok Nothing
catFromName _            = BT.Bad "No such category"

errorReport :: Snap ()
errorReport = do
  modifyResponse $ setResponseStatus 404 "Not found"
  writeBS "Unable to produce a report for the requested resource"

error404 :: Snap ()
error404 = do
  modifyResponse $ setResponseStatus 404 "Not found"
  writeBS "Resource not found"

-- | Return the report of one collector
oneReport :: Snap ()
oneReport = do
  categoryName <- fmap (maybe mzero unpack) $ getParam "category"
  collectorName <- fmap (maybe mzero unpack) $ getParam "collector"
  category <-
    case catFromName categoryName of
      BT.Ok cat -> return cat
      BT.Bad msg -> fail msg
  collector <-
    case
      find (\col -> collectorName == dName col) $
        filter (\c -> category == dCategory c) collectors of
      Just col -> return col
      Nothing -> fail "Unable to find the requested collector"
  report <- liftIO $ dReport collector
  writeBS . pack . J.encode $ report

-- | The function implementing the HTTP API of the monitoring agent.
monitoringApi :: Snap ()
monitoringApi =
  ifTop versionQ <|>
  dir "1" version1Api <|>
  error404

-- | Main function.
main :: MainFn CheckResult PrepResult
main _ _ httpConf =
  httpServe httpConf $ method GET monitoringApi

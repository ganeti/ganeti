{-# LANGUAGE OverloadedStrings #-}

{-| Implementation of the Ganeti confd server functionality.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.Monitoring.Server
  ( main
  , checkMain
  , prepMain
  , DataCollector(..)
  ) where

import Control.Applicative
import Control.Monad
import Control.Monad.IO.Class
import Data.ByteString.Char8 (pack, unpack)
import Data.Maybe (fromMaybe)
import Data.List (find)
import Data.Monoid (mempty)
import qualified Data.Map as Map
import Snap.Core
import Snap.Http.Server
import qualified Text.JSON as J
import Control.Concurrent

import qualified Ganeti.BasicTypes as BT
import Ganeti.Confd.Client
import qualified Ganeti.Confd.Types as CT
import Ganeti.Daemon
import qualified Ganeti.DataCollectors as DC
import Ganeti.DataCollectors.Types
import qualified Ganeti.JSON as GJ
import Ganeti.Objects (DataCollectorConfig(..))
import qualified Ganeti.Constants as C
import Ganeti.Runtime

-- * Types and constants definitions

-- | Type alias for checkMain results.
type CheckResult = ()

-- | Type alias for prepMain results.
type PrepResult = Config Snap ()

-- | Version of the latest supported http API.
latestAPIVersion :: Int
latestAPIVersion = C.mondLatestApiVersion

-- * Configuration handling

-- | The default configuration for the HTTP server.
defaultHttpConf :: FilePath -> FilePath -> Config Snap ()
defaultHttpConf accessLog errorLog =
  setAccessLog (ConfigFileLog accessLog) .
  setCompression False .
  setErrorLog (ConfigFileLog errorLog) $
  setVerbose False
  emptyConfig

-- * Helper functions

-- | Check function for the monitoring agent.
checkMain :: CheckFn CheckResult
checkMain _ = return $ Right ()

-- | Prepare function for monitoring agent.
prepMain :: PrepFn CheckResult PrepResult
prepMain opts _ = do
  accessLog <- daemonsExtraLogFile GanetiMond AccessLog
  errorLog <- daemonsExtraLogFile GanetiMond ErrorLog
  return .
    setPort
      (maybe C.defaultMondPort fromIntegral (optPort opts)) .
    maybe id (setBind . pack) (optBindAddress opts)
    $ defaultHttpConf accessLog errorLog

-- * Query answers

-- | Reply to the supported API version numbers query.
versionQ :: Snap ()
versionQ = writeBS . pack $ J.encode [latestAPIVersion]

-- | Version 1 of the monitoring HTTP API.
version1Api :: MVar CollectorMap -> Snap ()
version1Api mvar =
  let returnNull = writeBS . pack $ J.encode J.JSNull :: Snap ()
  in ifTop returnNull <|>
     route
       [ ("list", listHandler)
       , ("report", reportHandler mvar)
       ]

collectorConfigs :: IO (String -> DataCollectorConfig)
collectorConfigs = do
    confdClient <- getConfdClient Nothing Nothing
    response <- query confdClient CT.ReqDataCollectors CT.EmptyQuery
    return $ lookupConfig response
  where
    lookupConfig :: Maybe CT.ConfdReply -> String -> DataCollectorConfig
    lookupConfig response name = fromMaybe (mempty :: DataCollectorConfig) $ do
      confdReply <- response
      let answer = CT.confdReplyAnswer confdReply
      case J.readJSON answer :: J.Result (GJ.Container DataCollectorConfig) of
        J.Error _ -> Nothing
        J.Ok container -> GJ.lookupContainer Nothing name container

activeCollectors :: IO [DataCollector]
activeCollectors = do
  configs <- collectorConfigs
  return $ filter (dataCollectorActive . configs . dName) DC.collectors

-- | Get the JSON representation of a data collector to be used in the collector
-- list.
dcListItem :: DataCollector -> J.JSValue
dcListItem dc =
  J.JSArray
    [ J.showJSON $ dName dc
    , maybe defaultCategory J.showJSON $ dCategory dc
    , J.showJSON $ dKind dc
    ]
    where
      defaultCategory = J.showJSON C.mondDefaultCategory

-- | Handler for returning lists.
listHandler :: Snap ()
listHandler = dir "collectors" $ do
  collectors' <- liftIO activeCollectors
  writeBS . pack . J.encode $ map dcListItem collectors'


-- | Handler for returning data collector reports.
reportHandler :: MVar CollectorMap -> Snap ()
reportHandler mvar =
  route
    [ ("all", allReports mvar)
    , (":category/:collector", oneReport mvar)
    ] <|>
  errorReport

-- | Return the report of all the available collectors.
allReports :: MVar CollectorMap -> Snap ()
allReports mvar = do
  collectors' <- liftIO activeCollectors
  reports <- mapM (liftIO . getReport mvar) collectors'
  writeBS . pack . J.encode $ reports

-- | Takes the CollectorMap and a DataCollector and returns the report for this
-- collector.
getReport :: MVar CollectorMap -> DataCollector -> IO DCReport
getReport mvar collector =
  case dReport collector of
    StatelessR r -> r
    StatefulR r -> do
      colData <- getColData (dName collector) mvar
      r colData

-- | Returns the data for the corresponding collector.
getColData :: String -> MVar CollectorMap -> IO (Maybe CollectorData)
getColData name mvar = do
  m <- readMVar mvar
  return $ Map.lookup name m

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

-- | Return the report of one collector.
oneReport :: MVar CollectorMap -> Snap ()
oneReport mvar = do
  collectors' <- liftIO activeCollectors
  categoryName <- maybe mzero unpack <$> getParam "category"
  collectorName <- maybe mzero unpack <$> getParam "collector"
  category <-
    case catFromName categoryName of
      BT.Ok cat -> return cat
      BT.Bad msg -> fail msg
  collector <-
    case
      find (\col -> collectorName == dName col) $
        filter (\c -> category == dCategory c) collectors' of
      Just col -> return col
      Nothing -> fail "Unable to find the requested collector"
  dcr <- liftIO $ getReport mvar collector
  writeBS . pack . J.encode $ dcr

-- | The function implementing the HTTP API of the monitoring agent.
monitoringApi :: MVar CollectorMap -> Snap ()
monitoringApi mvar =
  ifTop versionQ <|>
  dir "1" (version1Api mvar) <|>
  error404

-- | The function collecting data for each data collector providing a dcUpdate
-- function.
collect :: CollectorMap -> DataCollector -> IO CollectorMap
collect m collector =
  case dUpdate collector of
    Nothing -> return m
    Just update -> do
      let name = dName collector
          existing = Map.lookup name m
      new_data <- update existing
      return $ Map.insert name new_data m

-- | Invokes collect for each data collector.
collection :: CollectorMap -> IO CollectorMap
collection m = liftIO activeCollectors >>= foldM collect m

-- | The thread responsible for the periodical collection of data for each data
-- data collector.
collectord :: MVar CollectorMap -> IO ()
collectord mvar =
  forever $ do
    m <- takeMVar mvar
    m' <- collection m
    putMVar mvar m'
    threadDelay $ 10^(6 :: Int) * C.mondTimeInterval

-- | Main function.
main :: MainFn CheckResult PrepResult
main _ _ httpConf = do
  mvar <- newMVar Map.empty
  _ <- forkIO $ collectord mvar
  httpServe httpConf . method GET $ monitoringApi mvar

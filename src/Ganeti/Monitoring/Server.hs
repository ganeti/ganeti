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
import Snap.Core
import Snap.Http.Server
import Data.ByteString.Char8
import qualified Text.JSON as J

import Ganeti.Daemon
import qualified Ganeti.Constants as C

-- * Types and constants definitions

-- | Type alias for checkMain results.
type CheckResult = ()

-- | Type alias for prepMain results.
type PrepResult = Config Snap ()

-- | Version of the latest supported http API.
latestAPIVersion :: Int
latestAPIVersion = 1

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

-- | Handler for returning lists.
listHandler :: Snap ()
listHandler =
  dir "collectors" $ writeText "TODO: return the list of collectors"

-- | Handler for returning data collector reports.
reportHandler :: Snap ()
reportHandler =
  route
    [ ("all", allReports)
    , (":category/:collector", oneReport)
    ]

-- | Return the report of all the available collectors
allReports :: Snap ()
allReports = writeText "TODO: return the reports of all the collectors"

-- | Return the report of one collector
oneReport :: Snap ()
oneReport = do
  category <- fmap (maybe mzero unpack) $ getParam "category"
  collector <- fmap (maybe mzero unpack) $ getParam "collector"
  writeBS . pack $
    "TODO: return the report for collector " ++ category
      ++ "/" ++ collector

-- | The function implementing the HTTP API of the monitoring agent.
-- TODO: Currently it only replies to the API version query: implement all the
-- missing features.
monitoringApi :: Snap ()
monitoringApi =
  ifTop versionQ <|>
  dir "1" version1Api

-- | Main function.
main :: MainFn CheckResult PrepResult
main _ _ httpConf =
  httpServe httpConf $ method GET monitoringApi

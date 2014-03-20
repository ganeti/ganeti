{-| Web server for the metadata daemon.

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

module Ganeti.Metad.WebServer (start) where

import Control.Applicative
import Control.Concurrent (MVar, readMVar)
import Control.Monad.IO.Class (liftIO)
import qualified Data.Map as Map
import qualified Data.ByteString.Char8 as ByteString (pack, unpack)
import Snap.Core
import Snap.Http.Server
import qualified Text.JSON as JSON

import Ganeti.Daemon
import qualified Ganeti.Constants as Constants
import qualified Ganeti.Logging as Logging
import Ganeti.Runtime (GanetiDaemon(..), ExtraLogReason(..))
import qualified Ganeti.Runtime as Runtime

import Ganeti.Metad.Types (InstanceParams)

type MetaM = Snap ()

error404 :: MetaM
error404 = do
  modifyResponse . setResponseStatus 404 $ ByteString.pack "Not found"
  writeBS $ ByteString.pack "Resource not found"

handleMetadata
  :: MVar InstanceParams -> Method -> String -> String -> String -> MetaM
handleMetadata _ GET  "ganeti" "latest" "meta_data.json" =
  liftIO $ Logging.logInfo "ganeti metadata"
handleMetadata params GET  "ganeti" "latest" "os/parameters.json" =
  do remoteAddr <- ByteString.unpack . rqRemoteAddr <$> getRequest
     instanceParams <- liftIO $ do
       Logging.logInfo $ "ganeti OS parameter for " ++ show remoteAddr
       readMVar params
     case Map.lookup remoteAddr instanceParams of
       Nothing ->
         error404
       Just osParams ->
         writeBS .
         ByteString.pack .
         JSON.encode $ osParams
handleMetadata _ GET  "ganeti" "latest" "read" =
  liftIO $ Logging.logInfo "ganeti READ"
handleMetadata _ POST "ganeti" "latest" "write" =
  liftIO $ Logging.logInfo "ganeti WRITE"
handleMetadata _ _ _ _ _ =
  error404

routeMetadata :: MVar InstanceParams -> MetaM
routeMetadata params =
  route [ (providerRoute1, dispatchMetadata)
        , (providerRoute2, dispatchMetadata)
        ] <|> dispatchMetadata
  where provider = "provider"
        version  = "version"

        providerRoute1 = ByteString.pack $ ':':provider ++ "/" ++ ':':version
        providerRoute2 = ByteString.pack $ ':':version

        getParamString :: String -> Snap String
        getParamString =
          fmap (maybe "" ByteString.unpack) . getParam . ByteString.pack

        dispatchMetadata =
          do m <- rqMethod <$> getRequest
             p <- getParamString provider
             v <- getParamString version
             r <- ByteString.unpack . rqPathInfo <$> getRequest
             handleMetadata params m p v r

defaultHttpConf :: DaemonOptions -> FilePath -> FilePath -> Config Snap ()
defaultHttpConf opts accessLog errorLog =
  maybe id (setBind . ByteString.pack) (optBindAddress opts) .
  setAccessLog (ConfigFileLog accessLog) .
  setCompression False .
  setErrorLog (ConfigFileLog errorLog) .
  setPort (maybe Constants.defaultMetadPort fromIntegral (optPort opts)) .
  setVerbose False $
  emptyConfig

start :: DaemonOptions -> MVar InstanceParams -> IO ()
start opts params = do
  accessLog <- Runtime.daemonsExtraLogFile GanetiMetad AccessLog
  errorLog <- Runtime.daemonsExtraLogFile GanetiMetad ErrorLog
  httpServe (defaultHttpConf opts accessLog errorLog) (routeMetadata params)

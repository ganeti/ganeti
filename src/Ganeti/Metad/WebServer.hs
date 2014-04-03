{-# LANGUAGE FlexibleContexts #-}
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
import Control.Monad.Error.Class (MonadError, catchError, throwError)
import Control.Monad.IO.Class (liftIO)
import qualified Control.Monad.CatchIO as CatchIO (catch)
import Data.Map (Map)
import qualified Data.Map as Map
import qualified Data.ByteString.Char8 as ByteString (pack, unpack)
import Snap.Core
import Snap.Util.FileServe
import Snap.Http.Server
import Text.JSON (JSValue, Result(..), JSObject)
import qualified Text.JSON as JSON
import System.FilePath ((</>))

import Ganeti.Daemon
import qualified Ganeti.Constants as Constants
import qualified Ganeti.Logging as Logging
import Ganeti.Runtime (GanetiDaemon(..), ExtraLogReason(..))
import qualified Ganeti.Runtime as Runtime

import Ganeti.Metad.Config as Config
import Ganeti.Metad.Types (InstanceParams)

type MetaM = Snap ()

split :: String -> [String]
split str =
  case span (/= '/') str of
    (x, []) -> [x]
    (x, _:xs) -> x:split xs

lookupInstanceParams :: MonadError String m => String -> Map String b -> m b
lookupInstanceParams inst params =
  case Map.lookup inst params of
    Nothing -> throwError $ "Could not get instance params for " ++ show inst
    Just x -> return x

error404 :: MetaM
error404 = do
  modifyResponse . setResponseStatus 404 $ ByteString.pack "Not found"
  writeBS $ ByteString.pack "Resource not found"

maybeResult :: MonadError String m => Result t -> (t -> m a) -> m a
maybeResult (Error err) _ = throwError err
maybeResult (Ok x) f = f x

serveOsParams :: String -> Map String JSValue -> MetaM
serveOsParams inst params =
  do instParams <- lookupInstanceParams inst params
     maybeResult (Config.getOsParamsWithVisibility instParams) $ \osParams ->
       writeBS .
       ByteString.pack .
       JSON.encode $ osParams

serveOsPackage :: String -> Map String JSValue -> MetaM
serveOsPackage inst instParams =
  case Map.lookup inst instParams of
    Just (JSON.JSObject osParams) -> do
      let res = getOsPackage osParams
      case res of
        Error err ->
          do liftIO $ Logging.logWarning err
             error404
        Ok package ->
          serveFile package
          `CatchIO.catch`
          \err -> do liftIO . Logging.logWarning $
                       "Could not serve OS package: " ++ show (err :: IOError)
                     error404
    _ -> error404
  where getOsPackage osParams =
          case lookup "os-package" (JSON.fromJSObject osParams) of
            Nothing -> Error $ "Could not find OS package for " ++ show inst
            Just x -> fst <$> (JSON.readJSON x :: Result (String, String))

serveOsScript :: String -> Map String JSValue -> String -> MetaM
serveOsScript inst params script =
  do instParams <- lookupInstanceParams inst params
     maybeResult (getOsType instParams) $ \os ->
       if null os
       then throwError $ "There is no OS for " ++ show inst
       else serveScript os Constants.osSearchPath
  where getOsType instParams =
          do obj <- JSON.readJSON instParams :: Result (JSObject JSValue)
             case lookup "os" (JSON.fromJSObject obj) of
               Nothing -> Error $ "Could not find OS for " ++ show inst
               Just x -> JSON.readJSON x :: Result String

        serveScript :: String -> [String] -> MetaM
        serveScript os [] =
          throwError $ "Could not find OS script " ++ show (os </> script)
        serveScript os (d:ds) =
          serveFile (d </> os </> script)
          `CatchIO.catch`
          \err -> do let _ = err :: IOError
                     serveScript os ds

handleMetadata
  :: MVar InstanceParams -> Method -> String -> String -> String -> MetaM
handleMetadata _ GET  "ganeti" "latest" "meta_data.json" =
  liftIO $ Logging.logInfo "ganeti metadata"
handleMetadata params GET  "ganeti" "latest" "os/package" =
  do remoteAddr <- ByteString.unpack . rqRemoteAddr <$> getRequest
     instanceParams <- liftIO $ do
       Logging.logInfo $ "OS package for " ++ show remoteAddr
       readMVar params
     serveOsPackage remoteAddr instanceParams
handleMetadata params GET  "ganeti" "latest" "os/parameters.json" =
  do remoteAddr <- ByteString.unpack . rqRemoteAddr <$> getRequest
     instanceParams <- liftIO $ do
       Logging.logInfo $ "OS parameters for " ++ show remoteAddr
       readMVar params
     serveOsParams remoteAddr instanceParams `catchError`
       \err -> do
         liftIO . Logging.logWarning $ "Could not serve OS parameters: " ++ err
         error404
handleMetadata params GET  "ganeti" "latest" script | isScript script =
  do remoteAddr <- ByteString.unpack . rqRemoteAddr <$> getRequest
     instanceParams <- liftIO $ do
       Logging.logInfo $ "OS package for " ++ show remoteAddr
       readMVar params
     serveOsScript remoteAddr instanceParams (last $ split script) `catchError`
       \err -> do
         liftIO . Logging.logWarning $ "Could not serve OS scripts: " ++ err
         error404
  where isScript =
          (`elem` [ "os/scripts/create"
                  , "os/scripts/export"
                  , "os/scripts/import"
                  , "os/scripts/rename"
                  , "os/scripts/verify"
                  ])
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

{-# LANGUAGE FlexibleContexts, OverloadedStrings #-}
{-| Web server for the metadata daemon.

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

module Ganeti.Metad.WebServer (start) where

import Control.Applicative
import Control.Concurrent (MVar, readMVar)
import Control.Monad.Error.Class (MonadError, catchError, throwError)
import Control.Monad.IO.Class (liftIO)
import qualified Control.Monad.CatchIO as CatchIO (catch)
import qualified Data.CaseInsensitive as CI
import Data.List (intercalate)
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

-- | The 404 "not found" error.
error404 :: MetaM
error404 = do
  modifyResponse $ setResponseStatus 404 "Not found"
  writeBS "Resource not found"

-- | The 405 "method not allowed error", including the list of allowed methods.
error405 :: [Method] -> MetaM
error405 ms = modifyResponse $
  addHeader (CI.mk "Allow") (ByteString.pack . intercalate ", " $ map show ms)
  . setResponseStatus 405 "Method not allowed"

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

serveOsPackage :: String -> Map String JSValue -> String -> MetaM
serveOsPackage inst params key =
  do instParams <- lookupInstanceParams inst params
     maybeResult (JSON.readJSON instParams >>=
                  Config.getPublicOsParams >>=
                  getOsPackage) $ \package ->
       serveFile package `CatchIO.catch` \err ->
         throwError $ "Could not serve OS package: " ++ show (err :: IOError)
  where getOsPackage osParams =
          case lookup key (JSON.fromJSObject osParams) of
            Nothing -> Error $ "Could not find OS package for " ++ show inst
            Just x -> JSON.readJSON x

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
handleMetadata params GET  "ganeti" "latest" "os/os-install-package" =
  do remoteAddr <- ByteString.unpack . rqRemoteAddr <$> getRequest
     instanceParams <- liftIO $ do
       Logging.logInfo $ "OS install package for " ++ show remoteAddr
       readMVar params
     serveOsPackage remoteAddr instanceParams "os-install-package"
       `catchError`
       \err -> do
         liftIO .
           Logging.logWarning $ "Could not serve OS install package: " ++ err
         error404
handleMetadata params GET  "ganeti" "latest" "os/package" =
  do remoteAddr <- ByteString.unpack . rqRemoteAddr <$> getRequest
     instanceParams <- liftIO $ do
       Logging.logInfo $ "OS package for " ++ show remoteAddr
       readMVar params
     serveOsPackage remoteAddr instanceParams "os-package"
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
handleMetadata _ _  "ganeti" "latest" "read" =
  error405 [GET]
handleMetadata _ POST "ganeti" "latest" "write" =
  liftIO $ Logging.logInfo "ganeti WRITE"
handleMetadata _ _ "ganeti" "latest" "write" =
  error405 [POST]
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

{-# LANGUAGE RankNTypes, FlexibleContexts #-}

{-| Implementation of functions specific to configuration management.

TODO: distribute the configuration to master candidates (and not the master)
TODO: Detect changes in SSConf and distribute only if it changes
TODO: distribute ssconf configuration, if it has changed

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

module Ganeti.WConfd.ConfigWriter
  ( loadConfigFromFile
  , saveConfigAsyncTask
  , readConfig
  , writeConfig
  ) where

import Control.Applicative
import Control.Monad.Base
import Control.Monad.Error
import qualified Control.Monad.State.Strict as S

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Config
import Ganeti.Logging.Lifted
import Ganeti.Objects
import Ganeti.Runtime
import Ganeti.Utils
import Ganeti.Utils.Atomic
import Ganeti.Utils.AsyncWorker
import Ganeti.WConfd.ConfigState
import Ganeti.WConfd.Monad

-- | Loads the configuration from the file, if it hasn't been loaded yet.
-- The function is internal and isn't thread safe.
loadConfigFromFile :: FilePath
                   -> ResultG (ConfigData, FStat)
loadConfigFromFile path = withLockedFile path $ \_ -> do
    stat <- liftBase $ getFStat path
    cd <- mkResultT (loadConfig path)
    return (cd, stat)

-- | Writes the current configuration to the file. The function isn't thread
-- safe.
-- Neither distributes the configuration (to nodes and ssconf) nor
-- updates the serial number.
writeConfigToFile :: (MonadBase IO m, MonadError GanetiException m, MonadLog m)
                  => ConfigData -> FilePath -> FStat -> m FStat
writeConfigToFile cfg path oldstat = do
    logDebug "Async. config. writer: Commencing write"
    r <- toErrorBase $ atomicUpdateLockedFile_ path oldstat doWrite
    logDebug "Async. config. writer: written"
    return r
  where
    doWrite fname fh = do
      setOwnerAndGroupFromNames fname GanetiWConfd
                                (DaemonGroup GanetiConfd)
      setOwnerWGroupR fname
      saveConfig fh cfg

-- | Construct an asynchronous worker whose action is to save the
-- configuration to the master file.
-- The worker's action reads the configuration using the given @IO@ action
-- and uses 'FStat' to check if the configuration hasn't been modified by
-- another process.
saveConfigAsyncTask :: FilePath -- ^ Path to the config file
                    -> FStat  -- ^ The initial state of the config. file
                    -> IO ConfigState -- ^ An action to read the current config
                    -> ResultG (AsyncWorker ())
saveConfigAsyncTask fpath fstat cdRef =
  flip S.evalStateT fstat . mkAsyncWorker $
    catchError (do
        oldstat <- S.get
        cd <- liftBase (csConfigData `liftM` cdRef)
        newstat <- writeConfigToFile cd fpath oldstat
        S.put newstat
      ) (logEmergency . (++) "Can't write the master configuration file: "
                      . show)

-- Reads the current configuration state in the 'WConfdMonad'.
readConfig :: WConfdMonad ConfigData
readConfig = csConfigData <$> readConfigState

-- Replaces the current configuration state within the 'WConfdMonad'.
writeConfig :: ConfigData -> WConfdMonad ()
writeConfig cd = modifyConfigState $ const (mkConfigState cd, ())

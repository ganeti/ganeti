{-# LANGUAGE RankNTypes, FlexibleContexts #-}

{-| Implementation of functions specific to configuration management.

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
  , readConfig
  , writeConfig
  , saveConfigAsyncTask
  , distMCsAsyncTask
  , distSSConfAsyncTask
  ) where

import Control.Applicative
import Control.Monad.Base
import Control.Monad.Error
import qualified Control.Monad.State.Strict as S
import Control.Monad.Trans.Control

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Config
import Ganeti.Logging
import Ganeti.Objects
import Ganeti.Rpc
import Ganeti.Runtime
import Ganeti.Utils
import Ganeti.Utils.Atomic
import Ganeti.Utils.AsyncWorker
import Ganeti.WConfd.ConfigState
import Ganeti.WConfd.Monad
import Ganeti.WConfd.Ssconf

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
    logDebug $ "Async. config. writer: Commencing write\
               \ serial no " ++ show (serialOf cfg)
    r <- toErrorBase $ atomicUpdateLockedFile_ path oldstat doWrite
    logDebug "Async. config. writer: written"
    return r
  where
    doWrite fname fh = do
      setOwnerAndGroupFromNames fname GanetiWConfd
                                (DaemonGroup GanetiConfd)
      setOwnerWGroupR fname
      saveConfig fh cfg

-- Reads the current configuration state in the 'WConfdMonad'.
readConfig :: WConfdMonad ConfigData
readConfig = csConfigData <$> readConfigState

-- Replaces the current configuration state within the 'WConfdMonad'.
writeConfig :: ConfigData -> WConfdMonad ()
writeConfig cd = modifyConfigState $ const (mkConfigState cd, ())

-- * Asynchronous tasks

-- | Runs the given action on success, or logs an error on failure.
finishOrLog :: (Show e, MonadLog m)
            => Priority
            -> String
            -> (a -> m ())
            -> GenericResult e a
            -> m ()
finishOrLog logPrio logPrefix =
  genericResult (logAt logPrio . (++) (logPrefix ++ ": ") . show)

-- | Creates a stateless asynchronous task that handles errors in its actions.
mkStatelessAsyncTask :: (MonadBaseControl IO m, MonadLog m, Show e)
                     => Priority
                     -> String
                     -> ResultT e m ()
                     -> m (AsyncWorker ())
mkStatelessAsyncTask logPrio logPrefix action =
    mkAsyncWorker $ runResultT action >>= finishOrLog logPrio logPrefix return

-- | Creates an asynchronous task that handles errors in its actions.
-- If an error occurs, it's logged and the internal state remains unchanged.
mkStatefulAsyncTask :: (MonadBaseControl IO m, MonadLog m, Show e)
                    => Priority
                    -> String
                    -> s
                    -> (s -> ResultT e m s)
                    -> m (AsyncWorker ())
mkStatefulAsyncTask logPrio logPrefix start action =
    flip S.evalStateT start . mkAsyncWorker $
      S.get >>= lift . runResultT . action
            >>= finishOrLog logPrio logPrefix S.put -- put on success

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
  lift . mkStatefulAsyncTask
           EMERGENCY "Can't write the master configuration file" fstat
       $ \oldstat -> do
            cd <- liftBase (csConfigData `liftM` cdRef)
            writeConfigToFile cd fpath oldstat

-- | Performs a RPC call on the given list of nodes and logs any failures.
-- If any of the calls fails, fail the computation with 'failError'.
execRpcCallAndLog :: (Rpc a b) => [Node] -> a -> ResultG ()
execRpcCallAndLog nodes req = do
  rs <- liftIO $ executeRpcCall nodes req
  es <- logRpcErrors rs
  unless (null es) $ failError "At least one of the RPC calls failed"

-- | Construct an asynchronous worker whose action is to distribute the
-- configuration to master candidates.
distMCsAsyncTask :: RuntimeEnts
                 -> FilePath -- ^ Path to the config file
                 -> IO ConfigState -- ^ An action to read the current config
                 -> ResultG (AsyncWorker ())
distMCsAsyncTask ents cpath cdRef =
  lift . mkStatelessAsyncTask ERROR "Can't distribute the configuration\
                                    \ to master candidates"
       $ do
          cd <- liftBase (csConfigData <$> cdRef) :: ResultG ConfigData
          logDebug $ "Distributing the configuration to master candidates,\
                     \ serial no " ++ show (serialOf cd)
          fupload <- prepareRpcCallUploadFile ents cpath
          execRpcCallAndLog (getMasterCandidates cd) fupload
          logDebug "Successfully finished distributing the configuration"

-- | Construct an asynchronous worker whose action is to construct SSConf
-- and distribute it to master candidates.
-- The worker's action reads the configuration using the given @IO@ action,
-- computes the current SSConf, compares it to the previous version, and
-- if different, distributes it.
distSSConfAsyncTask
    :: IO ConfigState -- ^ An action to read the current config
    -> ResultG (AsyncWorker ())
distSSConfAsyncTask cdRef =
  lift . mkStatefulAsyncTask ERROR "Can't distribute Ssconf" emptySSConf
       $ \oldssc -> do
            cd <- liftBase (csConfigData <$> cdRef) :: ResultG ConfigData
            let ssc = mkSSConf cd
            if oldssc == ssc
              then logDebug "SSConf unchanged, not distributing"
              else do
                logDebug $ "Starting the distribution of SSConf\
                           \ serial no " ++ show (serialOf cd)
                execRpcCallAndLog (getOnlineNodes cd)
                                  (RpcCallWriteSsconfFiles ssc)
                logDebug "Successfully finished distributing SSConf"
            return ssc

{-# LANGUAGE RankNTypes, FlexibleContexts #-}

{-| Implementation of functions specific to configuration management.

-}

{-

Copyright (C) 2013, 2014 Google Inc.
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
import Data.Monoid

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
writeConfig cd = modifyConfigState $ const ((), mkConfigState cd)

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
mkStatelessAsyncTask :: (MonadBaseControl IO m, MonadLog m, Show e, Monoid i)
                     => Priority
                     -> String
                     -> (i -> ResultT e m ())
                     -> m (AsyncWorker i ())
mkStatelessAsyncTask logPrio logPrefix action =
    mkAsyncWorker $ runResultT . action
                    >=> finishOrLog logPrio logPrefix return

-- | Creates an asynchronous task that handles errors in its actions.
-- If an error occurs, it's logged and the internal state remains unchanged.
mkStatefulAsyncTask :: (MonadBaseControl IO m, MonadLog m, Show e, Monoid i)
                    => Priority
                    -> String
                    -> s
                    -> (s -> i -> ResultT e m s)
                    -> m (AsyncWorker i ())
mkStatefulAsyncTask logPrio logPrefix start action =
    flip S.evalStateT start . mkAsyncWorker $ \i ->
      S.get >>= lift . runResultT . flip action i
            >>= finishOrLog logPrio logPrefix S.put -- put on success

-- | Construct an asynchronous worker whose action is to save the
-- configuration to the master file.
-- The worker's action reads the configuration using the given @IO@ action
-- and uses 'FStat' to check if the configuration hasn't been modified by
-- another process.
--
-- If 'Any' of the input requests is true, given additional worker
-- will be executed synchronously after sucessfully writing the configuration
-- file. Otherwise, they'll be just triggered asynchronously.
saveConfigAsyncTask :: FilePath -- ^ Path to the config file
                    -> FStat  -- ^ The initial state of the config. file
                    -> IO ConfigState -- ^ An action to read the current config
                    -> [AsyncWorker () ()] -- ^ Workers to be triggered
                                           -- afterwards
                    -> ResultG (AsyncWorker Any ())
saveConfigAsyncTask fpath fstat cdRef workers =
  lift . mkStatefulAsyncTask
           EMERGENCY "Can't write the master configuration file" fstat
       $ \oldstat (Any flush) -> do
            cd <- liftBase (csConfigData `liftM` cdRef)
            writeConfigToFile cd fpath oldstat
              <* if flush then logDebug "Running distribution synchronously"
                               >> triggerAndWaitMany_ workers
                          else logDebug "Running distribution asynchronously"
                               >> mapM trigger_ workers


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
                 -> ResultG (AsyncWorker () ())
distMCsAsyncTask ents cpath cdRef =
  lift . mkStatelessAsyncTask ERROR "Can't distribute the configuration\
                                    \ to master candidates"
       $ \_ -> do
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
    -> ResultG (AsyncWorker () ())
distSSConfAsyncTask cdRef =
  lift . mkStatefulAsyncTask ERROR "Can't distribute Ssconf" emptySSConf
       $ \oldssc _ -> do
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

{-# LANGUAGE MultiParamTypeClasses, TypeFamilies, FlexibleContexts #-}
{-# LANGUAGE TemplateHaskell #-}

{-| All RPC calls are run within this monad.

It encapsulates:

* IO operations,
* failures,
* working with the daemon state.

Code that is specific either to the configuration or the lock management, should
go into their corresponding dedicated modules.
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

module Ganeti.WConfd.Monad
  ( DaemonHandle
  , dhConfigPath
  , mkDaemonHandle
  , WConfdMonadInt
  , runWConfdMonadInt
  , WConfdMonad
  , daemonHandle
  , modifyConfigState
  , readConfigState
  , modifyLockWaiting
  , modifyLockWaiting_
  , readLockAllocation
  ) where

import Control.Applicative
import Control.Arrow ((&&&), second)
import Control.Monad
import Control.Monad.Base
import Control.Monad.Error
import Control.Monad.Reader
import Control.Monad.Trans.Control
import Data.IORef.Lifted
import qualified Data.Set as S
import Data.Tuple (swap)
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Lens
import Ganeti.Locking.Allocation (LockAllocation)
import Ganeti.Locking.Locks
import Ganeti.Locking.Waiting (getAllocation)
import Ganeti.Logging
import Ganeti.Utils.AsyncWorker
import Ganeti.WConfd.ConfigState

-- * Pure data types used in the monad

-- | The state of the daemon, capturing both the configuration state and the
-- locking state.
data DaemonState = DaemonState
  { dsConfigState :: ConfigState
  , dsLockWaiting :: GanetiLockWaiting
  }

$(makeCustomLenses ''DaemonState)

data DaemonHandle = DaemonHandle
  { dhDaemonState :: IORef DaemonState -- ^ The current state of the daemon
  , dhConfigPath :: FilePath           -- ^ The configuration file path
  -- all static information that doesn't change during the life-time of the
  -- daemon should go here;
  -- all IDs of threads that do asynchronous work should probably also go here
  , dhSaveConfigWorker :: AsyncWorker ()
  , dhDistMCsWorker :: AsyncWorker ()
  , dhDistSSConfWorker :: AsyncWorker ()
  , dhSaveLocksWorker :: AsyncWorker ()
  }

mkDaemonHandle :: FilePath
               -> ConfigState
               -> GanetiLockWaiting
               -> (IO ConfigState -> ResultG (AsyncWorker ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- saves the configuration to the master file.
               -> (IO ConfigState -> ResultG (AsyncWorker ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- distributes the configuration to master candidates
               -> (IO ConfigState -> ResultG (AsyncWorker ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- distributes SSConf to nodes
               -> (IO GanetiLockWaiting -> ResultG (AsyncWorker ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- saves the lock allocation state.
               -> ResultG DaemonHandle
mkDaemonHandle cpath cstat lstat
               saveWorkerFn distMCsWorkerFn distSSConfWorkerFn
               saveLockWorkerFn = do
  ds <- newIORef $ DaemonState cstat lstat
  let readConfigIO = dsConfigState `liftM` readIORef ds :: IO ConfigState

  saveWorker <- saveWorkerFn readConfigIO
  ssconfWorker <- distSSConfWorkerFn readConfigIO
  distMCsWorker <- distMCsWorkerFn readConfigIO

  saveLockWorker <- saveLockWorkerFn $ dsLockWaiting `liftM` readIORef ds

  return $ DaemonHandle ds cpath saveWorker distMCsWorker ssconfWorker
                                 saveLockWorker

-- * The monad and its instances

-- | A type alias for easier referring to the actual content of the monad
-- when implementing its instances.
type WConfdMonadIntType = ReaderT DaemonHandle IO

-- | The internal part of the monad without error handling.
newtype WConfdMonadInt a = WConfdMonadInt
  { getWConfdMonadInt :: WConfdMonadIntType a }

instance Functor WConfdMonadInt where
  fmap f = WConfdMonadInt . fmap f . getWConfdMonadInt

instance Applicative WConfdMonadInt where
  pure = WConfdMonadInt . pure
  WConfdMonadInt f <*> WConfdMonadInt k = WConfdMonadInt $ f <*> k

instance Monad WConfdMonadInt where
  return = WConfdMonadInt . return
  (WConfdMonadInt k) >>= f = WConfdMonadInt $ k >>= getWConfdMonadInt . f

instance MonadIO WConfdMonadInt where
  liftIO = WConfdMonadInt . liftIO

instance MonadBase IO WConfdMonadInt where
  liftBase = WConfdMonadInt . liftBase

instance MonadBaseControl IO WConfdMonadInt where
  newtype StM WConfdMonadInt b = StMWConfdMonadInt
    { runStMWConfdMonadInt :: StM WConfdMonadIntType b }
  liftBaseWith f = WConfdMonadInt . liftBaseWith
                   $ \r -> f (liftM StMWConfdMonadInt . r . getWConfdMonadInt)
  restoreM = WConfdMonadInt . restoreM . runStMWConfdMonadInt

instance MonadLog WConfdMonadInt where
  logAt p = WConfdMonadInt . logAt p

-- | Runs the internal part of the WConfdMonad monad on a given daemon
-- handle.
runWConfdMonadInt :: WConfdMonadInt a -> DaemonHandle -> IO a
runWConfdMonadInt (WConfdMonadInt k) = runReaderT k

-- | The complete monad with error handling.
type WConfdMonad = ResultT GanetiException WConfdMonadInt

-- * Basic functions in the monad

-- | Returns the daemon handle.
daemonHandle :: WConfdMonad DaemonHandle
daemonHandle = lift . WConfdMonadInt $ ask

-- | Returns the current configuration, given a handle
readConfigState :: WConfdMonad ConfigState
readConfigState = liftM dsConfigState . readIORef . dhDaemonState
                  =<< daemonHandle

-- | Atomically modifies the configuration state in the WConfdMonad.
modifyConfigState :: (ConfigState -> (ConfigState, a)) -> WConfdMonad a
modifyConfigState f = do
  dh <- daemonHandle
  let modCS cs = let (cs', r) = f cs
                  in ((r, cs /= cs'), cs')
  let mf = traverseOf dsConfigStateL modCS
  (r, modified) <- atomicModifyIORef (dhDaemonState dh) (swap . mf)
  when modified $ do
    -- trigger the config. saving worker and wait for it
    logDebug "Triggering config write"
    liftBase . triggerAndWait . dhSaveConfigWorker $ dh
    logDebug "Config write finished"
    -- trigger the config. distribution worker synchronously
    -- TODO: figure out what configuration changes need synchronous updates
    -- and otherwise use asynchronous triggers
    _ <- liftBase . triggerAndWaitMany $ [ dhDistMCsWorker dh
                                         , dhDistSSConfWorker dh
                                         ]
    return ()
  return r

-- | Atomically modifies the lock waiting state in WConfdMonad.
modifyLockWaiting :: (GanetiLockWaiting -> ( GanetiLockWaiting
                                           , (a, S.Set ClientId) ))
                     -> WConfdMonad a
modifyLockWaiting f = do
  dh <- lift . WConfdMonadInt $ ask
  let f' = swap . (fst &&& id) . f
  (lockAlloc, (r, nfy)) <- atomicModifyIORef
                             (dhDaemonState dh)
                             (swap . traverseOf dsLockWaitingL f')
  logDebug $ "Current lock status: " ++ J.encode lockAlloc
  logDebug "Triggering lock state write"
  liftBase . triggerAndWait . dhSaveLocksWorker $ dh
  logDebug "Lock write finished"
  unless (S.null nfy) $ do
    logDebug . (++) "Locks became available for " . show $ S.toList nfy
    logWarning "Process notification not yet implemented"
  return r

-- | Atomically modifies the lock allocation state in WConfdMonad, not
-- producing any result
modifyLockWaiting_ :: (GanetiLockWaiting -> (GanetiLockWaiting, S.Set ClientId))
                      -> WConfdMonad ()
modifyLockWaiting_ = modifyLockWaiting . ((second $ (,) ()) .)

-- | Read the underlying lock allocation.
readLockAllocation :: WConfdMonad (LockAllocation GanetiLocks ClientId)
readLockAllocation = liftM (getAllocation . dsLockWaiting)
                     . readIORef . dhDaemonState
                     =<< daemonHandle

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
  , dhSaveConfigWorker
  , mkDaemonHandle
  , WConfdMonadInt
  , runWConfdMonadInt
  , WConfdMonad
  , daemonHandle
  , modifyConfigState
  , readConfigState
  , modifyLockAllocation
  , modifyLockAllocation_
  , readLockAllocation
  ) where

import Control.Applicative
import Control.Monad
import Control.Monad.Base
import Control.Monad.Error
import Control.Monad.Reader
import Control.Monad.Trans.Control
import Data.IORef.Lifted
import Data.Tuple (swap)

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Lens
import Ganeti.Locking.Locks
import Ganeti.Logging
import Ganeti.Utils.AsyncWorker
import Ganeti.WConfd.ConfigState

-- * Pure data types used in the monad

-- | The state of the daemon, capturing both the configuration state and the
-- locking state.
data DaemonState = DaemonState
  { dsConfigState :: ConfigState
  , dsLockAllocation :: GanetiLockAllocation
  }

$(makeCustomLenses ''DaemonState)

data DaemonHandle = DaemonHandle
  { dhDaemonState :: IORef DaemonState -- ^ The current state of the daemon
  , dhConfigPath :: FilePath           -- ^ The configuration file path
  -- all static information that doesn't change during the life-time of the
  -- daemon should go here;
  -- all IDs of threads that do asynchronous work should probably also go here
  , dhSaveConfigWorker :: AsyncWorker ()
  , dhSaveLocksWorker :: AsyncWorker ()
  }

mkDaemonHandle :: FilePath
               -> ConfigState
               -> GanetiLockAllocation
               -> (IO ConfigState -> ResultG (AsyncWorker ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- saves the configuration to the master file.
               -> (IO GanetiLockAllocation -> ResultG (AsyncWorker ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- saves the lock allocation state.
               -> ResultG DaemonHandle
mkDaemonHandle cpath cstat lstat saveConfigWorkerFn saveLockWorkerFn = do
  ds <- newIORef $ DaemonState cstat lstat
  saveConfigWorker <- saveConfigWorkerFn $ dsConfigState `liftM` readIORef ds
  saveLockWorker <- saveLockWorkerFn $ dsLockAllocation `liftM` readIORef ds
  return $ DaemonHandle ds cpath saveConfigWorker saveLockWorker

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
    -- trigger the config. distribution worker asynchronously
    -- TODO
  return r

-- | Atomically modifies the lock allocation state in WConfdMonad.
modifyLockAllocation :: (GanetiLockAllocation -> (GanetiLockAllocation, a))
                     -> WConfdMonad a
modifyLockAllocation f = do
  dh <- lift . WConfdMonadInt $ ask
  r <- atomicModifyIORef (dhDaemonState dh)
                         (swap . traverseOf dsLockAllocationL (swap . f))
  logDebug "Triggering lock state write"
  liftBase . triggerAndWait . dhSaveLocksWorker $ dh
  logDebug "Lock write finished"
  return r

-- | Atomically modifies the lock allocation state in WConfdMonad, not
-- producing any result
modifyLockAllocation_ :: (GanetiLockAllocation -> GanetiLockAllocation)
                      -> WConfdMonad ()
modifyLockAllocation_ = modifyLockAllocation . (flip (,) () .)

-- | Read the lock allocation state.
readLockAllocation :: WConfdMonad GanetiLockAllocation
readLockAllocation = liftM dsLockAllocation . readIORef . dhDaemonState
                     =<< daemonHandle

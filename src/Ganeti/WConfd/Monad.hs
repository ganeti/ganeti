{-# LANGUAGE MultiParamTypeClasses, TypeFamilies, FlexibleContexts #-}

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
  ) where

import Control.Applicative
import Control.Monad
import Control.Monad.Base
import Control.Monad.Error
import Control.Monad.Reader
import Control.Monad.Trans.Control
import Data.IORef.Lifted

import Ganeti.BasicTypes
import Ganeti.Errors
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

data DaemonHandle = DaemonHandle
  { dhDaemonState :: IORef DaemonState -- ^ The current state of the daemon
  , dhConfigPath :: FilePath           -- ^ The configuration file path
  -- all static information that doesn't change during the life-time of the
  -- daemon should go here;
  -- all IDs of threads that do asynchronous work should probably also go here
  , dhSaveConfigWorker :: AsyncWorker ()
  }

mkDaemonHandle :: FilePath
               -> ConfigState
               -> GanetiLockAllocation
               -> (IO ConfigState -> ResultG (AsyncWorker ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- saves the configuration to the master file.
               -> ResultG DaemonHandle
mkDaemonHandle cpath cstat lstat saveWorkerFn = do
  ds <- newIORef $ DaemonState cstat lstat
  saveWorker <- saveWorkerFn $ dsConfigState `liftM` readIORef ds
  return $ DaemonHandle ds cpath saveWorker

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
  -- TODO: Use lenses to modify the daemons state here
  let mf ds = let (cs', r) = f (dsConfigState ds)
              in (ds { dsConfigState = cs' }, r)
  r <- atomicModifyIORef (dhDaemonState dh) mf
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
  let mf ds = let (la', r) = f (dsLockAllocation ds)
              in (ds { dsLockAllocation = la' }, r)
  atomicModifyIORef (dhDaemonState dh) mf
  -- TODO: Trigger the async. lock saving worker

{-# LANGUAGE MultiParamTypeClasses, TypeFamilies #-}
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

module Ganeti.WConfd.Monad
  ( DaemonHandle
  , dhConfigPath
  , dhLivelock
  , mkDaemonHandle
  , WConfdMonadInt
  , runWConfdMonadInt
  , WConfdMonad
  , daemonHandle
  , modifyConfigState
  , forceConfigStateDistribution
  , readConfigState
  , modifyConfigDataErr_
  , modifyLockWaiting
  , modifyLockWaiting_
  , readLockWaiting
  , readLockAllocation
  , modifyTempResState
  , modifyTempResStateErr
  , readTempResState
  ) where

import Control.Applicative
import Control.Arrow ((&&&), second)
import Control.Monad
import Control.Monad.Base
import Control.Monad.Error
import Control.Monad.Reader
import Control.Monad.State
import Control.Monad.Trans.Control
import Data.Functor.Identity
import Data.IORef.Lifted
import Data.Monoid (Any(..))
import qualified Data.Set as S
import Data.Tuple (swap)
import System.Time (getClockTime)
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.JQueue (notifyJob)
import Ganeti.Lens
import Ganeti.Locking.Allocation (LockAllocation)
import Ganeti.Locking.Locks
import Ganeti.Locking.Waiting (getAllocation)
import Ganeti.Logging
import Ganeti.Logging.WriterLog
import Ganeti.Objects (ConfigData)
import Ganeti.Utils.AsyncWorker
import Ganeti.Utils.IORef
import Ganeti.Utils.Livelock (Livelock)
import Ganeti.WConfd.ConfigState
import Ganeti.WConfd.TempRes

-- * Pure data types used in the monad

-- | The state of the daemon, capturing both the configuration state and the
-- locking state.
data DaemonState = DaemonState
  { dsConfigState :: ConfigState
  , dsLockWaiting :: GanetiLockWaiting
  , dsTempRes :: TempResState
  }

$(makeCustomLenses ''DaemonState)

data DaemonHandle = DaemonHandle
  { dhDaemonState :: IORef DaemonState -- ^ The current state of the daemon
  , dhConfigPath :: FilePath           -- ^ The configuration file path
  -- all static information that doesn't change during the life-time of the
  -- daemon should go here;
  -- all IDs of threads that do asynchronous work should probably also go here
  , dhSaveConfigWorker :: AsyncWorker Any ()
  , dhSaveLocksWorker :: AsyncWorker () ()
  , dhSaveTempResWorker :: AsyncWorker () ()
  , dhLivelock :: Livelock
  }

mkDaemonHandle :: FilePath
               -> ConfigState
               -> GanetiLockWaiting
               -> TempResState
               -> (IO ConfigState -> [AsyncWorker () ()]
                                  -> ResultG (AsyncWorker Any ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- saves the configuration to the master file.
               -> (IO ConfigState -> ResultG (AsyncWorker () ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- distributes the configuration to master candidates
               -> (IO ConfigState -> ResultG (AsyncWorker () ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- distributes SSConf to nodes
               -> (IO GanetiLockWaiting -> ResultG (AsyncWorker () ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- saves the lock allocation state.
               -> (IO TempResState -> ResultG (AsyncWorker () ()))
                  -- ^ A function that creates a worker that asynchronously
                  -- saves the temporary reservations state.
               -> Livelock
               -> ResultG DaemonHandle
mkDaemonHandle cpath cstat lstat trstat
               saveWorkerFn distMCsWorkerFn distSSConfWorkerFn
               saveLockWorkerFn saveTempResWorkerFn
               livelock = do
  ds <- newIORef $ DaemonState cstat lstat trstat
  let readConfigIO = dsConfigState `liftM` readIORef ds :: IO ConfigState

  ssconfWorker <- distSSConfWorkerFn readConfigIO
  distMCsWorker <- distMCsWorkerFn readConfigIO
  saveWorker <- saveWorkerFn readConfigIO [ distMCsWorker
                                          , ssconfWorker ]

  saveLockWorker <- saveLockWorkerFn $ dsLockWaiting `liftM` readIORef ds

  saveTempResWorker <- saveTempResWorkerFn $ dsTempRes `liftM` readIORef ds

  return $ DaemonHandle ds cpath saveWorker saveLockWorker saveTempResWorker
                        livelock

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

-- | A pure monad that logs and reports errors used for atomic modifications.
type AtomicModifyMonad a = ResultT GanetiException WriterLog a

-- * Basic functions in the monad

-- | Returns the daemon handle.
daemonHandle :: WConfdMonad DaemonHandle
daemonHandle = lift . WConfdMonadInt $ ask

-- | Returns the current configuration, given a handle
readConfigState :: WConfdMonad ConfigState
readConfigState = liftM dsConfigState . readIORef . dhDaemonState
                  =<< daemonHandle

-- | Atomically modifies the configuration state in the WConfdMonad
-- with a computation that can possibly fail.
modifyConfigStateErr
  :: (TempResState -> ConfigState -> AtomicModifyMonad (a, ConfigState))
  -> WConfdMonad a
modifyConfigStateErr f = do
  dh <- daemonHandle
  now <- liftIO getClockTime

  -- If the configuration is modified, we also bump its serial number.
  -- In order to determine if we need to save, we report if it's modified
  -- as well as if it needs to be distributed synchronously.
  let unpackResult cs (r, cs')
                    | cs /= cs' = ( (r, True, needsFullDist cs cs')
                                  , over csConfigDataL (bumpSerial now) cs' )
                    | otherwise = ((r, False, False), cs')
  let modCS ds@(DaemonState { dsTempRes = tr }) =
        mapMOf2 dsConfigStateL (\cs -> liftM (unpackResult cs) (f tr cs)) ds
  (r, modified, distSync) <- atomicModifyIORefErrLog (dhDaemonState dh)
                                                     (liftM swap . modCS)
  when modified $ do
    if distSync
      then do
        logDebug "Triggering config write\
                 \ together with full synchronous distribution"
        liftBase . triggerAndWait (Any True) . dhSaveConfigWorker $ dh
        logDebug "Config write and distribution finished"
      else do
        -- trigger the config. saving worker and wait for it
        logDebug "Triggering config write\
                 \ and asynchronous distribution"
        liftBase . triggerAndWait (Any False) . dhSaveConfigWorker $ dh
    return ()
  return r

-- | Atomically modifies the configuration state in the WConfdMonad
-- with a computation that can possibly fail.
modifyConfigStateErr_
  :: (TempResState -> ConfigState -> AtomicModifyMonad ConfigState)
  -> WConfdMonad ()
modifyConfigStateErr_ f = modifyConfigStateErr ((liftM ((,) ()) .) . f)

-- | Atomically modifies the configuration state in the WConfdMonad.
modifyConfigState :: (ConfigState -> (a, ConfigState)) -> WConfdMonad a
modifyConfigState f = modifyConfigStateErr ((return .) . const f)

-- | Force the distribution of configuration without actually modifying it.
--
-- We need a separate call for this operation, because 'modifyConfigState' only
-- triggers the distribution when the configuration changes.
forceConfigStateDistribution :: WConfdMonad ()
forceConfigStateDistribution  = do
  logDebug "Forcing synchronous config write together with full distribution"
  dh <- daemonHandle
  liftBase . triggerAndWait (Any True) . dhSaveConfigWorker $ dh
  logDebug "Forced config write and distribution finished"

-- | Atomically modifies the configuration data in the WConfdMonad
-- with a computation that can possibly fail.
modifyConfigDataErr_
  :: (TempResState -> ConfigData -> AtomicModifyMonad ConfigData)
  -> WConfdMonad ()
modifyConfigDataErr_ f =
  modifyConfigStateErr_ (traverseOf csConfigDataL . f)

-- | Atomically modifies the state of temporary reservations in
-- WConfdMonad in the presence of possible errors.
modifyTempResStateErr
  :: (ConfigData -> StateT TempResState ErrorResult a) -> WConfdMonad a
modifyTempResStateErr f = do
  -- we use Compose to traverse the composition of applicative functors
  -- @ErrorResult@ and @(,) a@
  let f' ds = traverseOf2 dsTempResL
              (runStateT (f (csConfigData . dsConfigState $ ds))) ds
  dh <- daemonHandle
  r <- toErrorBase $ atomicModifyIORefErr (dhDaemonState dh)
                                          (liftM swap . f')
  -- logDebug $ "Current temporary reservations: " ++ J.encode tr
  logDebug "Triggering temporary reservations write"
  liftBase . triggerAndWait_ . dhSaveTempResWorker $ dh
  logDebug "Temporary reservations write finished"
  return r

-- | Atomically modifies the state of temporary reservations in
-- WConfdMonad.
modifyTempResState :: (ConfigData -> State TempResState a) -> WConfdMonad a
modifyTempResState f =
  modifyTempResStateErr (mapStateT (return . runIdentity) . f)

-- | Reads the state of of the configuration and temporary reservations
-- in WConfdMonad.
readTempResState :: WConfdMonad (ConfigData, TempResState)
readTempResState = liftM (csConfigData . dsConfigState &&& dsTempRes)
                     . readIORef . dhDaemonState
                   =<< daemonHandle

-- | Atomically modifies the lock waiting state in WConfdMonad.
modifyLockWaiting :: (GanetiLockWaiting -> ( GanetiLockWaiting
                                           , (a, S.Set ClientId) ))
                     -> WConfdMonad a
modifyLockWaiting f = do
  dh <- lift . WConfdMonadInt $ ask
  let f' = (id &&& fst) . f
  (lockAlloc, (r, nfy)) <- atomicModifyWithLens
                             (dhDaemonState dh) dsLockWaitingL f'
  logDebug $ "Current lock status: " ++ J.encode lockAlloc
  logDebug "Triggering lock state write"
  liftBase . triggerAndWait_ . dhSaveLocksWorker $ dh
  logDebug "Lock write finished"
  unless (S.null nfy) $ do
    logDebug . (++) "Locks became available for " . show $ S.toList nfy
    liftIO . mapM_ (notifyJob . ciPid) $ S.toList nfy
    logDebug "Finished notifying processes"
  return r

-- | Atomically modifies the lock allocation state in WConfdMonad, not
-- producing any result
modifyLockWaiting_ :: (GanetiLockWaiting -> (GanetiLockWaiting, S.Set ClientId))
                      -> WConfdMonad ()
modifyLockWaiting_ = modifyLockWaiting . ((second $ (,) ()) .)

-- | Read the lock waiting state in WConfdMonad.
readLockWaiting :: WConfdMonad GanetiLockWaiting
readLockWaiting = liftM dsLockWaiting
                  . readIORef . dhDaemonState
                  =<< daemonHandle


-- | Read the underlying lock allocation.
readLockAllocation :: WConfdMonad (LockAllocation GanetiLocks ClientId)
readLockAllocation = liftM getAllocation readLockWaiting

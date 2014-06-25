{-# LANGUAGE TemplateHaskell #-}

{-| The Ganeti WConfd core functions.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

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

module Ganeti.WConfd.Core where

import Control.Arrow ((&&&))
import Control.Monad (liftM, unless, when)
import Control.Monad.State (modify)
import qualified Data.Map as M
import qualified Data.Set as S
import Language.Haskell.TH (Name)
import qualified System.Random as Rand

import Ganeti.BasicTypes
import qualified Ganeti.JSON as J
import qualified Ganeti.Locking.Allocation as L
import Ganeti.Locking.Locks ( GanetiLocks(ConfigLock), LockLevel(LevelConfig)
                            , lockLevel, LockLevel, ClientId )
import qualified Ganeti.Locking.Waiting as LW
import Ganeti.Objects (ConfigData, DRBDSecret, LogicalVolume)
import qualified Ganeti.WConfd.ConfigVerify as V
import Ganeti.WConfd.Language
import Ganeti.WConfd.Monad
import qualified Ganeti.WConfd.TempRes as T
import qualified Ganeti.WConfd.ConfigWriter as CW

-- * Functions available to the RPC module

-- Just a test function
echo :: String -> WConfdMonad String
echo = return

-- ** Configuration related functions

checkConfigLock :: ClientId -> L.OwnerState -> WConfdMonad ()
checkConfigLock cid state = do
  la <- readLockAllocation
  unless (L.holdsLock cid ConfigLock state la)
         . failError $ "Requested lock " ++ show state
                       ++ " on the configuration missing"

-- | Read the configuration, checking that a shared lock is held.
-- If not, the call fails.
readConfig :: ClientId -> WConfdMonad ConfigData
readConfig ident = checkConfigLock ident L.OwnShared >> CW.readConfig

-- | Write the configuration, checking that an exclusive lock is held.
-- If not, the call fails.
writeConfig :: ClientId -> ConfigData -> WConfdMonad ()
writeConfig ident cdata = do
  checkConfigLock ident L.OwnExclusive
  -- V.verifyConfigErr cdata
  CW.writeConfig cdata

-- | Explicitly run verification of the configuration.
-- The caller doesn't need to hold the configuration lock.
verifyConfig :: WConfdMonad ()
verifyConfig = CW.readConfig >>= V.verifyConfigErr

-- *** Locks on the configuration (only transitional, will be removed later)

-- | Tries to acquire 'ConfigLock' for the client.
-- If the second parameter is set to 'True', the lock is acquired in
-- shared mode.
--
-- If the lock was successfully acquired, returns the current configuration
-- state.
lockConfig
    :: ClientId
    -> Bool -- ^ set to 'True' if the lock should be shared
    -> WConfdMonad (J.MaybeForJSON ConfigData)
lockConfig cid shared = do
  let reqtype = if shared then ReqShared else ReqExclusive
  -- warn if we already have the lock, this shouldn't happen
  la <- readLockAllocation
  when (L.holdsLock cid ConfigLock L.OwnShared la)
       . failError $ "Client " ++ show cid ++
                     " already holds a config lock"
  waiting <- tryUpdateLocks cid [(ConfigLock, reqtype)]
  liftM J.MaybeForJSON $ case waiting of
    []  -> liftM Just CW.readConfig
    _   -> return Nothing

-- | Release the config lock, if the client currently holds it.
unlockConfig
  :: ClientId -> WConfdMonad ()
unlockConfig cid = freeLocksLevel cid LevelConfig

-- | Force the distribution of configuration without actually modifying it.
-- It is not necessary to hold a lock for this operation.
flushConfig :: WConfdMonad ()
flushConfig = forceConfigStateDistribution

-- ** Temporary reservations related functions

dropAllReservations :: ClientId -> WConfdMonad ()
dropAllReservations cid =
  modifyTempResState (const . modify $ T.dropAllReservations cid)

-- *** DRBD

computeDRBDMap :: WConfdMonad T.DRBDMap
computeDRBDMap = uncurry T.computeDRBDMap =<< readTempResState

-- Allocate a drbd minor.
--
-- The free minor will be automatically computed from the existing devices.
-- A node can be given multiple times in order to allocate multiple minors.
-- The result is the list of minors, in the same order as the passed nodes.
allocateDRBDMinor
  :: T.InstanceUUID -> [T.NodeUUID] -> WConfdMonad [T.DRBDMinor]
allocateDRBDMinor inst nodes =
  modifyTempResStateErr (\cfg -> T.allocateDRBDMinor cfg inst nodes)

-- Release temporary drbd minors allocated for a given instance using
-- 'allocateDRBDMinor'.
--
-- This should be called on the error paths, on the success paths
-- it's automatically called by the ConfigWriter add and update
-- functions.
releaseDRBDMinors
  :: T.InstanceUUID -> WConfdMonad ()
releaseDRBDMinors inst = modifyTempResState (const $ T.releaseDRBDMinors inst)

-- *** MACs

-- Randomly generate a MAC for an instance and reserve it for
-- a given client.
generateMAC
  :: ClientId -> J.MaybeForJSON T.NetworkUUID -> WConfdMonad T.MAC
generateMAC cid (J.MaybeForJSON netId) = do
  g <- liftIO Rand.newStdGen
  modifyTempResStateErr $ T.generateMAC g cid netId

-- Reserves a MAC for an instance in the list of temporary reservations.
reserveMAC :: ClientId -> T.MAC -> WConfdMonad ()
reserveMAC = (modifyTempResStateErr .) . T.reserveMAC

-- *** DRBDSecrets

-- Randomly generate a DRBDSecret for an instance and reserves it for
-- a given client.
generateDRBDSecret :: ClientId -> WConfdMonad DRBDSecret
generateDRBDSecret cid = do
  g <- liftIO Rand.newStdGen
  modifyTempResStateErr $ T.generateDRBDSecret g cid

-- *** LVs

reserveLV :: ClientId -> LogicalVolume -> WConfdMonad ()
reserveLV jobId lv = modifyTempResStateErr $ T.reserveLV jobId lv

-- ** Locking related functions

-- | List the locks of a given owner (i.e., a job-id lockfile pair).
listLocks :: ClientId -> WConfdMonad [(GanetiLocks, L.OwnerState)]
listLocks cid = liftM (M.toList . L.listLocks cid) readLockAllocation

-- | List all active locks.
listAllLocks :: WConfdMonad [GanetiLocks]
listAllLocks = liftM L.listAllLocks readLockAllocation

-- | List all active locks with their owners.
listAllLocksOwners :: WConfdMonad [(GanetiLocks, [(ClientId, L.OwnerState)])]
listAllLocksOwners = liftM L.listAllLocksOwners readLockAllocation

-- | Get full information of the lock waiting status, i.e., provide
-- the information about all locks owners and all pending requests.
listLocksWaitingStatus :: WConfdMonad
                            ( [(GanetiLocks, [(ClientId, L.OwnerState)])]
                            , [(Integer, ClientId, [L.LockRequest GanetiLocks])]
                            )
listLocksWaitingStatus = liftM ( (L.listAllLocksOwners . LW.getAllocation)
                                 &&& (S.toList . LW.getPendingRequests) )
                         readLockWaiting

-- | Try to update the locks of a given owner (i.e., a job-id lockfile pair).
-- This function always returns immediately. If the lock update was possible,
-- the empty list is returned; otherwise, the lock status is left completly
-- unchanged, and the return value is the list of jobs which need to release
-- some locks before this request can succeed.
tryUpdateLocks :: ClientId -> GanetiLockRequest -> WConfdMonad [ClientId]
tryUpdateLocks cid req =
  liftM S.toList
  . (>>= toErrorStr)
  $ modifyLockWaiting (LW.updateLocks cid (fromGanetiLockRequest req))

-- | Try to update the locks of a given owner and make that a pending
-- request if not immediately possible.
updateLocksWaiting :: ClientId -> Integer
                      -> GanetiLockRequest -> WConfdMonad [ClientId]
updateLocksWaiting cid prio req =
  liftM S.toList
  . (>>= toErrorStr)
  . modifyLockWaiting
  $ LW.updateLocksWaiting prio cid (fromGanetiLockRequest req)

-- | Tell whether a given owner has pending requests.
hasPendingRequest :: ClientId -> WConfdMonad Bool
hasPendingRequest cid = liftM (LW.hasPendingRequest cid) readLockWaiting

-- | Free all locks of a given owner (i.e., a job-id lockfile pair).
freeLocks :: ClientId -> WConfdMonad ()
freeLocks cid =
  modifyLockWaiting_ $ LW.releaseResources cid

-- | Free all locks of a given owner (i.e., a job-id lockfile pair)
-- of a given level in the Ganeti sense (e.g., "cluster", "node").
freeLocksLevel :: ClientId -> LockLevel -> WConfdMonad ()
freeLocksLevel cid level =
  modifyLockWaiting_ $ LW.freeLocksPredicate ((==) level . lockLevel) cid

-- | Downgrade all locks of the given level to shared.
downGradeLocksLevel :: ClientId -> LockLevel -> WConfdMonad ()
downGradeLocksLevel cid level =
  modifyLockWaiting_ $ LW.downGradeLocksPredicate ((==) level . lockLevel) cid

-- | Intersect the possesed locks of an owner with a given set.
intersectLocks :: ClientId -> [GanetiLocks] -> WConfdMonad ()
intersectLocks cid locks = modifyLockWaiting_ $ LW.intersectLocks locks cid

-- | Opportunistically allocate locks for a given owner.
opportunisticLockUnion :: ClientId
                       -> [(GanetiLocks, L.OwnerState)]
                       -> WConfdMonad [GanetiLocks]
opportunisticLockUnion cid req =
  modifyLockWaiting $ LW.opportunisticLockUnion cid req

-- * The list of all functions exported to RPC.

exportedFunctions :: [Name]
exportedFunctions = [ 'echo
                    -- config
                    , 'readConfig
                    , 'writeConfig
                    , 'verifyConfig
                    , 'lockConfig
                    , 'unlockConfig
                    , 'flushConfig
                    -- temporary reservations (common)
                    , 'dropAllReservations
                    -- DRBD
                    , 'computeDRBDMap
                    , 'allocateDRBDMinor
                    , 'releaseDRBDMinors
                    -- MACs
                    , 'reserveMAC
                    , 'generateMAC
                    -- DRBD secrets
                    , 'generateDRBDSecret
                    -- LVs
                    , 'reserveLV
                    -- locking
                    , 'listLocks
                    , 'listAllLocks
                    , 'listAllLocksOwners
                    , 'listLocksWaitingStatus
                    , 'tryUpdateLocks
                    , 'updateLocksWaiting
                    , 'freeLocks
                    , 'freeLocksLevel
                    , 'downGradeLocksLevel
                    , 'intersectLocks
                    , 'opportunisticLockUnion
                    , 'hasPendingRequest
                    ]

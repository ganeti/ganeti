{-# LANGUAGE TemplateHaskell #-}

{-| The Ganeti WConfd core functions.

This module defines all the functions that WConfD exports for
RPC calls. They are in a separate module so that in a later
stage, TemplateHaskell can generate, e.g., the python interface
for those.

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

module Ganeti.WConfd.Core where

import Control.Arrow ((&&&))
import Control.Concurrent (myThreadId)
import Control.Lens.Setter (set)
import Control.Monad (liftM, unless)
import qualified Data.Map as M
import qualified Data.Set as S
import Language.Haskell.TH (Name)
import System.Posix.Process (getProcessID)
import qualified System.Random as Rand

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import qualified Ganeti.JSON as J
import qualified Ganeti.Locking.Allocation as L
import Ganeti.Logging (logDebug, logWarning)
import Ganeti.Locking.Locks ( GanetiLocks(ConfigLock, BGL)
                            , LockLevel(LevelConfig)
                            , lockLevel, LockLevel
                            , ClientType(ClientOther), ClientId(..) )
import qualified Ganeti.Locking.Waiting as LW
import Ganeti.Objects (ConfigData, DRBDSecret, LogicalVolume, Ip4Address)
import Ganeti.Objects.Lens (configClusterL, clusterMasterNodeL)
import Ganeti.WConfd.ConfigState (csConfigDataL)
import qualified Ganeti.WConfd.ConfigVerify as V
import Ganeti.WConfd.DeathDetection (cleanupLocks)
import Ganeti.WConfd.Language
import Ganeti.WConfd.Monad
import qualified Ganeti.WConfd.TempRes as T
import qualified Ganeti.WConfd.ConfigModifications as CM
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

-- | Read the configuration.
readConfig :: WConfdMonad ConfigData
readConfig = CW.readConfig

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
  let (reqtype, owntype) = if shared
                             then (ReqShared, L.OwnShared)
                             else (ReqExclusive, L.OwnExclusive)
  la <- readLockAllocation
  if L.holdsLock cid ConfigLock owntype la
    then do
      -- warn if we already have the lock, but continue (with no-op)
      -- on the locks
      logWarning $ "Client " ++ show cid ++ " asked to lock the config"
                   ++ " while owning the lock"
      liftM (J.MaybeForJSON . Just) CW.readConfig
    else do
      waiting <- tryUpdateLocks cid [(ConfigLock, reqtype)]
      liftM J.MaybeForJSON $ case waiting of
        []  -> liftM Just CW.readConfig
        _   -> return Nothing

-- | Release the config lock, if the client currently holds it.
unlockConfig
  :: ClientId -> WConfdMonad ()
unlockConfig cid = freeLocksLevel cid LevelConfig

-- | Write the configuration, if the config lock is held exclusively,
-- and release the config lock. It the caller does not have the config
-- lock, return False.
writeConfigAndUnlock :: ClientId -> ConfigData -> WConfdMonad Bool
writeConfigAndUnlock cid cdata = do
  la <- readLockAllocation
  if L.holdsLock cid ConfigLock L.OwnExclusive la
    then do
      CW.writeConfig cdata
      unlockConfig cid
      return True
    else do
      logWarning $ show cid ++ " tried writeConfigAndUnlock without owning"
                   ++ " the config lock"
      return False

-- | Force the distribution of configuration without actually modifying it.
-- It is not necessary to hold a lock for this operation.
flushConfig :: WConfdMonad ()
flushConfig = forceConfigStateDistribution Everywhere

-- | Force the distribution of configuration to a given group without actually
-- modifying it. It is not necessary to hold a lock for this operation.
flushConfigGroup :: String -> WConfdMonad ()
flushConfigGroup = forceConfigStateDistribution . ToGroups . S.singleton

-- ** Temporary reservations related functions

dropAllReservations :: ClientId -> WConfdMonad ()
dropAllReservations cid =
  modifyTempResState (const $ T.dropAllReservations cid)

-- *** DRBD

computeDRBDMap :: WConfdMonad T.DRBDMap
computeDRBDMap = uncurry T.computeDRBDMap =<< readTempResState

-- Allocate a drbd minor.
--
-- The free minor will be automatically computed from the existing devices.
-- A node can not be given multiple times.
-- The result is the list of minors, in the same order as the passed nodes.
allocateDRBDMinor
  :: T.DiskUUID -> [T.NodeUUID] -> WConfdMonad [T.DRBDMinor]
allocateDRBDMinor disk nodes =
  modifyTempResStateErr (\cfg -> T.allocateDRBDMinor cfg disk nodes)

-- Release temporary drbd minors allocated for a given disk using
-- 'allocateDRBDMinor'.
--
-- This should be called on the error paths, on the success paths
-- it's automatically called by the ConfigWriter add and update
-- functions.
releaseDRBDMinors
  :: T.DiskUUID -> WConfdMonad ()
releaseDRBDMinors disk = modifyTempResState (const $ T.releaseDRBDMinors disk)

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

-- *** IPv4s

-- | Reserve a given IPv4 address for use by an instance.
reserveIp :: ClientId -> T.NetworkUUID -> Ip4Address -> Bool -> WConfdMonad ()
reserveIp = (((modifyTempResStateErr .) .) .) . T.reserveIp

-- | Give a specific IP address back to an IP pool.
-- The IP address is returned to the IP pool designated by network id
-- and marked as reserved.
releaseIp :: ClientId -> T.NetworkUUID -> Ip4Address -> WConfdMonad ()
releaseIp = (((modifyTempResStateErr .) const .) .) . T.releaseIp

-- Find a free IPv4 address for an instance and reserve it.
generateIp :: ClientId -> T.NetworkUUID -> WConfdMonad Ip4Address
generateIp = (modifyTempResStateErr .) . T.generateIp

-- | Commit all reserved/released IP address to an IP pool.
-- The IP addresses are taken from the network's IP pool and marked as
-- reserved/free for instances.
--
-- Note that the reservations are kept, they are supposed to be cleaned
-- when a job finishes.
commitTemporaryIps :: ClientId -> WConfdMonad ()
commitTemporaryIps = modifyConfigDataErr_ . T.commitReservedIps

-- | Immediately release an IP address, without using the reservations pool.
commitReleaseTemporaryIp
  :: T.NetworkUUID -> Ip4Address -> WConfdMonad ()
commitReleaseTemporaryIp net_uuid addr =
  modifyConfigDataErr_ (const $ T.commitReleaseIp net_uuid addr)

-- | List all IP reservations for the current client.
--
-- This function won't be needed once the corresponding calls are moved to
-- WConfd.
listReservedIps :: ClientId -> WConfdMonad [T.IPv4Reservation]
listReservedIps jobId =
  liftM (S.toList . T.listReservedIps jobId . snd) readTempResState

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
  $ LW.safeUpdateLocksWaiting prio cid (fromGanetiLockRequest req)

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

-- | Opprtunistially allocate locks for a given owner, requesting a
-- certain minimum of success.
guardedOpportunisticLockUnion :: Int
                                 -> ClientId
                                 -> [(GanetiLocks, L.OwnerState)]
                                 -> WConfdMonad [GanetiLocks]
guardedOpportunisticLockUnion count cid req =
  modifyLockWaiting $ LW.guardedOpportunisticLockUnion count cid req

-- * Prepareation for cluster destruction

-- | Prepare daemon for cluster destruction. This consists of
-- verifying that the requester owns the BGL exclusively, transfering the BGL
-- to WConfD itself, and modifying the configuration so that no
-- node is the master any more. Note that, since we own the BGL exclusively,
-- we can safely modify the configuration, as no other process can request
-- changes.
prepareClusterDestruction :: ClientId -> WConfdMonad ()
prepareClusterDestruction cid = do
  la <- readLockAllocation
  unless (L.holdsLock cid BGL L.OwnExclusive la)
    . failError $ "Cluster destruction requested without owning BGL exclusively"
  logDebug $ "preparing cluster destruction as requested by " ++ show cid
  -- transfer BGL to ourselfs. The do this, by adding a super-priority waiting
  -- request and then releasing the BGL of the requestor.
  dh <- daemonHandle
  pid <- liftIO getProcessID
  tid <- liftIO myThreadId
  let mycid = ClientId { ciIdentifier = ClientOther $ "wconfd-" ++ show tid
                       , ciLockFile = dhLivelock dh
                       , ciPid = pid
                       }
  _ <- modifyLockWaiting $ LW.updateLocksWaiting
                           (fromIntegral C.opPrioHighest - 1) mycid
                           [L.requestExclusive BGL]
  _ <- modifyLockWaiting $ LW.updateLocks cid [L.requestRelease BGL]
  -- To avoid beeing restarted we change the configuration to a no-master
  -- state.
  modifyConfigState $ (,) ()
    . set (csConfigDataL . configClusterL . clusterMasterNodeL) ""


-- * The list of all functions exported to RPC.

exportedFunctions :: [Name]
exportedFunctions = [ 'echo
                    , 'cleanupLocks
                    , 'prepareClusterDestruction
                    -- config
                    , 'readConfig
                    , 'writeConfig
                    , 'verifyConfig
                    , 'lockConfig
                    , 'unlockConfig
                    , 'writeConfigAndUnlock
                    , 'flushConfig
                    , 'flushConfigGroup
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
                    -- IPv4s
                    , 'reserveIp
                    , 'releaseIp
                    , 'generateIp
                    , 'commitTemporaryIps
                    , 'commitReleaseTemporaryIp
                    , 'listReservedIps
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
                    , 'guardedOpportunisticLockUnion
                    , 'hasPendingRequest
                    ]
                    ++ CM.exportedFunctions

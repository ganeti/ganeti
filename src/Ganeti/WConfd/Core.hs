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

import Control.Monad (liftM, unless, when)
import qualified Data.Map as M
import qualified Data.Set as S
import Language.Haskell.TH (Name)

import Ganeti.BasicTypes
import qualified Ganeti.JSON as J
import qualified Ganeti.Locking.Allocation as L
import Ganeti.Locking.Locks ( GanetiLocks(ConfigLock), LockLevel(LevelConfig)
                            , lockLevel, LockLevel, ClientId )
import Ganeti.Objects (ConfigData)
import Ganeti.WConfd.Language
import Ganeti.WConfd.Monad
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
writeConfig ident cdata =
  checkConfigLock ident L.OwnExclusive >> CW.writeConfig cdata

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

-- ** Locking related functions

-- | List the locks of a given owner (i.e., a job-id lockfile pair).
listLocks :: ClientId -> WConfdMonad [(GanetiLocks, L.OwnerState)]
listLocks cid = liftM (M.toList . L.listLocks cid) readLockAllocation

-- | Try to update the locks of a given owner (i.e., a job-id lockfile pair).
-- This function always returns immediately. If the lock update was possible,
-- the empty list is returned; otherwise, the lock status is left completly
-- unchanged, and the return value is the list of jobs which need to release
-- some locks before this request can succeed.
tryUpdateLocks :: ClientId -> GanetiLockRequest -> WConfdMonad [ClientId]
tryUpdateLocks cid req =
  liftM S.toList
  . (>>= toErrorStr)
  $ modifyLockAllocation (L.updateLocks cid (fromGanetiLockRequest req))

-- | Free all locks of a given owner (i.e., a job-id lockfile pair).
freeLocks :: ClientId -> WConfdMonad ()
freeLocks cid =
  modifyLockAllocation_ (`L.freeLocks` cid)

-- | Free all locks of a given owner (i.e., a job-id lockfile pair)
-- of a given level in the Ganeti sense (e.g., "cluster", "node").
freeLocksLevel :: ClientId -> LockLevel -> WConfdMonad ()
freeLocksLevel cid level =
  modifyLockAllocation_ (L.freeLocksPredicate ((==) level . lockLevel)
                           `flip` cid)

-- | Downgrade all locks of the given level to shared.
downGradeLocksLevel :: ClientId -> LockLevel -> WConfdMonad ()
downGradeLocksLevel cid level =
  modifyLockAllocation_ $ L.downGradePredicate ((==) level . lockLevel) cid

-- | Intersect the possesed locks of an owner with a given set.
intersectLocks :: ClientId -> [GanetiLocks] -> WConfdMonad ()
intersectLocks cid =
 modifyLockAllocation_ . L.intersectLocks cid

-- | Opportunistically allocate locks for a given owner.
opportunisticLockUnion :: ClientId
                       -> [(GanetiLocks, L.OwnerState)]
                       -> WConfdMonad [GanetiLocks]
opportunisticLockUnion cid req =
  liftM S.toList
  . modifyLockAllocation
  $ L.opportunisticLockUnion cid req

-- * The list of all functions exported to RPC.

exportedFunctions :: [Name]
exportedFunctions = [ 'echo
                    , 'readConfig
                    , 'writeConfig
                    , 'lockConfig
                    , 'unlockConfig
                    , 'listLocks
                    , 'tryUpdateLocks
                    , 'freeLocks
                    , 'freeLocksLevel
                    , 'downGradeLocksLevel
                    , 'intersectLocks
                    , 'opportunisticLockUnion
                    ]

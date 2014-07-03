{-# LANGUAGE MultiParamTypeClasses, TypeFamilies #-}

{-| Common types and functions for persistent resources

In particular:
- locks
- temporary reservations

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

module Ganeti.WConfd.Persistent
  ( Persistent(..)
  , writePersistentAsyncTask
  , readPersistent
  , persistentLocks
  , persistentTempRes
  ) where

import Control.Monad.Error
import System.Directory (doesFileExist)
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Errors
import qualified Ganeti.JSON as J
import Ganeti.Locking.Waiting (emptyWaiting)
import Ganeti.Locking.Locks (ClientId(..), GanetiLockWaiting)
import Ganeti.Logging
import qualified Ganeti.Path as Path
import Ganeti.WConfd.Core (freeLocks, dropAllReservations)
import Ganeti.WConfd.Monad
import Ganeti.WConfd.TempRes (TempResState, emptyTempResState)
import Ganeti.Utils.Atomic
import Ganeti.Utils.AsyncWorker

-- * Common definitions

-- ** The data type that collects all required operations

-- | A collection of operations needed for persisting a resource.
data Persistent a = Persistent
  { persName :: String
  , persPath :: IO FilePath
  , persEmpty :: a
  , persCleanup :: ClientId -> WConfdMonad ()
  -- ^ The clean-up action needs to be a full 'WConfdMonad' action as it
  -- might need to do some complex processing, such as notifying
  -- clients that some locks are available.
  }

-- ** Common functions

-- | Construct an asynchronous worker whose action is to save the
-- current state of the persistent state.
-- The worker's action reads the state using the given @IO@
-- action. Any inbetween changes to the file are tacitly ignored.
writePersistentAsyncTask
  :: (J.JSON a) => Persistent a -> IO a -> ResultG (AsyncWorker () ())
writePersistentAsyncTask pers readAction = mkAsyncWorker_ $
  catchError (do
    let prefix = "Async. " ++ persName pers ++ " writer: "
    fpath <- liftIO $ persPath pers
    logDebug $ prefix ++ "Starting write to " ++ fpath
    state <- liftIO readAction
    toErrorBase . liftIO . atomicWriteFile fpath . J.encode $ state
    logDebug $ prefix ++ "written"
  ) (logEmergency . (++) ("Can't write " ++ persName pers ++ " state: ")
                  . show)

-- | Load a persistent data structure from disk.
readPersistent :: (J.JSON a) => Persistent a -> ResultG a
readPersistent pers = do
  logDebug $ "Reading " ++ persName pers
  file <- liftIO $ persPath pers
  file_present <- liftIO $ doesFileExist file
  if file_present
    then
      liftIO (persPath pers >>= readFile)
        >>= J.fromJResultE ("parsing " ++ persName pers) . J.decodeStrict
    else do
      logInfo $ "Note: No saved data for " ++ persName pers
                ++ ", tacitly assuming empty."
      return (persEmpty pers)

-- * Implementations

-- ** Locks

persistentLocks :: Persistent GanetiLockWaiting
persistentLocks = Persistent
  { persName = "lock allocation state"
  , persPath = Path.lockStatusFile
  , persEmpty = emptyWaiting
  , persCleanup = freeLocks
  }

-- ** Temporary reservations

persistentTempRes :: Persistent TempResState
persistentTempRes = Persistent
  { persName = "temporary reservations"
  , persPath = Path.tempResStatusFile
  , persEmpty = emptyTempResState
  , persCleanup = dropAllReservations
  }

{-# LANGUAGE MultiParamTypeClasses, TypeFamilies #-}

{-| Common types and functions for persistent resources

In particular:
- locks
- temporary reservations

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
import Ganeti.Locking.Waiting (emptyWaiting, releaseResources)
import Ganeti.Locking.Locks (ClientId(..), GanetiLockWaiting)
import Ganeti.Logging
import qualified Ganeti.Path as Path
import Ganeti.WConfd.Monad
import Ganeti.WConfd.TempRes ( TempResState, emptyTempResState
                             , dropAllReservations)
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
  , persCleanup = modifyLockWaiting_ . releaseResources
  }

-- ** Temporary reservations

persistentTempRes :: Persistent TempResState
persistentTempRes = Persistent
  { persName = "temporary reservations"
  , persPath = Path.tempResStatusFile
  , persEmpty = emptyTempResState
  , persCleanup = modifyTempResState . const . dropAllReservations
  }

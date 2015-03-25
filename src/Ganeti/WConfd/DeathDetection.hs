{-| Utility function for detecting the death of a job holding resources

To clean up resources owned by jobs that die for some reason, we need
to detect whether a job is still alive. As we have no control over PID
reuse, our approach is that each requester for a resource has to provide
a file where it owns an exclusive lock on. The kernel will make sure the
lock is removed if the process dies. We can probe for such a lock by
requesting a shared lock on the file.

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

module Ganeti.WConfd.DeathDetection
  ( cleanupLocksTask
  , cleanupLocks
  ) where

import Control.Concurrent (threadDelay)
import qualified Control.Exception as E
import Control.Monad
import System.Directory (removeFile)

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import qualified Ganeti.Locking.Allocation as L
import Ganeti.Locking.Locks (ClientId(..))
import Ganeti.Logging.Lifted (logDebug, logInfo)
import Ganeti.Utils.Livelock
import Ganeti.WConfd.Monad
import Ganeti.WConfd.Persistent

-- | Interval to run clean-up tasks in microseconds
cleanupInterval :: Int
cleanupInterval = C.wconfdDeathdetectionIntervall * 1000000

-- | Go through all owners once and clean them up, if they're dead.
cleanupLocks :: WConfdMonad ()
cleanupLocks = do
  owners <- liftM L.lockOwners readLockAllocation
  mylivelock <- liftM dhLivelock daemonHandle
  logDebug $ "Current lock owners: " ++ show owners
  let cleanupIfDead owner = do
        let fpath = ciLockFile owner
        died <- if fpath == mylivelock
                  then return False
                  else liftIO (isDead fpath)
        when died $ do
          logInfo $ show owner ++ " died, releasing locks and reservations"
          persCleanup persistentTempRes owner
          persCleanup persistentLocks owner
          _ <- liftIO . E.try $ removeFile fpath
               :: WConfdMonad (Either IOError ())
          return ()
  mapM_ cleanupIfDead owners

-- | Thread periodically cleaning up locks of lock owners that died.
cleanupLocksTask :: WConfdMonadInt ()
cleanupLocksTask = forever . runResultT $ do
  logDebug "Death detection timer fired"
  cleanupLocks
  remainingFiles <- liftIO listLiveLocks
  mylivelock <- liftM dhLivelock daemonHandle
  logDebug $ "Livelockfiles remaining: " ++ show remainingFiles
  let cleanupStaleIfDead fpath = do
        died <- if fpath == mylivelock
                  then return False
                  else liftIO (isDead fpath)
        when died $ do
          logInfo $ "Cleaning up stale file " ++ fpath
          _ <- liftIO . E.try $ removeFile fpath
               :: WConfdMonad (Either IOError ())
          return ()
  mapM_ cleanupStaleIfDead remainingFiles
  liftIO $ threadDelay cleanupInterval

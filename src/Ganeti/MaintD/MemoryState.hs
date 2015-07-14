{-| Memory copy of the state of the maintenance daemon.

While the autoritative state of the maintenance daemon is
stored in the configuration, the daemon keeps a copy of some
values at run time, so that they can easily be exposed over
HTTP.

This module also provides functions for the mirrored information
to update both, the authoritative state and the in-memory copy.

-}

{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.MaintD.MemoryState
  ( MemoryState(..)
  , emptyMemoryState
  , getJobs
  , clearJobs
  , appendJobs
  ) where

import Control.Monad.IO.Class (liftIO)
import Data.IORef (IORef, atomicModifyIORef)

import Ganeti.BasicTypes (ResultT, withErrorT)
import Ganeti.Types (JobId)
import Ganeti.Utils (ordNub)
import Ganeti.WConfd.Client ( runNewWConfdClient, maintenanceJobs, runModifyRpc
                            , clearMaintdJobs, appendMaintdJobs )

-- | In-memory copy of parts of the state of the maintenance
-- daemon.
data MemoryState = MemoryState
  { msJobs :: [ JobId ]
  }

-- | Inital state of the in-memory copy. All parts will be updated
-- before use, after one round at the latest this copy is up to date.
emptyMemoryState :: MemoryState
emptyMemoryState = MemoryState {
                     msJobs = []
                   }

-- | Get the list of jobs from the authoritative copy, and update the
-- in-memory copy as well.
getJobs :: IORef MemoryState -> ResultT String IO [JobId]
getJobs memstate = do
  jobs <- withErrorT show $ runNewWConfdClient maintenanceJobs
  liftIO . atomicModifyIORef memstate $ \ s -> (s { msJobs = jobs }, ())
  return jobs

-- | Reset the list of active jobs.
clearJobs :: IORef MemoryState -> IO ()
clearJobs memstate = do
  runModifyRpc clearMaintdJobs
  atomicModifyIORef memstate $ \ s -> ( s { msJobs = [] }, ())

-- | Append jobs to the list of active jobs, if not present already
appendJobs :: IORef MemoryState -> [JobId] -> IO ()
appendJobs memstate jobs = do
  runModifyRpc $ appendMaintdJobs jobs
  atomicModifyIORef memstate
    $ \ s -> ( s { msJobs = ordNub $ msJobs s ++ jobs }, ())

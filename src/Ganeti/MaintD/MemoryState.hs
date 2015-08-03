{-# LANGUAGE TemplateHaskell #-}

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
  , getEvacuated
  , addEvacuated
  , rmEvacuated
  , getIncidents
  , updateIncident
  , rmIncident
  ) where

import Control.Monad.IO.Class (liftIO)
import Data.IORef (IORef)

import Ganeti.BasicTypes (ResultT, withErrorT)
import Ganeti.Lens (makeCustomLenses)
import Ganeti.Objects.Maintenance (Incident)
import Ganeti.Types (JobId, uuidOf)
import Ganeti.Utils (ordNub)
import Ganeti.Utils.IORef (atomicModifyWithLens_)
import Ganeti.WConfd.Client ( runNewWConfdClient, maintenanceJobs, runModifyRpc
                            , clearMaintdJobs, appendMaintdJobs
                            , maintenanceEvacuated, addMaintdEvacuated
                            , rmMaintdEvacuated
                            , maintenanceIncidents, updateMaintdIncident
                            , rmMaintdIncident )

-- | In-memory copy of parts of the state of the maintenance
-- daemon.
data MemoryState = MemoryState
  { msJobs :: [ JobId ]
  , msEvacuated :: [ String ]
  , msIncidents :: [ Incident ]
  }

$(makeCustomLenses ''MemoryState)

-- | Inital state of the in-memory copy. All parts will be updated
-- before use, after one round at the latest this copy is up to date.
emptyMemoryState :: MemoryState
emptyMemoryState = MemoryState { msJobs = []
                               , msEvacuated = []
                               , msIncidents = []
                               }

-- | Get the list of jobs from the authoritative copy, and update the
-- in-memory copy as well.
getJobs :: IORef MemoryState -> ResultT String IO [JobId]
getJobs memstate = do
  jobs <- withErrorT show $ runNewWConfdClient maintenanceJobs
  liftIO . atomicModifyWithLens_ memstate msJobsL $ const jobs
  return jobs

-- | Reset the list of active jobs.
clearJobs :: IORef MemoryState -> IO ()
clearJobs memstate = do
  runModifyRpc clearMaintdJobs
  atomicModifyWithLens_ memstate msJobsL $ const []

-- | Append jobs to the list of active jobs, if not present already
appendJobs :: IORef MemoryState -> [JobId] -> IO ()
appendJobs memstate jobs = do
  runModifyRpc $ appendMaintdJobs jobs
  atomicModifyWithLens_ memstate msJobsL $ ordNub . (++ jobs)

-- | Get the list of recently evacuated instances from the authoritative
-- copy and update the in-memory state.
getEvacuated :: IORef MemoryState -> ResultT String IO [String]
getEvacuated memstate = do
  evac <- withErrorT show $ runNewWConfdClient maintenanceEvacuated
  liftIO . atomicModifyWithLens_ memstate msEvacuatedL $ const evac
  return evac

-- | Add names to the list of recently evacuated instances.
addEvacuated :: IORef MemoryState -> [String] -> IO ()
addEvacuated memstate names = do
  runModifyRpc $ addMaintdEvacuated names
  atomicModifyWithLens_ memstate msEvacuatedL $ ordNub . (++ names)

-- | Remove a name from the list of recently evacuated instances.
rmEvacuated :: IORef MemoryState -> String -> IO ()
rmEvacuated memstate name = do
  runModifyRpc $ rmMaintdEvacuated name
  atomicModifyWithLens_ memstate msEvacuatedL $ filter (/= name)

-- | Get the list of incidents fo the authoritative copy and update the
-- in-memory state.
getIncidents :: IORef MemoryState -> ResultT String IO  [Incident]
getIncidents memstate = do
  incidents <- withErrorT show $ runNewWConfdClient maintenanceIncidents
  liftIO . atomicModifyWithLens_ memstate msIncidentsL $ const incidents
  return incidents

-- | Update an incident.
updateIncident :: IORef MemoryState -> Incident -> IO ()
updateIncident memstate incident = do
  runModifyRpc $ updateMaintdIncident incident
  atomicModifyWithLens_ memstate msIncidentsL
    $ (incident :) . filter ((/= uuidOf incident) . uuidOf)

-- | Remove an incident.
rmIncident :: IORef MemoryState -> String -> IO ()
rmIncident memstate uuid = do
  runModifyRpc $ rmMaintdIncident uuid
  atomicModifyWithLens_ memstate msIncidentsL
    $ filter ((/= uuid) . uuidOf)

{-| Incident failing in the maintenace daemon

This module implements the treatment of an incident, once
a job failed.

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

module Ganeti.MaintD.FailIncident
 ( failIncident
 ) where

import Control.Exception.Lifted (bracket)
import Control.Lens.Setter (over)
import Control.Monad (liftM, when)
import Control.Monad.IO.Class (liftIO)
import Data.IORef (IORef)
import System.IO.Error (tryIOError)

import Ganeti.BasicTypes (ResultT, mkResultT, GenericResult(..))
import qualified Ganeti.Constants as C
import Ganeti.JQueue (currentTimestamp)
import Ganeti.Jobs (execJobsWaitOkJid)
import Ganeti.Logging.Lifted
import qualified Ganeti.Luxi as L
import Ganeti.MaintD.MemoryState (MemoryState, getIncidents, updateIncident)
import Ganeti.MaintD.Utils (annotateOpCode)
import Ganeti.Objects.Lens (incidentJobsL)
import Ganeti.Objects.Maintenance (Incident(..), RepairStatus(..))
import Ganeti.OpCodes (OpCode(..))
import qualified Ganeti.Path as Path
import Ganeti.Types (JobId, fromJobId, TagKind(..))

-- | Mark an incident as failed.
markAsFailed :: IORef MemoryState -> Incident -> ResultT String IO ()
markAsFailed memstate incident = do
  let uuid = incidentUuid incident
      newtag = C.maintdFailureTagPrefix ++ uuid
  logInfo $ "Marking incident " ++ uuid ++ " as failed"
  now <- liftIO currentTimestamp
  luxiSocket <- liftIO Path.defaultQuerySocket
  jids <- bracket (mkResultT . liftM (either (Bad . show) Ok)
                   . tryIOError $ L.getLuxiClient luxiSocket)
                  (liftIO . L.closeClient)
                  (mkResultT . execJobsWaitOkJid
                     [[ annotateOpCode "marking incident handling as failed" now
                        . OpTagsSet TagKindNode [ newtag ]
                        . Just $ incidentNode incident ]])
  let incident' = over incidentJobsL (++ jids)
                    $ incident { incidentRepairStatus = RSFailed
                               , incidentTag = newtag
                               }
  liftIO $ updateIncident memstate incident'

-- | Mark the incident, if any, belonging to the given job as
-- failed after having tagged it appropriately.
failIncident :: IORef MemoryState -> JobId -> ResultT String IO ()
failIncident memstate jid = do
  incidents <- getIncidents memstate
  let affected = filter (elem jid . incidentJobs) incidents
  when (null affected) . logInfo
    $ "Job " ++ show (fromJobId jid) ++ " does not belong to an incident"
  mapM_ (markAsFailed memstate) affected

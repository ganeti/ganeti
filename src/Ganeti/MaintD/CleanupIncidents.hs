{-| Incident clean up in the maintenance daemon.

This module implements the clean up of events that are finished,
and acknowledged as such by the user.

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

module Ganeti.MaintD.CleanupIncidents
  ( cleanupIncidents
  ) where

import Control.Arrow ((&&&))
import Control.Monad (unless)
import Control.Monad.IO.Class (liftIO)
import qualified Data.ByteString.UTF8 as UTF8
import Data.IORef (IORef)

import Ganeti.BasicTypes (ResultT, mkResultT)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node
import Ganeti.Logging.Lifted
import Ganeti.MaintD.MemoryState (MemoryState, getIncidents, rmIncident)
import Ganeti.Objects.Maintenance (Incident(..), RepairStatus(..))
import Ganeti.Utils (logAndBad)

-- | Remove a single incident, provided the corresponding tag
-- is no longer present.
cleanupIncident :: IORef MemoryState
                -> Node.List
                -> Incident
                -> ResultT String IO ()
cleanupIncident memstate nl incident = do
  let location = incidentNode incident
      uuid = incidentUuid incident
      tag = incidentTag incident
      nodes = filter ((==) location . Node.name) $ Container.elems nl
  case nodes of
    [] -> do
            logInfo $ "No node any more with name " ++ location
                       ++ "; will forget event " ++ UTF8.toString uuid
            liftIO . rmIncident memstate $ UTF8.toString uuid
    [nd] -> unless (tag `elem` Node.nTags nd) $ do
              logInfo $ "Tag " ++ tag ++ " removed on " ++ location
                        ++ "; will forget event " ++ UTF8.toString uuid
              liftIO . rmIncident memstate $ UTF8.toString uuid
    _ -> mkResultT . logAndBad
           $ "Found More than one node with name " ++ location

-- | Remove all incidents from the record that are in a final state
-- and additionally the node tag for that incident has been removed.
cleanupIncidents :: IORef MemoryState -> Node.List -> ResultT String IO ()
cleanupIncidents memstate nl = do
  incidents <- getIncidents memstate
  let finalized = filter ((> RSPending) . incidentRepairStatus) incidents
  logDebug . (++) "Finalized incidents " . show
    $ map (incidentNode &&& incidentUuid) finalized
  mapM_ (cleanupIncident memstate nl) finalized

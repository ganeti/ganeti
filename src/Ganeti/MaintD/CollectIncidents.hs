{-| Discovery of incidents by the maintenance daemon.

This module implements the querying of all monitoring
daemons for the value of the node-status data collector.
Any new incident gets registered.

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

module Ganeti.MaintD.CollectIncidents
  ( collectIncidents
  ) where

import Control.Applicative (liftA2)
import Control.Monad (unless)
import Control.Monad.IO.Class (liftIO)
import qualified Data.ByteString.UTF8 as UTF8
import Data.IORef (IORef)
import Network.Curl
import System.Time (getClockTime)
import qualified Text.JSON as J

import Ganeti.BasicTypes (ResultT)
import qualified Ganeti.Constants as C
import qualified Ganeti.DataCollectors.Diagnose as D
import Ganeti.DataCollectors.Types (getCategoryName)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node
import Ganeti.Logging.Lifted
import Ganeti.MaintD.MemoryState (MemoryState, getIncidents, updateIncident)
import Ganeti.Objects.Maintenance
import Ganeti.Utils (newUUID)

-- | Query a node, unless it is offline, and return
-- the paylod of the report, if available. For offline
-- nodes return nothing.
queryStatus :: Node.Node -> IO (Maybe J.JSValue)
queryStatus node = do
  let name = Node.name node
  let url = name ++ ":" ++ show C.defaultMondPort
            ++ "/1/report/" ++ maybe "default" getCategoryName D.dcCategory
            ++ "/" ++ D.dcName
  if Node.offline node
    then do
      logDebug $ "Not asking " ++ name ++ "; it is offline"
      return Nothing
    else do
      (code, body) <- liftIO $ curlGetString url []
      case code of
        CurlOK ->
          case J.decode body of
            J.Ok r -> return $ Just r
            _ -> return Nothing
        _ -> do
          logWarning $ "Failed to contact " ++ name
          return Nothing

-- | Update the status of one node.
updateNode :: IORef MemoryState -> Node.Node -> ResultT String IO ()
updateNode memstate node = do
  let name = Node.name node
  logDebug $ "Inspecting " ++ name
  report <- liftIO $ queryStatus node
  case report of
    Just (J.JSObject obj)
      | Just orig@(J.JSObject origobj) <- lookup "data" $ J.fromJSObject obj,
        Just s <- lookup "status" $ J.fromJSObject origobj,
        J.Ok state <- J.readJSON s,
        state /= RANoop -> do
          let origs = J.encode orig
          logDebug $ "Relevant event on " ++ name ++ ": " ++ origs
          incidents <- getIncidents memstate
          unless (any (liftA2 (&&)
                        ((==) name . incidentNode)
                        ((==) orig . incidentOriginal)) incidents) $ do
            logInfo $ "Registering new incident on " ++ name ++ ": " ++ origs
            uuid <- liftIO newUUID
            now <- liftIO getClockTime
            let tag = C.maintdSuccessTagPrefix ++ uuid
                incident = Incident { incidentOriginal = orig
                                    , incidentAction = state
                                    , incidentRepairStatus = RSNoted
                                    , incidentJobs = []
                                    , incidentNode = name
                                    , incidentTag = tag
                                    , incidentUuid = UTF8.fromString uuid
                                    , incidentCtime = now
                                    , incidentMtime = now
                                    , incidentSerial = 1
                                    }
            liftIO $ updateIncident memstate incident
    _ -> return ()


-- | Query all MonDs for updates on the node-status.
collectIncidents :: IORef MemoryState -> Node.List -> ResultT String IO ()
collectIncidents memstate nl = do
  _ <- getIncidents memstate -- always update the memory state,
                             -- even if we do not observe anything
  logDebug "Querying all nodes for incidents"
  mapM_ (updateNode memstate) $ Container.elems nl

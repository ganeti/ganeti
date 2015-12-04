{-| Incident handling in the maintenance daemon.

This module implements the submission of actions for ongoing
repair events reported by the node-status data collector.

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

module Ganeti.MaintD.HandleIncidents
  ( handleIncidents
  ) where

import Control.Arrow ((&&&))
import Control.Exception.Lifted (bracket)
import Control.Lens.Setter (over)
import Control.Monad (foldM)
import Control.Monad.IO.Class (liftIO)
import qualified Data.ByteString.UTF8 as UTF8
import Data.Function (on)
import Data.IORef (IORef)
import qualified Data.Map as Map
import qualified Data.Set as Set
import qualified Text.JSON as J

import Ganeti.BasicTypes ( GenericResult(..), ResultT, mkResultT, Down(..))
import qualified Ganeti.Constants as C
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..), defaultOptions)
import Ganeti.HTools.Cluster.Evacuate (tryNodeEvac, EvacSolution(..))
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types (Idx)
import Ganeti.JQueue (currentTimestamp)
import Ganeti.Jobs (execJobsWaitOkJid, submitJobs, forceFailover)
import Ganeti.Logging.Lifted
import qualified Ganeti.Luxi as L
import Ganeti.MaintD.MemoryState ( MemoryState, getIncidents, rmIncident
                                 , updateIncident, appendJobs)
import Ganeti.MaintD.Utils (annotateOpCode, getRepairCommand)
import Ganeti.Objects.Lens (incidentJobsL)
import Ganeti.Objects.Maintenance ( RepairStatus(..), RepairAction(..)
                                  , Incident(..))
import Ganeti.OpCodes (OpCode(..), MetaOpCode)
import qualified Ganeti.Path as Path
import Ganeti.Types ( cTimeOf, uuidOf, mkNonEmpty, fromJobId
                    , EvacMode(..), TagKind(..))
import Ganeti.Utils (maxBy, logAndBad)

-- | Given two incidents, choose the more severe one; for equally severe
-- ones the older (by creation timestamp).
moreSevereIncident :: Incident -> Incident -> Incident
moreSevereIncident = maxBy (compare `on` incidentAction &&& (Down . cTimeOf))

-- | From a given list of incidents, return, for each node,
-- the one with the most severe action.
rankIncidents :: [Incident] -> Map.Map String Incident
rankIncidents = foldl (\m i -> Map.insertWith moreSevereIncident
                                 (incidentNode i) i m) Map.empty

-- | Generate a job to drain a given node.
drainJob :: String -> ResultT String IO [ MetaOpCode ]
drainJob name = do
  name' <- mkNonEmpty name
  now <- liftIO currentTimestamp
  return $ map (annotateOpCode ("Draining " ++ name) now)
    [ OpNodeSetParams { opNodeName = name'
                      , opNodeUuid = Nothing
                      , opForce = True
                      , opHvState = Nothing
                      , opDiskState = Nothing
                      , opMasterCandidate = Nothing
                      , opOffline = Nothing
                      , opDrained = Just True
                      , opAutoPromote = False
                      , opMasterCapable = Nothing
                      , opVmCapable = Nothing
                      , opSecondaryIp = Nothing
                      , opgenericNdParams = Nothing
                      , opPowered = Nothing
                      } ]

-- | Submit and register the next job for a node evacuation.
handleEvacuation :: L.Client -- ^ Luxi client to use
                 -> IORef MemoryState -- ^ memory state of the daemon
                 -> (Group.List, Node.List, Instance.List) -- ^ cluster
                 -> Idx -- ^ index of the node to evacuate
                 -> Bool -- ^ whether to try migrations
                 -> Set.Set Int -- ^ allowed nodes for evacuation
                 -> Incident -- ^ the incident
                 -> ResultT String IO (Set.Set Int) -- ^ nodes still available
handleEvacuation client memst (gl, nl, il) ndx migrate freenodes incident = do
  let node = Container.find ndx nl
      name = Node.name node
      fNdNames = map (Node.name . flip Container.find nl) $ Set.elems freenodes
      evacOpts = defaultOptions { algEvacMode = True
                                , algIgnoreSoftErrors = True
                                , algRestrictToNodes = Just fNdNames
                                }
      evacFun = tryNodeEvac evacOpts gl nl il
      migrateFun = if migrate then id else forceFailover
      annotateFun = annotateOpCode $ "Evacuating " ++ name
      pendingIncident = incident { incidentRepairStatus = RSPending }
      updateJobs jids_r = case jids_r of
        Ok jids -> do
          let incident' = over incidentJobsL (++ jids) pendingIncident
          liftIO $ updateIncident memst incident'
          liftIO $ appendJobs memst jids
          logDebug $ "Jobs submitted: " ++ show (map fromJobId jids)
        Bad e -> mkResultT . logAndBad
                   $ "Failure evacuating " ++ name ++ ": " ++ e
      logInstName i = logInfo $ "Evacuating instance "
                                  ++ Instance.name (Container.find i il)
                                  ++ " from " ++ name
      execSol sol = do
        now <- liftIO currentTimestamp
        let jobs = map (map (annotateFun now . migrateFun)) $ esOpCodes sol
        jids <- liftIO $ submitJobs jobs client
        updateJobs jids
        let touched = esMoved sol >>= \(_, _, nidxs) -> nidxs
        return $ freenodes Set.\\ Set.fromList touched
  logDebug $ "Handling evacuation of " ++ name
  case () of _ | not $ Node.offline node -> do
                   logDebug $ "Draining node " ++ name
                   job <- drainJob name
                   jids <- liftIO $ submitJobs [job] client
                   updateJobs jids
                   return freenodes
               | i:_ <- Node.pList node -> do
                   logInstName i
                   (_, _, sol) <- mkResultT . return $ evacFun ChangePrimary [i]
                   execSol sol
               | i:_ <- Node.sList node -> do
                   logInstName i
                   (_, _, sol) <- mkResultT . return
                                    $ evacFun ChangeSecondary [i]
                   execSol sol
               | otherwise -> do
                   logDebug $ "Finished evacuation of " ++ name
                   now <- liftIO currentTimestamp
                   jids <- mkResultT $ execJobsWaitOkJid
                            [[ annotateFun now
                               . OpTagsSet TagKindNode [ incidentTag incident ]
                               $ Just name]] client
                   let incident' = over incidentJobsL (++ jids)
                                     $ incident { incidentRepairStatus =
                                                    RSCompleted }
                   liftIO $ updateIncident memst incident'
                   liftIO $ appendJobs memst jids
                   return freenodes

-- | Submit the next action for a live-repair incident.
handleLiveRepairs :: L.Client -- ^ Luxi client to use
                 -> IORef MemoryState -- ^ memory state of the daemon
                 -> Idx -- ^ the node to handle the event on
                 -> Set.Set Int -- ^ unaffected nodes
                 -> Incident -- ^ the incident
                 -> ResultT String IO (Set.Set Int) -- ^ nodes still available
handleLiveRepairs client memst ndx freenodes incident = do
  let maybeCmd = getRepairCommand incident
      uuid = incidentUuid incident
      name = incidentNode incident
  now <- liftIO currentTimestamp
  logDebug $ "Handling requested command " ++ show maybeCmd ++ " on " ++ name
  case () of
    _ | null $ incidentJobs incident,
        Just cmd <- maybeCmd,
        cmd /= "" -> do
            logDebug "Submitting repair command job"
            name' <- mkNonEmpty name
            cmd' <- mkNonEmpty cmd
            orig' <- mkNonEmpty . J.encode $ incidentOriginal incident
            jids_r <- liftIO $ submitJobs
                        [[ annotateOpCode "repair command requested by node" now
                           OpRepairCommand { opNodeName = name'
                                           , opRepairCommand = cmd'
                                           , opInput = Just orig'
                                           } ]] client
            case jids_r of
              Ok jids -> do
                let incident' = over incidentJobsL (++ jids) incident
                liftIO $ updateIncident memst incident'
                liftIO $ appendJobs memst jids
                logDebug $ "Jobs submitted: " ++ show (map fromJobId jids)
              Bad e -> mkResultT . logAndBad
                   $ "Failure requesting command " ++ cmd ++ " on " ++ name
                     ++ ": " ++ e
      | null $ incidentJobs incident -> do
            logInfo $ "Marking incident " ++ UTF8.toString uuid ++ " as failed;"
                      ++ " command for live repair not specified"
            let newtag = C.maintdFailureTagPrefix ++ UTF8.toString uuid
            jids <- mkResultT $ execJobsWaitOkJid
                      [[ annotateOpCode "marking incident as ill specified" now
                         . OpTagsSet TagKindNode [ newtag ]
                         $ Just name ]] client
            let incident' = over incidentJobsL (++ jids)
                              $ incident { incidentRepairStatus = RSFailed
                                         , incidentTag = newtag
                                         }
            liftIO $ updateIncident memst incident'
            liftIO $ appendJobs memst jids
      | otherwise -> do
            logDebug "Command execution has succeeded"
            jids <- mkResultT $ execJobsWaitOkJid
                      [[ annotateOpCode "repair command requested by node" now
                         . OpTagsSet TagKindNode [ incidentTag incident ]
                         $ Just name ]] client
            let incident' = over incidentJobsL (++ jids)
                            $ incident { incidentRepairStatus = RSCompleted }
            liftIO $ updateIncident memst incident'
            liftIO $ appendJobs memst jids
  return $ Set.delete ndx freenodes


-- | Submit the next actions for a single incident, given the unaffected nodes;
-- register all submitted jobs and return the new set of unaffected nodes.
handleIncident :: L.Client
               -> IORef MemoryState
               -> (Group.List, Node.List, Instance.List)
               -> Set.Set Int
               -> (String, Incident)
               -> ResultT String IO (Set.Set Int)
handleIncident client memstate (gl, nl, il) freeNodes (name, incident) = do
  ndx <- case Container.keys $ Container.filter ((==) name . Node.name) nl of
           [ndx] -> return ndx
           [] -> do
             logWarning $ "Node " ++ name ++ " no longer in the cluster;"
                          ++ " clearing incident " ++ show incident
             liftIO . rmIncident memstate $ uuidOf incident
             fail $ "node " ++ name ++ " left the cluster"
           ndxs -> do
             logWarning $ "Abmigious node name " ++ name
                          ++ "; could refer to indices " ++ show ndxs
             fail $ "ambigious name " ++ name
  case incidentAction incident of
    RANoop -> do
      logDebug $ "Nothing to do for " ++ show incident
      liftIO . rmIncident memstate $ uuidOf incident
      return freeNodes
    RALiveRepair ->
      handleLiveRepairs client memstate ndx freeNodes incident
    RAEvacuate ->
      handleEvacuation client memstate (gl, nl, il) ndx True freeNodes incident
    RAEvacuateFailover ->
      handleEvacuation client memstate (gl, nl, il) ndx False freeNodes incident

-- | Submit the jobs necessary for the next maintenance step
-- for each pending maintenance, i.e., the most radical maintenance
-- for each node. Return the set of node indices unaffected by these
-- operations. Also, for each job submitted, register it directly.
handleIncidents :: IORef MemoryState
                -> (Group.List, Node.List, Instance.List)
                -> ResultT String IO (Set.Set Int)
handleIncidents memstate (gl, nl, il) = do
  incidents <- getIncidents memstate
  let activeIncidents = filter ((<= RSPending) . incidentRepairStatus) incidents
      incidentsToHandle = rankIncidents activeIncidents
      incidentNodes = Set.fromList . Container.keys
        $ Container.filter ((`Map.member` incidentsToHandle) . Node.name) nl
      freeNodes = Set.fromList (Container.keys nl) Set.\\ incidentNodes
  if null activeIncidents
    then return freeNodes
    else do
      luxiSocket <- liftIO Path.defaultQuerySocket
      bracket (liftIO $ L.getLuxiClient luxiSocket)
              (liftIO . L.closeClient)
              $ \ client ->
                foldM (handleIncident client memstate (gl, nl, il)) freeNodes
                  $ Map.assocs incidentsToHandle

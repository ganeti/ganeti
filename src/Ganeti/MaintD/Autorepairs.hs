{-| Auto-repair task of the maintenance daemon.

This module implements the non-pure parts of harep-style
repairs carried out by the maintenance daemon.

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

module Ganeti.MaintD.Autorepairs
  ( harepTasks
  ) where

import Control.Arrow (second, (***))
import Control.Monad (forM)
import Control.Exception (bracket)
import Data.Maybe (isJust, fromJust)
import qualified Data.Set as Set
import System.IO.Error (tryIOError)
import System.Time (getClockTime)

import Ganeti.BasicTypes
import Ganeti.Errors (formatError)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Repair
import Ganeti.HTools.Types
import Ganeti.JQueue (currentTimestamp)
import Ganeti.Jobs (execJobsWaitOkJid, submitJobs)
import Ganeti.Logging.Lifted
import qualified Ganeti.Luxi as L
import Ganeti.MaintD.Utils (annotateOpCode)
import Ganeti.OpCodes (OpCode(..))
import qualified Ganeti.Path as Path
import Ganeti.Types (JobId, JobStatus(..), TagKind(..), mkNonNegative)
import Ganeti.Utils (newUUID)

-- | Log a message and return a Bad result.
logAndBad :: String -> IO (Result a)
logAndBad msg = do
  logNotice msg
  return $ Bad msg

-- | Apply and remove tags form an instance indicated by `InstanceData`.
commitChange :: L.Client
             -> InstanceData
             -> ResultT String IO (InstanceData, [JobId])
commitChange client instData = do
  now <- liftIO currentTimestamp
  let arData = getArData $ arState instData
      iname = Instance.name $ arInstance instData
      rmTags = tagsToRemove instData
  addJobs <- if isJust arData
               then do
                 let tag = arTag $ fromJust arData
                 logDebug $ "Adding tag " ++ tag ++ " to " ++ iname
                 mkResultT $ execJobsWaitOkJid
                               [[ annotateOpCode "harep state tagging" now
                                   . OpTagsSet TagKindInstance [tag]
                                   $ Just iname ]]
                               client
               else return []
  rmJobs <- if null rmTags
              then return []
              else do
                logDebug $ "Removing tags " ++ show rmTags ++ " from " ++ iname
                mkResultT $ execJobsWaitOkJid
                              [[ annotateOpCode "harep state tag removal" now
                                . OpTagsDel TagKindInstance rmTags
                                $ Just iname ]]
                              client
  return (instData { tagsToRemove = [] }, addJobs ++ rmJobs)

-- | Query jobs of a pending repair, returning the new instance data.
processPending :: L.Client
               -> InstanceData
               -> IO (Result (InstanceData, [JobId]))
processPending client instData = runResultT $ case arState instData of
  (ArPendingRepair arData) -> do
    sts <- liftIO . L.queryJobsStatus client $ arJobs arData
    time <- liftIO getClockTime
    case sts of
      Bad e -> mkResultT . logAndBad
                 $ "Could not check job status: " ++ formatError e
      Ok sts' ->
        if any (<= JOB_STATUS_RUNNING) sts' then
          return (instData, [])
        else do
          let iname = Instance.name $ arInstance instData
              srcSt = arStateName $ arState instData
              arState' =
                if all (== JOB_STATUS_SUCCESS) sts' then
                  ArHealthy . Just
                    . updateTag $ arData { arResult = Just ArSuccess
                                         , arTime = time }
                else
                  ArFailedRepair . updateTag
                    $ arData { arResult = Just ArFailure, arTime = time }
              destSt = arStateName arState'
              instData' = instData { arState = arState'
                                   , tagsToRemove = delCurTag instData
                                   }
          logInfo $ "Moving " ++ iname ++ " form " ++ show srcSt ++ " to "
                    ++ show destSt
          commitChange client instData'
  _ -> return (instData, [])

-- | Perfom the suggested repair on an instance if its policy allows it
-- and return the list of submitted jobs.
doRepair :: L.Client
         -> InstanceData
         -> (AutoRepairType, [OpCode])
         -> IO (Result ([Idx], [JobId]))
doRepair client instData (rtype, opcodes) = runResultT $ do
  let inst = arInstance instData
      ipol = Instance.arPolicy inst
      iname = Instance.name inst
  case ipol of
    ArEnabled maxtype -> do
      uuid <- liftIO newUUID
      time <- liftIO getClockTime
      if rtype > maxtype then do
        let arState' = ArNeedsRepair (
              updateTag $ AutoRepairData rtype uuid time [] (Just ArEnoperm) "")
            instData' = instData { arState = arState'
                                 , tagsToRemove = delCurTag instData
                                 }
        logInfo $ "Not performing repair of type " ++ show rtype ++ " on "
                  ++ iname ++ " because only repairs up to " ++ show maxtype
                  ++ " are allowed"
        (_, jobs) <- commitChange client instData'
        return ([], jobs)
      else do
        now <- liftIO currentTimestamp
        logInfo $ "Executing " ++ show rtype ++ " repair on " ++ iname
        -- As in harep, we delay the actual repair, to allow the tagging
        -- to happen first; again this is only about speeding up the harep
        -- round, not about correctness.
        let opcodes' = OpTestDelay { opDelayDuration = 10
                                   , opDelayOnMaster = True
                                   , opDelayOnNodes = []
                                   , opDelayOnNodeUuids = Nothing
                                   , opDelayRepeat = fromJust $ mkNonNegative 0
                                   , opDelayInterruptible = False
                                   , opDelayNoLocks = False
                                   } : opcodes
        jids <- liftIO $ submitJobs
                           [ map (annotateOpCode "harep-style repair" now)
                             opcodes'] client
        case jids of
          Bad e -> mkResultT . logAndBad $ "Failure submitting repair jobs: "
                                           ++ e
          Ok jids' -> do
            let arState' = ArPendingRepair (
                  updateTag $ AutoRepairData rtype uuid time jids' Nothing "")
                instData' = instData { arState = arState'
                                     , tagsToRemove = delCurTag instData
                                     }
            (_, tagjobs) <- commitChange client instData'
            let nodes = filter (>= 0) [Instance.pNode inst, Instance.sNode inst]
            return (nodes, jids' ++ tagjobs)
    otherSt -> do
      logDebug $ "Not repairing " ++ iname ++ " becuase it is in state "
                 ++ show otherSt
      return ([], [])

-- | Harep-like repair tasks.
harepTasks :: (Node.List, Instance.List) -- ^ Current cluster configuration
           -> Set.Set Int -- ^ Node indices on which actions may be taken
           -> ResultT String IO (Set.Set Int, [JobId])
              -- ^ untouched nodes and jobs submitted
harepTasks (nl, il) nidxs = do
  logDebug $ "harep tasks on nodes " ++ show (Set.toList nidxs)
  iniData <- mkResultT . return . mapM setInitialState $ Container.elems il

  -- First step: check all pending repairs, see if they are completed.
  luxiSocket <- liftIO Path.defaultQuerySocket
  either_iData <- liftIO . tryIOError
                  . bracket (L.getLuxiClient luxiSocket) L.closeClient
                  $  forM iniData . processPending
  (iData', jobs) <- mkResultT $ case either_iData of
                      Left e -> logAndBad $ "Error while harep status update: "
                                              ++ show e
                      Right r ->
                        if any isBad r
                          then logAndBad $ "Bad harep processing pending: "
                                            ++ show (justBad r)
                          else return . Ok . second concat . unzip $ justOk r

  -- Second step: detect any problems.
  let repairs = map (detectBroken nl . arInstance) iData'

  -- Third step: create repair jobs for broken instances that are in ArHealthy.
  let repairIfHealthy c i = case arState i of
                              ArHealthy _ -> doRepair c i
                              _           -> const . return $ Ok ([], [])
      maybeRepair c (i, r) = maybe (return $ Ok ([], []))
                               (repairIfHealthy c i) r
  either_repairJobs <- liftIO . tryIOError
                       . bracket (L.getLuxiClient luxiSocket) L.closeClient
                       $ forM (zip iData' repairs) . maybeRepair

  (ntouched, jobs') <- mkResultT $ case either_repairJobs of
                         Left e -> logAndBad $ "Error while attempting repair: "
                                                 ++ show e
                         Right r ->
                           if any isBad r
                             then logAndBad $ "Error submitting repair jobs: "
                                                ++ show (justBad r)
                             else return . Ok . (concat *** concat) . unzip
                                    $ justOk r

  return (nidxs Set.\\ Set.fromList ntouched, jobs ++ jobs' )

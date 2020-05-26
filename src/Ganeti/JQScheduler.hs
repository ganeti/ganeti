{-# LANGUAGE RankNTypes #-}
{-| Implementation of a reader for the job queue.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.JQScheduler
  ( JQStatus
  , jqLivelock
  , emptyJQStatus
  , selectJobsToRun
  , scheduleSomeJobs
  , initJQScheduler
  , enqueueNewJobs
  , dequeueJob
  , setJobPriority
  , cleanupIfDead
  , updateStatusAndScheduleSomeJobs
  , configChangeNeedsRescheduling
  ) where

import Control.Applicative (liftA2)
import Control.Arrow
import Control.Concurrent
import Control.Exception
import Control.Monad
import Control.Monad.IO.Class
import Data.Function (on)
import Data.IORef (IORef, atomicModifyIORef,
                   atomicModifyIORef', newIORef, readIORef)
import Data.List
import Data.Maybe
import qualified Data.Map as Map
import Data.Ord (comparing)
import Data.Set (Set)
import qualified Data.Set as S
import System.INotify

import Ganeti.BasicTypes
import Ganeti.Compat
import Ganeti.Constants as C
import Ganeti.Errors
import Ganeti.JQScheduler.Filtering (applyingFilter, jobFiltering)
import Ganeti.JQScheduler.Types
import Ganeti.JQScheduler.ReasonRateLimiting (reasonRateLimit)
import Ganeti.JQueue as JQ
import Ganeti.JSON (fromContainer)
import Ganeti.Lens hiding (chosen)
import Ganeti.Logging
import Ganeti.Objects
import Ganeti.Path
import Ganeti.Types
import Ganeti.Utils
import Ganeti.Utils.Livelock
import Ganeti.Utils.MVarLock


{-| Representation of the job queue

We keep two lists of jobs (together with information about the last
fstat result observed): the jobs that are enqueued, but not yet handed
over for execution, and the jobs already handed over for execution. They
are kept together in a single IORef, so that we can atomically update
both, in particular when scheduling jobs to be handed over for execution.

-}

data JQStatus = JQStatus
  { jqJobs :: IORef Queue
  , jqConfig :: IORef (Result ConfigData)
  , jqLivelock :: Livelock
  , jqForkLock :: Lock
  }


emptyJQStatus :: IORef (Result ConfigData) -> IO JQStatus
emptyJQStatus config = do
  jqJ <- newIORef Queue { qEnqueued = [], qRunning = [], qManipulated = [] }
  (_, livelock) <- mkLivelockFile C.luxiLivelockPrefix
  forkLock <- newLock
  return JQStatus { jqJobs = jqJ, jqConfig = config, jqLivelock = livelock
                  , jqForkLock = forkLock }

-- When updating the job lists, force the elements to WHNF, otherwise it is
-- easy to leak the resources held onto by the lazily parsed job file.
-- This can happen, eg, if updateJob is called, but the resulting QueuedJob
-- isn't used by the scheduler, for example when the inotify watcher or the
-- the polling loop re-reads a job with a new message appended to it.

-- | Apply a function on the running jobs.
onRunningJobs :: ([JobWithStat] -> [JobWithStat]) -> Queue -> Queue
onRunningJobs f q@Queue { qRunning = qr } =
  let qr' = (foldr seq () qr) `seq` f qr -- force list els to WHNF
  in q { qRunning = qr' }

-- | Apply a function on the queued jobs.
onQueuedJobs :: ([JobWithStat] -> [JobWithStat]) -> Queue -> Queue
onQueuedJobs f q@Queue { qEnqueued = qe } =
  let qe' = (foldr seq () qe) `seq` f qe -- force list els to WHNF
  in q { qEnqueued = qe' }

-- | Obtain a JobWithStat from a QueuedJob.
unreadJob :: QueuedJob -> JobWithStat
unreadJob job = JobWithStat {jJob=job, jStat=nullFStat, jINotify=Nothing}

-- | Reload interval for polling the running jobs for updates in microseconds.
watchInterval :: Int
watchInterval = C.luxidJobqueuePollInterval * 1000000 

-- | Read a cluster parameter from the configuration, using a default if the
-- configuration is not available.
getConfigValue :: (Cluster -> a) -> a -> JQStatus -> IO a
getConfigValue param defaultvalue =
  liftM (genericResult (const defaultvalue) (param . configCluster))
  . readIORef . jqConfig

-- | Get the maximual number of jobs to be run simultaneously from the
-- configuration. If the configuration is not available, be conservative
-- and use the smallest possible value, i.e., 1.
getMaxRunningJobs :: JQStatus -> IO Int
getMaxRunningJobs = getConfigValue clusterMaxRunningJobs 1

-- | Get the maximual number of jobs to be tracked simultaneously from the
-- configuration. If the configuration is not available, be conservative
-- and use the smallest possible value, i.e., 1.
getMaxTrackedJobs :: JQStatus -> IO Int
getMaxTrackedJobs = getConfigValue clusterMaxTrackedJobs 1

-- | Get the number of jobs currently running.
getRQL :: JQStatus -> IO Int
getRQL = liftM (length . qRunning) . readIORef . jqJobs

-- | Wrapper function to atomically update the jobs in the queue status.
modifyJobs :: JQStatus -> (Queue -> Queue) -> IO ()
modifyJobs qstat f = atomicModifyIORef' (jqJobs qstat) (flip (,) ()  . f)

-- | Reread a job from disk, if the file has changed.
readJobStatus :: JobWithStat -> IO (Maybe JobWithStat)
readJobStatus jWS@(JobWithStat {jStat=fstat, jJob=job})  = do
  let jid = qjId job
  qdir <- queueDir
  let fpath = liveJobFile qdir jid
  logDebug $ "Checking if " ++ fpath ++ " changed on disk."
  changedResult <- try $ needsReload fstat fpath
                   :: IO (Either IOError (Maybe FStat))
  let changed = either (const $ Just nullFStat) id changedResult
  case changed of
    Nothing -> do
      logDebug $ "File " ++ fpath ++ " not changed on disk."
      return Nothing
    Just fstat' -> do
      let jids = show $ fromJobId jid
      logDebug $ "Rereading job "  ++ jids
      readResult <- loadJobFromDisk qdir True jid
      case readResult of
        Bad s -> do
          logWarning $ "Failed to read job " ++ jids ++ ": " ++ s
          return Nothing
        Ok (job', _) -> do
          logDebug $ "Read job " ++ jids ++ ", status is "
                     ++ show (calcJobStatus job')
          return . Just $ jWS {jStat=fstat', jJob=job'}
                          -- jINotify unchanged

-- | Update a job in the job queue, if it is still there. This is the
-- pure function for inserting a previously read change into the queue.
-- as the change contains its time stamp, we don't have to worry about a
-- later read change overwriting a newer read state. If this happens, the
-- fstat value will be outdated, so the next poller run will fix this.
updateJobStatus :: JobWithStat -> [JobWithStat] -> [JobWithStat]
updateJobStatus job' =
  let jid = qjId $ jJob job' in
  map (\job -> if qjId (jJob job) == jid then job' else job)

-- | Update a single job by reading it from disk, if necessary.
updateJob :: JQStatus -> JobWithStat -> IO ()
updateJob state jb = do
  jb' <- readJobStatus jb
  maybe (return ()) (modifyJobs state . onRunningJobs . updateJobStatus) jb'
  when (maybe True (jobFinalized . jJob) jb') . (>> return ()) . forkIO $ do
    logDebug "Scheduler noticed a job to have finished."
    cleanupFinishedJobs state
    scheduleSomeJobs state

-- | Move a job from one part of the queue to another.
-- Return the job that was moved, or 'Nothing' if it wasn't found in
-- the queue.
moveJob :: Lens' Queue [JobWithStat] -- ^ from queue
        -> Lens' Queue [JobWithStat] -- ^ to queue
        -> JobId
        -> Queue
        -> (Queue, Maybe JobWithStat)
moveJob fromQ toQ jid queue =
    -- traverse over the @(,) [JobWithStats]@ functor to extract the job
    case traverseOf fromQ (partition ((== jid) . qjId . jJob)) queue of
      (job : _, queue') -> (over toQ (++ [job]) queue', Just job)
      _                 -> (queue, Nothing)

-- | Atomically move a job from one part of the queue to another.
-- Return the job that was moved, or 'Nothing' if it wasn't found in
-- the queue.
moveJobAtomic :: Lens' Queue [JobWithStat] -- ^ from queue
              -> Lens' Queue [JobWithStat] -- ^ to queue
              -> JobId
              -> JQStatus
              -> IO (Maybe JobWithStat)
moveJobAtomic fromQ toQ jid qstat =
  atomicModifyIORef (jqJobs qstat) (moveJob fromQ toQ jid)

-- | Manipulate a running job by atomically moving it from 'qRunning'
-- into 'qManipulated', running a given IO action and then atomically
-- returning it back.
--
-- Returns the result of the IO action, or 'Nothing', if the job wasn't found
-- in the queue.
manipulateRunningJob :: JQStatus -> JobId -> IO a -> IO (Maybe a)
manipulateRunningJob qstat jid k = do
  jobOpt <- moveJobAtomic qRunningL qManipulatedL jid qstat
  case jobOpt of
    Nothing -> return Nothing
    Just _  -> (Just `liftM` k)
               `finally` moveJobAtomic qManipulatedL qRunningL jid qstat

-- | Sort out the finished jobs from the monitored part of the queue.
-- This is the pure part, splitting the queue into a remaining queue
-- and the jobs that were removed.
sortoutFinishedJobs :: Queue -> (Queue, [JobWithStat])
sortoutFinishedJobs queue =
  let (fin, run') = partition (jobFinalized . jJob) . qRunning $ queue
  in (queue {qRunning=run'}, fin)

-- | Actually clean up the finished jobs. This is the IO wrapper around
-- the pure `sortoutFinishedJobs`.
cleanupFinishedJobs :: JQStatus -> IO ()
cleanupFinishedJobs qstate = do
  finished <- atomicModifyIORef (jqJobs qstate) sortoutFinishedJobs
  let showJob = show . ((fromJobId . qjId) &&& calcJobStatus) . jJob
      jlist = commaJoin $ map showJob finished
  unless (null finished)
    . logInfo $ "Finished jobs: " ++ jlist
  mapM_ (maybe (return ()) killINotify . jINotify) finished

-- | Watcher task for a job, to update it on file changes. It also
-- reinstantiates itself upon receiving an Ignored event.
jobWatcher :: JQStatus -> JobWithStat -> Event -> IO ()
jobWatcher state jWS e = do
  let jid = qjId $ jJob jWS
      jids = show $ fromJobId jid
  logInfo $ "Scheduler notified of change of job " ++ jids
  logDebug $ "Scheduler notify event for " ++ jids ++ ": " ++ show e
  let inotify = jINotify jWS
  when (e == Ignored  && isJust inotify) $ do
    qdir <- queueDir
    let fpath = toInotifyPath $ liveJobFile qdir jid
    _ <- addWatch (fromJust inotify) [Modify, Delete] fpath
           (jobWatcher state jWS)
    return ()
  updateJob state jWS

-- | Attach the job watcher to a running job.
attachWatcher :: JQStatus -> JobWithStat -> IO ()
attachWatcher state jWS = when (isNothing $ jINotify jWS) $ do
  max_watch <- getMaxTrackedJobs state
  rql <- getRQL state
  if rql < max_watch
   then do
     inotify <- initINotify
     qdir <- queueDir
     let fpath = liveJobFile qdir . qjId $ jJob jWS
         jWS' = jWS { jINotify=Just inotify }
     logDebug $ "Attaching queue watcher for " ++ fpath
     _ <- addWatch inotify [Modify, Delete] (toInotifyPath fpath)
            $ jobWatcher state jWS'
     modifyJobs state . onRunningJobs $ updateJobStatus jWS'
   else logDebug $ "Not attaching watcher for job "
                   ++ (show . fromJobId . qjId $ jJob jWS)
                   ++ ", run queue length is " ++ show rql

-- | For a queued job, determine whether it is eligible to run, i.e.,
-- if no jobs it depends on are either enqueued or running.
jobEligible :: Queue -> JobWithStat -> Bool
jobEligible queue jWS =
  let jdeps = getJobDependencies $ jJob jWS
      blocks = flip elem jdeps . qjId . jJob
  in not . any blocks . liftA2 (++) qRunning qEnqueued $ queue

-- | Decide on which jobs to schedule next for execution. This is the
-- pure function doing the scheduling.
selectJobsToRun :: Int  -- ^ How many jobs are allowed to run at the
                        -- same time.
                -> Set FilterRule -- ^ Filter rules to respect for scheduling
                -> Queue
                -> (Queue, [JobWithStat])
selectJobsToRun count filters queue =
  let n = count - length (qRunning queue) - length (qManipulated queue)
      chosen = take n
               . jobFiltering queue filters
               . reasonRateLimit queue
               . sortBy (comparing (calcJobPriority . jJob))
               . filter (jobEligible queue)
               $ qEnqueued queue
      remain = deleteFirstsBy ((==) `on` (qjId . jJob)) (qEnqueued queue) chosen
  in (queue {qEnqueued=remain, qRunning=qRunning queue ++ chosen}, chosen)

-- | Logs errors of failed jobs and returns the set of job IDs.
logFailedJobs :: (MonadLog m)
              => [(JobWithStat, GanetiException)] -> m (S.Set JobId)
logFailedJobs [] = return S.empty
logFailedJobs jobs = do
  let jids = S.fromList . map (qjId . jJob . fst) $ jobs
      jidsString = commaJoin . map (show . fromJobId) . S.toList $ jids
  logWarning $ "Starting jobs " ++ jidsString ++ " failed: "
               ++ show (map snd jobs)
  return jids

-- | Fail jobs that were previously selected for execution
-- but couldn't be started.
failJobs :: ConfigData -> JQStatus -> [(JobWithStat, GanetiException)]
         -> IO ()
failJobs cfg qstate jobs = do
  qdir <- queueDir
  now <- currentTimestamp
  jids <- logFailedJobs jobs
  let sjobs = intercalate "." . map (show . fromJobId) $ S.toList jids
  let rmJobs = filter ((`S.notMember` jids) . qjId . jJob)
  logWarning $ "Failing jobs " ++ sjobs
  modifyJobs qstate $ onRunningJobs rmJobs
  let trySaveJob :: JobWithStat -> ResultT String IO ()
      trySaveJob = (() <$) . writeAndReplicateJob cfg qdir . jJob
      reason jid msg =
        ( "gnt:daemon:luxid:startjobs"
        , "job " ++ show (fromJobId jid) ++ " failed to start: " ++ msg
        , reasonTrailTimestamp now )
      failJob err job = failQueuedJob (reason (qjId job) (show err)) now job
      failAndSaveJobWithStat (jws, err) =
        trySaveJob . over jJobL (failJob err) $ jws
  mapM_ (runResultT . failAndSaveJobWithStat) jobs
  logDebug $ "Failed jobs " ++ sjobs


-- | Checks if any jobs match a REJECT filter rule, and cancels them.
cancelRejectedJobs :: JQStatus -> ConfigData -> Set FilterRule -> IO ()
cancelRejectedJobs qstate cfg filters = do

  enqueuedJobs <- map jJob . qEnqueued <$> readIORef (jqJobs qstate)

  -- Determine which jobs are rejected.
  let jobsToCancel =
        [ (job, fr) | job <- enqueuedJobs
                    , Just fr <- [applyingFilter filters job]
                    , frAction fr == Reject ]

  -- Cancel them.
  qDir <- queueDir
  forM_ jobsToCancel $ \(job, fr) -> do
    let jid = qjId job
    logDebug $ "Cancelling job " ++ show (fromJobId jid)
               ++ " because it was REJECTed by filter rule " ++ uuidOf fr
    -- First dequeue, then cancel.
    dequeueResult <- dequeueJob qstate jid
    case dequeueResult of
      Ok True -> do
        now <- currentTimestamp
        r <- runResultT
               $ writeAndReplicateJob cfg qDir (cancelQueuedJob now job)
        case r of
          Ok _ -> return ()
          Bad err -> logError $
            "Failed to write config when cancelling job: " ++ err
      Ok False -> do
        logDebug $ "Job " ++ show (fromJobId jid)
                   ++ " not queued; trying to cancel directly"
        _ <- cancelJob False (jqLivelock qstate) jid  -- sigTERM-kill only
        return ()
      Bad s -> logError s -- passing a nonexistent job ID is an error here


-- | Schedule jobs to be run. This is the IO wrapper around the
-- pure `selectJobsToRun`.
scheduleSomeJobs :: JQStatus -> IO ()
scheduleSomeJobs qstate = do
  cfgR <- readIORef (jqConfig qstate)
  case cfgR of
    Bad err -> do
      let msg = "Configuration unavailable: " ++ err
      logError msg
    Ok cfg -> do
      let filters = S.fromList . Map.elems . fromContainer $ configFilters cfg

      -- Check if jobs are rejected by a REJECT filter, and cancel them.
      cancelRejectedJobs qstate cfg filters

      -- Select the jobs to run.
      count <- getMaxRunningJobs qstate
      chosen <- atomicModifyIORef (jqJobs qstate)
                                  (selectJobsToRun count filters)
      let jobs = map jJob chosen
      unless (null chosen) . logInfo . (++) "Starting jobs: " . commaJoin
        $ map (show . fromJobId . qjId) jobs

      -- Attach the watcher.
      mapM_ (attachWatcher qstate) chosen

      -- Start the jobs.
      result <- JQ.startJobs (jqLivelock qstate) (jqForkLock qstate) jobs
      let badWith (x, Bad y) = Just (x, y)
          badWith _          = Nothing
      let failed = mapMaybe badWith $ zip chosen result
      unless (null failed) $ failJobs cfg qstate failed

-- | Format the job queue status in a compact, human readable way.
showQueue :: Queue -> String
showQueue (Queue {qEnqueued=waiting, qRunning=running}) =
  let showids = show . map (fromJobId . qjId . jJob)
  in "Waiting jobs: " ++ showids waiting 
       ++ "; running jobs: " ++ showids running

-- | Check if a job died, and clean up if so. Return True, if
-- the job was found dead.
checkForDeath :: JQStatus -> JobWithStat -> IO Bool
checkForDeath state jobWS = do
  let job = jJob jobWS
      jid = qjId job
      sjid = show $ fromJobId jid
      livelock = qjLivelock job
  logDebug $ "Livelock of job " ++ sjid ++ " is " ++ show livelock
  died <- maybe (return False) isDead
          . mfilter (/= jqLivelock state)
          $ livelock
  logDebug $ "Death of " ++ sjid ++ ": " ++ show died
  when died $ do
    logInfo $ "Detected death of job " ++ sjid
    -- if we manage to remove the job from the queue, we own the job file
    -- and can manipulate it.
    void . manipulateRunningJob state jid . runResultT $ do
      jobWS' <- mkResultT $ readJobFromDisk jid :: ResultG JobWithStat
      unless (jobFinalized . jJob $ jobWS') . void $ do
        -- If the job isn't finalized, but dead, add a corresponding
        -- failed status.
        now <- liftIO currentTimestamp
        qDir <- liftIO queueDir
        let reason = ( "gnt:daemon:luxid:deathdetection"
                     , "detected death of job " ++ sjid
                     , reasonTrailTimestamp now )
            failedJob = failQueuedJob reason now $ jJob jobWS'
        cfg <- mkResultT . readIORef $ jqConfig state
        writeAndReplicateJob cfg qDir failedJob
  return died

-- | Trigger job detection for the job with the given job id.
-- Return True, if the job is dead.
cleanupIfDead :: JQStatus -> JobId -> IO Bool
cleanupIfDead state jid = do
  logDebug $ "Extra job-death detection for " ++ show (fromJobId jid)
  jobs <- readIORef (jqJobs state)
  let jobWS = find ((==) jid . qjId . jJob) $ qRunning jobs
  maybe (return True) (checkForDeath state) jobWS

-- | Force the queue to check the state of all jobs.
updateStatusAndScheduleSomeJobs :: JQStatus -> IO ()
updateStatusAndScheduleSomeJobs qstate =  do
  jobs <- readIORef (jqJobs qstate)
  mapM_ (checkForDeath qstate) $ qRunning jobs
  jobs' <- readIORef (jqJobs qstate)
  mapM_ (updateJob qstate) $ qRunning jobs'
  cleanupFinishedJobs qstate
  jobs'' <- readIORef (jqJobs qstate)
  logInfo $ showQueue jobs''
  scheduleSomeJobs qstate

-- | Time-based watcher for updating the job queue.
onTimeWatcher :: JQStatus -> IO ()
onTimeWatcher qstate = forever $ do
  threadDelay watchInterval
  logDebug "Job queue watcher timer fired"
  updateStatusAndScheduleSomeJobs qstate
  logDebug "Job queue watcher cycle finished"

-- | Read a single, non-archived, job, specified by its id, from disk.
readJobFromDisk :: JobId -> IO (Result JobWithStat)
readJobFromDisk jid = do
  qdir <- queueDir
  let fpath = liveJobFile qdir jid
  logDebug $ "Reading " ++ fpath
  tryFstat <- try $ getFStat fpath :: IO (Either IOError FStat)
  let fstat = either (const nullFStat) id tryFstat
  loadResult <- JQ.loadJobFromDisk qdir False jid
  return $ liftM (JobWithStat Nothing fstat . fst) loadResult

-- | Read all non-finalized jobs from disk.
readJobsFromDisk :: IO [JobWithStat]
readJobsFromDisk = do
  logInfo "Loading job queue"
  qdir <- queueDir
  eitherJids <- JQ.getJobIDs [qdir]
  let jids = genericResult (const []) JQ.sortJobIDs eitherJids
      jidsstring = commaJoin $ map (show . fromJobId) jids
  logInfo $ "Non-archived jobs on disk: " ++ jidsstring
  jobs <- mapM readJobFromDisk jids
  return $ justOk jobs

-- | Set up the job scheduler. This will also start the monitoring
-- of changes to the running jobs.
initJQScheduler :: JQStatus -> IO ()
initJQScheduler qstate = do
  alljobs <- readJobsFromDisk
  let jobs = filter (not . jobFinalized . jJob) alljobs
      (running, queued) = partition (jobStarted . jJob) jobs
  modifyJobs qstate (onQueuedJobs (++ queued) . onRunningJobs (++ running))
  jqjobs <- readIORef (jqJobs qstate)
  logInfo $ showQueue jqjobs
  scheduleSomeJobs qstate
  logInfo "Starting time-based job queue watcher"
  _ <- forkIO $ onTimeWatcher qstate
  return ()

-- | Enqueue new jobs. This will guarantee that the jobs will be executed
-- eventually.
enqueueNewJobs :: JQStatus -> [QueuedJob] -> IO ()
enqueueNewJobs state jobs = do
  logInfo . (++) "New jobs enqueued: " . commaJoin
    $ map (show . fromJobId . qjId) jobs
  let jobs' = map unreadJob jobs
      insertFn = insertBy (compare `on` fromJobId . qjId . jJob)
      addJobs oldjobs = foldl (flip insertFn) oldjobs jobs'
  modifyJobs state (onQueuedJobs addJobs)
  scheduleSomeJobs state

-- | Pure function for removing a queued job from the job queue by
-- atomicModifyIORef. The answer is Just the job if the job could be removed
-- before being handed over to execution, Nothing if it already was started
-- and a Bad result if the job is not found in the queue.
rmJob :: JobId -> Queue -> (Queue, Result (Maybe QueuedJob))
rmJob jid q =
  let isJid = (jid ==) . qjId . jJob
      (found, queued') = partition isJid $ qEnqueued q
      isRunning = any isJid $ qRunning q
      sJid = (++) "Job " . show $ fromJobId jid
  in case (found, isRunning) of
    ([job], _) -> (q {qEnqueued = queued'}, Ok . Just $ jJob job)
    (_:_, _) -> (q, Bad $ "Queue in inconsistent state."
                           ++ sJid ++ " queued multiple times")
    (_, True) -> (q, Ok Nothing)
    _ -> (q, Bad $ sJid ++ " not found in queue")

-- | Try to remove a queued job from the job queue. Return True, if
-- the job could be removed from the queue before being handed over
-- to execution, False if the job already started, and a Bad result
-- if the job is unknown.
dequeueJob :: JQStatus -> JobId -> IO (Result Bool)
dequeueJob state jid = do
  result <- atomicModifyIORef (jqJobs state) $ rmJob jid
  let result' = fmap isJust result
  logDebug $ "Result of dequeing job " ++ show (fromJobId jid)
              ++ " is " ++ show result'
  return result'

-- | Change the priority of a queued job (once the job is handed over
-- to execution, the job itself needs to be informed). To avoid the
-- job being started unmodified, it is temporarily unqueued during the
-- change. Return the modified job, if the job's priority was sucessfully
-- modified, Nothing, if the job already started, and a Bad value, if the job
-- is unkown.
setJobPriority :: JQStatus -> JobId -> Int -> IO (Result (Maybe QueuedJob))
setJobPriority state jid prio = runResultT $ do
  maybeJob <- mkResultT . atomicModifyIORef (jqJobs state) $ rmJob jid
  case maybeJob of
    Nothing -> return Nothing
    Just job -> do
      let job' = changeJobPriority prio job
      qDir <- liftIO queueDir
      mkResultT $ writeJobToDisk qDir job'
      liftIO $ enqueueNewJobs state [job']
      return $ Just job'


-- | Given old and new configs, determines if the changes between them should
-- trigger the scheduler to run.
configChangeNeedsRescheduling :: ConfigData -> ConfigData -> Bool
configChangeNeedsRescheduling old new =
  -- Trigger rescheduling if any of the following change:
  (((/=) `on` configFilters) old new || -- filters
   ((/=) `on` clusterMaxRunningJobs . configCluster) old new -- run queue length
  )

{-| Implementation of a reader for the job queue.

-}

{-

Copyright (C) 2013 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.JQScheduler
  ( JQStatus
  , emptyJQStatus
  , initJQScheduler
  , enqueueNewJobs
  , dequeueJob
  ) where

import Control.Arrow
import Control.Concurrent
import Control.Exception
import Control.Monad
import Data.Function (on)
import Data.List
import Data.Maybe
import Data.IORef
import System.INotify

import Ganeti.BasicTypes
import Ganeti.Constants as C
import Ganeti.JQueue as JQ
import Ganeti.Logging
import Ganeti.Objects
import Ganeti.Path
import Ganeti.Types
import Ganeti.Utils

data JobWithStat = JobWithStat { jINotify :: Maybe INotify
                               , jStat :: FStat
                               , jJob :: QueuedJob
                               }
data Queue = Queue { qEnqueued :: [JobWithStat], qRunning :: [JobWithStat] }

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
  }


emptyJQStatus :: IORef (Result ConfigData) -> IO JQStatus
emptyJQStatus config = do
  jqJ <- newIORef Queue { qEnqueued = [], qRunning = []}
  return JQStatus { jqJobs = jqJ, jqConfig = config }

-- | Apply a function on the running jobs.
onRunningJobs :: ([JobWithStat] -> [JobWithStat]) -> Queue -> Queue
onRunningJobs f queue = queue {qRunning=f $ qRunning queue}

-- | Apply a function on the queued jobs.
onQueuedJobs :: ([JobWithStat] -> [JobWithStat]) -> Queue -> Queue
onQueuedJobs f queue = queue {qEnqueued=f $ qEnqueued queue}

-- | Obtain a JobWithStat from a QueuedJob.
unreadJob :: QueuedJob -> JobWithStat
unreadJob job = JobWithStat {jJob=job, jStat=nullFStat, jINotify=Nothing}

-- | Reload interval for polling the running jobs for updates in microseconds.
watchInterval :: Int
watchInterval = C.luxidJobqueuePollInterval * 1000000 

-- | Get the maximual number of jobs to be run simultaneously from the
-- configuration. If the configuration is not available, be conservative
-- and use the smallest possible value, i.e., 1.
getMaxRunningJobs :: JQStatus -> IO Int
getMaxRunningJobs =
  liftM (genericResult (const 1) (clusterMaxRunningJobs . configCluster))
  . readIORef . jqConfig

-- | Wrapper function to atomically update the jobs in the queue status.
modifyJobs :: JQStatus -> (Queue -> Queue) -> IO ()
modifyJobs qstat f = atomicModifyIORef (jqJobs qstat) (flip (,) ()  . f)

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
      logInfo $ "Rereading job "  ++ jids
      readResult <- loadJobFromDisk qdir True jid
      case readResult of
        Bad s -> do
          logWarning $ "Failed to read job " ++ jids ++ ": " ++ s
          return Nothing
        Ok (job', _) -> do
          logDebug
            $ "Read job " ++ jids ++ ", staus is " ++ show (calcJobStatus job')
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
  logDebug $ "Scheulder notify event for " ++ jids ++ ": " ++ show e
  let inotify = jINotify jWS
  when (e == Ignored  && isJust inotify) $ do
    qdir <- queueDir
    let fpath = liveJobFile qdir jid
    _ <- addWatch (fromJust inotify) [Modify, Delete] fpath
           (jobWatcher state jWS)
    return ()
  updateJob state jWS

-- | Attach the job watcher to a running job.
attachWatcher :: JQStatus -> JobWithStat -> IO ()
attachWatcher state jWS = when (isNothing $ jINotify jWS) $ do
  inotify <- initINotify
  qdir <- queueDir
  let fpath = liveJobFile qdir . qjId $ jJob jWS
      jWS' = jWS { jINotify=Just inotify }
  logDebug $ "Attaching queue watcher for " ++ fpath
  _ <- addWatch inotify [Modify, Delete] fpath $ jobWatcher state jWS'
  modifyJobs state . onRunningJobs $ updateJobStatus jWS'

-- | Decide on which jobs to schedule next for execution. This is the
-- pure function doing the scheduling.
selectJobsToRun :: Int -> Queue -> (Queue, [JobWithStat])
selectJobsToRun count queue =
  let n = count - length (qRunning queue)
      (chosen, remain) = splitAt n (qEnqueued queue)
  in (queue {qEnqueued=remain, qRunning=qRunning queue ++ chosen}, chosen)

-- | Requeue jobs that were previously selected for execution
-- but couldn't be started.
requeueJobs :: JQStatus -> [JobWithStat] -> IOError -> IO ()
requeueJobs qstate jobs err = do
  let jids = map (qjId . jJob) jobs
      jidsString = commaJoin $ map (show . fromJobId) jids
      rmJobs = filter ((`notElem` jids) . qjId . jJob)
  logWarning $ "Starting jobs failed: " ++ show err
  logWarning $ "Rescheduling jobs: " ++ jidsString
  modifyJobs qstate (onRunningJobs rmJobs)
  modifyJobs qstate (onQueuedJobs $ (++) jobs)

-- | Schedule jobs to be run. This is the IO wrapper around the
-- pure `selectJobsToRun`.
scheduleSomeJobs :: JQStatus -> IO ()
scheduleSomeJobs qstate = do
  count <- getMaxRunningJobs qstate
  chosen <- atomicModifyIORef (jqJobs qstate) (selectJobsToRun count)
  let jobs = map jJob chosen
  unless (null chosen) . logInfo . (++) "Starting jobs: " . commaJoin
    $ map (show . fromJobId . qjId) jobs
  mapM_ (attachWatcher qstate) chosen
  result <- try $ JQ.startJobs jobs
  either (requeueJobs qstate chosen) return result

-- | Format the job queue status in a compact, human readable way.
showQueue :: Queue -> String
showQueue (Queue {qEnqueued=waiting, qRunning=running}) =
  let showids = show . map (fromJobId . qjId . jJob)
  in "Waiting jobs: " ++ showids waiting 
       ++ "; running jobs: " ++ showids running

-- | Time-based watcher for updating the job queue.
onTimeWatcher :: JQStatus -> IO ()
onTimeWatcher qstate = forever $ do
  threadDelay watchInterval
  logDebug "Job queue watcher timer fired"
  jobs <- readIORef (jqJobs qstate)
  mapM_ (updateJob qstate) $ qRunning jobs
  cleanupFinishedJobs qstate
  jobs' <- readIORef (jqJobs qstate)
  logInfo $ showQueue jobs'
  scheduleSomeJobs qstate

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
  let jids = either (const []) JQ.sortJobIDs eitherJids
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

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
  ) where

import Control.Arrow
import Control.Concurrent
import Control.Exception
import Control.Monad
import Data.List
import Data.IORef

import Ganeti.BasicTypes
import Ganeti.Constants as C
import Ganeti.JQueue as JQ
import Ganeti.Logging
import Ganeti.Path
import Ganeti.Types
import Ganeti.Utils

data JobWithStat = JobWithStat { jStat :: FStat, jJob :: QueuedJob }
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
  }


emptyJQStatus :: IO JQStatus
emptyJQStatus = do
  jqJ <- newIORef Queue {qEnqueued=[], qRunning=[]}
  return JQStatus { jqJobs=jqJ }

-- | Apply a function on the running jobs.
onRunningJobs :: ([JobWithStat] -> [JobWithStat]) -> Queue -> Queue
onRunningJobs f queue = queue {qRunning=f $ qRunning queue}

-- | Apply a function on the queued jobs.
onQueuedJobs :: ([JobWithStat] -> [JobWithStat]) -> Queue -> Queue
onQueuedJobs f queue = queue {qEnqueued=f $ qEnqueued queue}

-- | Obtain a JobWithStat from a QueuedJob.
unreadJob :: QueuedJob -> JobWithStat
unreadJob job = JobWithStat {jJob=job, jStat=nullFStat}

-- | Reload interval for polling the running jobs for updates in microseconds.
watchInterval :: Int
watchInterval = C.luxidJobqueuePollInterval * 1000000 

-- | Maximal number of jobs to be running at the same time.
maxRunningJobs :: Int
maxRunningJobs = C.luxidMaximalRunningJobs 

-- | Wrapper function to atomically update the jobs in the queue status.
modifyJobs :: JQStatus -> (Queue -> Queue) -> IO ()
modifyJobs qstat f = atomicModifyIORef (jqJobs qstat) (flip (,) ()  . f)

-- | Reread a job from disk, if the file has changed.
readJobStatus :: JobWithStat -> IO (Maybe JobWithStat)
readJobStatus (JobWithStat {jStat=fstat, jJob=job})  = do
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
          return . Just $ JobWithStat {jStat=fstat', jJob=job'}

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

-- | Sort out the finished jobs from the monitored part of the queue.
-- This is the pure part, splitting the queue into a remaining queue
-- and the jobs that were removed.
sortoutFinishedJobs :: Queue -> (Queue, [QueuedJob])
sortoutFinishedJobs queue =
  let (run', fin) = partition
                      ((<= JOB_STATUS_RUNNING) . calcJobStatus . jJob)
                      . qRunning $ queue
  in (queue {qRunning=run'}, map jJob fin)

-- | Actually clean up the finished jobs. This is the IO wrapper around
-- the pure `sortoutFinishedJobs`.
cleanupFinishedJobs :: JQStatus -> IO ()
cleanupFinishedJobs qstate = do
  finished <- atomicModifyIORef (jqJobs qstate) sortoutFinishedJobs
  let showJob = show . ((fromJobId . qjId) &&& calcJobStatus)
      jlist = commaJoin $ map showJob finished
  unless (null finished)
    . logInfo $ "Finished jobs: " ++ jlist

-- | Decide on which jobs to schedule next for execution. This is the
-- pure function doing the scheduling.
selectJobsToRun :: Queue -> (Queue, [QueuedJob])
selectJobsToRun queue =
  let n = maxRunningJobs - length (qRunning queue)
      (chosen, remain) = splitAt n (qEnqueued queue)
  in (queue {qEnqueued=remain, qRunning=qRunning queue ++ chosen}
     , map jJob chosen)

-- | Requeue jobs that were previously selected for execution
-- but couldn't be started.
requeueJobs :: JQStatus -> [QueuedJob] -> IOError -> IO ()
requeueJobs qstate jobs err = do
  let jids = map qjId jobs
      jidsString = commaJoin $ map (show . fromJobId) jids
      rmJobs = filter ((`notElem` jids) . qjId . jJob)
  logWarning $ "Starting jobs failed: " ++ show err
  logWarning $ "Rescheduling jobs: " ++ jidsString
  modifyJobs qstate (onRunningJobs rmJobs)
  modifyJobs qstate (onQueuedJobs . (++) $ map unreadJob jobs)

-- | Schedule jobs to be run. This is the IO wrapper around the
-- pure `selectJobsToRun`.
scheduleSomeJobs :: JQStatus -> IO ()
scheduleSomeJobs qstate = do
  chosen <- atomicModifyIORef (jqJobs qstate) selectJobsToRun
  unless (null chosen) . logInfo . (++) "Starting jobs: " . commaJoin
    $ map (show . fromJobId . qjId) chosen
  result <- try $ JQ.startJobs chosen
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

-- | Set up the job scheduler. This will also start the monitoring
-- of changes to the running jobs.
initJQScheduler :: JQStatus -> IO ()
initJQScheduler qstate = do
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
  modifyJobs state (onQueuedJobs (++ jobs'))
  scheduleSomeJobs state

{-| Implementation of the job queue.

-}

{-

Copyright (C) 2010, 2012 Google Inc.
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

module Ganeti.JQueue
    ( queuedOpCodeFromMetaOpCode
    , queuedJobFromOpCodes
    , changeOpCodePriority
    , changeJobPriority
    , cancelQueuedJob
    , failQueuedJob
    , fromClockTime
    , noTimestamp
    , currentTimestamp
    , advanceTimestamp
    , reasonTrailTimestamp
    , setReceivedTimestamp
    , extendJobReasonTrail
    , getJobDependencies
    , opStatusFinalized
    , extractOpSummary
    , calcJobStatus
    , jobStarted
    , jobFinalized
    , jobArchivable
    , calcJobPriority
    , jobFileName
    , liveJobFile
    , archivedJobFile
    , determineJobDirectories
    , getJobIDs
    , sortJobIDs
    , loadJobFromDisk
    , noSuchJob
    , readSerialFromDisk
    , allocateJobIds
    , allocateJobId
    , writeJobToDisk
    , replicateManyJobs
    , writeAndReplicateJob
    , isQueueOpen
    , startJobs
    , cancelJob
    , tellJobPriority
    , notifyJob
    , waitUntilJobExited
    , queueDirPermissions
    , archiveJobs
    -- re-export
    , Timestamp
    , InputOpCode(..)
    , QueuedOpCode(..)
    , QueuedJob(..)
    ) where

import Control.Applicative (liftA2, (<|>))
import Control.Arrow (first, second)
import Control.Concurrent (forkIO, threadDelay)
import Control.Exception
import Control.Lens (over)
import Control.Monad
import Control.Monad.Fix
import Control.Monad.IO.Class
import Control.Monad.Trans (lift)
import Control.Monad.Trans.Maybe
import Data.List
import Data.Maybe
import Data.Ord (comparing)
-- workaround what seems to be a bug in ghc 7.4's TH shadowing code
import Prelude hiding (id, log)
import System.Directory
import System.FilePath
import System.IO.Error (isDoesNotExistError)
import System.Posix.Files
import System.Posix.Signals (sigHUP, sigTERM, sigUSR1, sigKILL, signalProcess)
import System.Posix.Types (ProcessID)
import System.Time
import qualified Text.JSON
import Text.JSON.Types

import Ganeti.BasicTypes
import qualified Ganeti.Config as Config
import qualified Ganeti.Constants as C
import Ganeti.Errors (ErrorResult, ResultG)
import Ganeti.JQueue.Lens (qoInputL, validOpCodeL)
import Ganeti.JQueue.Objects
import Ganeti.JSON (fromJResult, fromObjWithDefault)
import Ganeti.Logging
import Ganeti.Luxi
import Ganeti.Objects (ConfigData, Node)
import Ganeti.OpCodes
import Ganeti.OpCodes.Lens (metaParamsL, opReasonL)
import Ganeti.Path
import Ganeti.Query.Exec as Exec
import Ganeti.Rpc (executeRpcCall, ERpcError, logRpcErrors,
                   RpcCallJobqueueUpdate(..), RpcCallJobqueueRename(..))
import Ganeti.Runtime (GanetiDaemon(..), GanetiGroup(..), MiscGroup(..))
import Ganeti.Types
import Ganeti.Utils
import Ganeti.Utils.Atomic
import Ganeti.Utils.Livelock (Livelock, isDead)
import Ganeti.Utils.MVarLock
import Ganeti.VCluster (makeVirtualPath)

-- * Data types

-- | Missing timestamp type.
noTimestamp :: Timestamp
noTimestamp = (-1, -1)

-- | Obtain a Timestamp from a given clock time
fromClockTime :: ClockTime -> Timestamp
fromClockTime (TOD ctime pico) =
  (fromIntegral ctime, fromIntegral $ pico `div` 1000000)

-- | Get the current time in the job-queue timestamp format.
currentTimestamp :: IO Timestamp
currentTimestamp = fromClockTime `liftM` getClockTime

-- | From a given timestamp, obtain the timestamp of the
-- time that is the given number of seconds later.
advanceTimestamp :: Int -> Timestamp -> Timestamp
advanceTimestamp = first . (+)


-- | From an InputOpCode obtain the MetaOpCode, if any.
toMetaOpCode :: InputOpCode -> [MetaOpCode]
toMetaOpCode (ValidOpCode mopc) = [mopc]
toMetaOpCode _ = []

-- | Invalid opcode summary.
invalidOp :: String
invalidOp = "INVALID_OP"

-- | Tries to extract the opcode summary from an 'InputOpCode'. This
-- duplicates some functionality from the 'opSummary' function in
-- "Ganeti.OpCodes".
extractOpSummary :: InputOpCode -> String
extractOpSummary (ValidOpCode metaop) = opSummary $ metaOpCode metaop
extractOpSummary (InvalidOpCode (JSObject o)) =
  case fromObjWithDefault (fromJSObject o) "OP_ID" ("OP_" ++ invalidOp) of
    Just s -> drop 3 s -- drop the OP_ prefix
    Nothing -> invalidOp
extractOpSummary _ = invalidOp

-- | Convenience function to obtain a QueuedOpCode from a MetaOpCode
queuedOpCodeFromMetaOpCode :: MetaOpCode -> QueuedOpCode
queuedOpCodeFromMetaOpCode op =
  QueuedOpCode { qoInput = ValidOpCode op
               , qoStatus = OP_STATUS_QUEUED
               , qoPriority = opSubmitPriorityToRaw . opPriority . metaParams
                              $ op
               , qoLog = []
               , qoResult = JSNull
               , qoStartTimestamp = Nothing
               , qoEndTimestamp = Nothing
               , qoExecTimestamp = Nothing
               }

-- | From a job-id and a list of op-codes create a job. This is
-- the pure part of job creation, as allocating a new job id
-- lives in IO.
queuedJobFromOpCodes :: (Monad m) => JobId -> [MetaOpCode] -> m QueuedJob
queuedJobFromOpCodes jobid ops = do
  ops' <- mapM (`resolveDependencies` jobid) ops
  return QueuedJob { qjId = jobid
                   , qjOps = map queuedOpCodeFromMetaOpCode ops'
                   , qjReceivedTimestamp = Nothing
                   , qjStartTimestamp = Nothing
                   , qjEndTimestamp = Nothing
                   , qjLivelock = Nothing
                   , qjProcessId = Nothing
                   }

-- | Attach a received timestamp to a Queued Job.
setReceivedTimestamp :: Timestamp -> QueuedJob -> QueuedJob
setReceivedTimestamp ts job = job { qjReceivedTimestamp = Just ts }

-- | Build a timestamp in the format expected by the reason trail (nanoseconds)
-- starting from a JQueue Timestamp.
reasonTrailTimestamp :: Timestamp -> Integer
reasonTrailTimestamp (sec, micro) =
  let sec' = toInteger sec
      micro' = toInteger micro
  in sec' * 1000000000 + micro' * 1000

-- | Append an element to the reason trail of an input opcode.
extendInputOpCodeReasonTrail :: JobId -> Timestamp -> Int -> InputOpCode
                             -> InputOpCode
extendInputOpCodeReasonTrail _ _ _ op@(InvalidOpCode _) = op
extendInputOpCodeReasonTrail jid ts i (ValidOpCode vOp) =
  let metaP = metaParams vOp
      op = metaOpCode vOp
      trail = opReason metaP
      reasonSrc = opReasonSrcID op
      reasonText = "job=" ++ show (fromJobId jid) ++ ";index=" ++ show i
      reason = (reasonSrc, reasonText, reasonTrailTimestamp ts)
      trail' = trail ++ [reason]
  in ValidOpCode $ vOp { metaParams = metaP { opReason = trail' } }

-- | Append an element to the reason trail of a queued opcode.
extendOpCodeReasonTrail :: JobId -> Timestamp -> Int -> QueuedOpCode
                        -> QueuedOpCode
extendOpCodeReasonTrail jid ts i op =
  let inOp = qoInput op
  in op { qoInput = extendInputOpCodeReasonTrail jid ts i inOp }

-- | Append an element to the reason trail of all the OpCodes of a queued job.
extendJobReasonTrail :: QueuedJob -> QueuedJob
extendJobReasonTrail job =
  let jobId = qjId job
      mTimestamp = qjReceivedTimestamp job
      -- This function is going to be called on QueuedJobs that already contain
      -- a timestamp. But for safety reasons we cannot assume mTimestamp will
      -- be (Just timestamp), so we use the value 0 in the extremely unlikely
      -- case this is not true.
      timestamp = fromMaybe (0, 0) mTimestamp
    in job
        { qjOps =
            zipWith (extendOpCodeReasonTrail jobId timestamp) [0..] $
              qjOps job
        }

-- | From a queued job obtain the list of jobs it depends on.
getJobDependencies :: QueuedJob -> [JobId]
getJobDependencies job = do
  op <- qjOps job
  mopc <- toMetaOpCode $ qoInput op
  dep <- fromMaybe [] . opDepends $ metaParams mopc
  getJobIdFromDependency dep

-- | Change the priority of a QueuedOpCode, if it is not already
-- finalized.
changeOpCodePriority :: Int -> QueuedOpCode -> QueuedOpCode
changeOpCodePriority prio op =
  if qoStatus op > OP_STATUS_RUNNING
     then op
     else op { qoPriority = prio }

-- | Set the state of a QueuedOpCode to canceled.
cancelOpCode :: Timestamp -> QueuedOpCode -> QueuedOpCode
cancelOpCode now op =
  op { qoStatus = OP_STATUS_CANCELED, qoEndTimestamp = Just now }

-- | Change the priority of a job, i.e., change the priority of the
-- non-finalized opcodes.
changeJobPriority :: Int -> QueuedJob -> QueuedJob
changeJobPriority prio job =
  job { qjOps = map (changeOpCodePriority prio) $ qjOps job }

-- | Transform a QueuedJob that has not been started into its canceled form.
cancelQueuedJob :: Timestamp -> QueuedJob -> QueuedJob
cancelQueuedJob now job =
  let ops' = map (cancelOpCode now) $ qjOps job
  in job { qjOps = ops', qjEndTimestamp = Just now }

-- | Set the state of a QueuedOpCode to failed
-- and set the Op result using the given reason message.
failOpCode :: ReasonElem -> Timestamp -> QueuedOpCode -> QueuedOpCode
failOpCode reason@(_, msg, _) now op =
  over (qoInputL . validOpCodeL . metaParamsL . opReasonL) (++ [reason])
  op { qoStatus = OP_STATUS_ERROR
     , qoResult = Text.JSON.JSString . Text.JSON.toJSString $ msg
     , qoEndTimestamp = Just now }

-- | Transform a QueuedJob that has not been started into its failed form.
failQueuedJob :: ReasonElem -> Timestamp -> QueuedJob -> QueuedJob
failQueuedJob reason now job =
  let ops' = map (failOpCode reason now) $ qjOps job
  in job { qjOps = ops', qjEndTimestamp = Just now }

-- | Job file prefix.
jobFilePrefix :: String
jobFilePrefix = "job-"

-- | Computes the filename for a given job ID.
jobFileName :: JobId -> FilePath
jobFileName jid = jobFilePrefix ++ show (fromJobId jid)

-- | Parses a job ID from a file name.
parseJobFileId :: (Monad m) => FilePath -> m JobId
parseJobFileId path =
  case stripPrefix jobFilePrefix path of
    Nothing -> fail $ "Job file '" ++ path ++
                      "' doesn't have the correct prefix"
    Just suffix -> makeJobIdS suffix

-- | Computes the full path to a live job.
liveJobFile :: FilePath -> JobId -> FilePath
liveJobFile rootdir jid = rootdir </> jobFileName jid

-- | Computes the full path to an archives job. BROKEN.
archivedJobFile :: FilePath -> JobId -> FilePath
archivedJobFile rootdir jid =
  let subdir = show (fromJobId jid `div` C.jstoreJobsPerArchiveDirectory)
  in rootdir </> jobQueueArchiveSubDir </> subdir </> jobFileName jid

-- | Map from opcode status to job status.
opStatusToJob :: OpStatus -> JobStatus
opStatusToJob OP_STATUS_QUEUED    = JOB_STATUS_QUEUED
opStatusToJob OP_STATUS_WAITING   = JOB_STATUS_WAITING
opStatusToJob OP_STATUS_SUCCESS   = JOB_STATUS_SUCCESS
opStatusToJob OP_STATUS_RUNNING   = JOB_STATUS_RUNNING
opStatusToJob OP_STATUS_CANCELING = JOB_STATUS_CANCELING
opStatusToJob OP_STATUS_CANCELED  = JOB_STATUS_CANCELED
opStatusToJob OP_STATUS_ERROR     = JOB_STATUS_ERROR

-- | Computes a queued job's status.
calcJobStatus :: QueuedJob -> JobStatus
calcJobStatus QueuedJob { qjOps = ops } =
  extractOpSt (map qoStatus ops) JOB_STATUS_QUEUED True
    where
      terminalStatus OP_STATUS_ERROR     = True
      terminalStatus OP_STATUS_CANCELING = True
      terminalStatus OP_STATUS_CANCELED  = True
      terminalStatus _                   = False
      softStatus     OP_STATUS_SUCCESS   = True
      softStatus     OP_STATUS_QUEUED    = True
      softStatus     _                   = False
      extractOpSt [] _ True = JOB_STATUS_SUCCESS
      extractOpSt [] d False = d
      extractOpSt (x:xs) d old_all
           | terminalStatus x = opStatusToJob x -- abort recursion
           | softStatus x     = extractOpSt xs d new_all -- continue unchanged
           | otherwise        = extractOpSt xs (opStatusToJob x) new_all
           where new_all = x == OP_STATUS_SUCCESS && old_all

-- | Determine if a job has started
jobStarted :: QueuedJob -> Bool
jobStarted = (> JOB_STATUS_QUEUED) . calcJobStatus

-- | Determine if a job is finalised.
jobFinalized :: QueuedJob -> Bool
jobFinalized = (> JOB_STATUS_RUNNING) . calcJobStatus

-- | Determine if a job is finalized and its timestamp is before
-- a given time.
jobArchivable :: Timestamp -> QueuedJob -> Bool
jobArchivable ts = liftA2 (&&) jobFinalized
  $ maybe False (< ts)
    .  liftA2 (<|>) qjEndTimestamp qjStartTimestamp

-- | Determine whether an opcode status is finalized.
opStatusFinalized :: OpStatus -> Bool
opStatusFinalized = (> OP_STATUS_RUNNING)

-- | Compute a job's priority.
calcJobPriority :: QueuedJob -> Int
calcJobPriority QueuedJob { qjOps = ops } =
  helper . map qoPriority $ filter (not . opStatusFinalized . qoStatus) ops
    where helper [] = C.opPrioDefault
          helper ps = minimum ps

-- | Log but ignore an 'IOError'.
ignoreIOError :: a -> Bool -> String -> IOError -> IO a
ignoreIOError a ignore_noent msg e = do
  unless (isDoesNotExistError e && ignore_noent) .
    logWarning $ msg ++ ": " ++ show e
  return a

-- | Compute the list of existing archive directories. Note that I/O
-- exceptions are swallowed and ignored.
allArchiveDirs :: FilePath -> IO [FilePath]
allArchiveDirs rootdir = do
  let adir = rootdir </> jobQueueArchiveSubDir
  contents <- getDirectoryContents adir `Control.Exception.catch`
               ignoreIOError [] False
                 ("Failed to list queue directory " ++ adir)
  let fpaths = map (adir </>) $ filter (not . ("." `isPrefixOf`)) contents
  filterM (\path ->
             liftM isDirectory (getFileStatus (adir </> path))
               `Control.Exception.catch`
               ignoreIOError False True
                 ("Failed to stat archive path " ++ path)) fpaths

-- | Build list of directories containing job files. Note: compared to
-- the Python version, this doesn't ignore a potential lost+found
-- file.
determineJobDirectories :: FilePath -> Bool -> IO [FilePath]
determineJobDirectories rootdir archived = do
  other <- if archived
             then allArchiveDirs rootdir
             else return []
  return $ rootdir:other

-- | Computes the list of all jobs in the given directories.
getJobIDs :: [FilePath] -> IO (GenericResult IOError [JobId])
getJobIDs = runResultT . liftM concat . mapM getDirJobIDs

-- | Sorts the a list of job IDs.
sortJobIDs :: [JobId] -> [JobId]
sortJobIDs = sortBy (comparing fromJobId)

-- | Computes the list of jobs in a given directory.
getDirJobIDs :: FilePath -> ResultT IOError IO [JobId]
getDirJobIDs path =
  withErrorLogAt WARNING ("Failed to list job directory " ++ path) .
    liftM (mapMaybe parseJobFileId) $ liftIO (getDirectoryContents path)

-- | Reads the job data from disk.
readJobDataFromDisk :: FilePath -> Bool -> JobId -> IO (Maybe (String, Bool))
readJobDataFromDisk rootdir archived jid = do
  let live_path = liveJobFile rootdir jid
      archived_path = archivedJobFile rootdir jid
      all_paths = if archived
                    then [(live_path, False), (archived_path, True)]
                    else [(live_path, False)]
  foldM (\state (path, isarchived) ->
           liftM (\r -> Just (r, isarchived)) (readFile path)
             `Control.Exception.catch`
             ignoreIOError state True
               ("Failed to read job file " ++ path)) Nothing all_paths

-- | Failed to load job error.
noSuchJob :: Result (QueuedJob, Bool)
noSuchJob = Bad "Can't load job file"

-- | Loads a job from disk.
loadJobFromDisk :: FilePath -> Bool -> JobId -> IO (Result (QueuedJob, Bool))
loadJobFromDisk rootdir archived jid = do
  raw <- readJobDataFromDisk rootdir archived jid
  -- note: we need some stricness below, otherwise the wrapping in a
  -- Result will create too much lazyness, and not close the file
  -- descriptors for the individual jobs
  return $! case raw of
             Nothing -> noSuchJob
             Just (str, arch) ->
               liftM (\qj -> (qj, arch)) .
               fromJResult "Parsing job file" $ Text.JSON.decode str

-- | Write a job to disk.
writeJobToDisk :: FilePath -> QueuedJob -> IO (Result ())
writeJobToDisk rootdir job = do
  let filename = liveJobFile rootdir . qjId $ job
      content = Text.JSON.encode . Text.JSON.showJSON $ job
  tryAndLogIOError (atomicWriteFile filename content)
                   ("Failed to write " ++ filename) Ok

-- | Replicate a job to all master candidates.
replicateJob :: FilePath -> [Node] -> QueuedJob -> IO [(Node, ERpcError ())]
replicateJob rootdir mastercandidates job = do
  let filename = liveJobFile rootdir . qjId $ job
      content = Text.JSON.encode . Text.JSON.showJSON $ job
  filename' <- makeVirtualPath filename
  callresult <- executeRpcCall mastercandidates
                  $ RpcCallJobqueueUpdate filename' content
  let result = map (second (() <$)) callresult
  _ <- logRpcErrors result
  return result

-- | Replicate many jobs to all master candidates.
replicateManyJobs :: FilePath -> [Node] -> [QueuedJob] -> IO ()
replicateManyJobs rootdir mastercandidates =
  mapM_ (replicateJob rootdir mastercandidates)

-- | Writes a job to a file and replicates it to master candidates.
writeAndReplicateJob :: (Error e)
                     => ConfigData -> FilePath -> QueuedJob
                     -> ResultT e IO [(Node, ERpcError ())]
writeAndReplicateJob cfg rootdir job = do
  mkResultT $ writeJobToDisk rootdir job
  liftIO $ replicateJob rootdir (Config.getMasterCandidates cfg) job

-- | Read the job serial number from disk.
readSerialFromDisk :: IO (Result JobId)
readSerialFromDisk = do
  filename <- jobQueueSerialFile
  tryAndLogIOError (readFile filename) "Failed to read serial file"
                   (makeJobIdS . rStripSpace)

-- | Allocate new job ids.
-- To avoid races while accessing the serial file, the threads synchronize
-- over a lock, as usual provided by a Lock.
allocateJobIds :: [Node] -> Lock -> Int -> IO (Result [JobId])
allocateJobIds mastercandidates lock n =
  if n <= 0
    then if n == 0
           then return $ Ok []
           else return . Bad
                  $ "Can only allocate non-negative number of job ids"
    else withLock lock $ do
      rjobid <- readSerialFromDisk
      case rjobid of
        Bad s -> return . Bad $ s
        Ok jid -> do
          let current = fromJobId jid
              serial_content = show (current + n) ++  "\n"
          serial <- jobQueueSerialFile
          write_result <- try $ atomicWriteFile serial serial_content
                          :: IO (Either IOError ())
          case write_result of
            Left e -> do
              let msg = "Failed to write serial file: " ++ show e
              logError msg
              return . Bad $ msg
            Right () -> do
              serial' <- makeVirtualPath serial
              _ <- executeRpcCall mastercandidates
                     $ RpcCallJobqueueUpdate serial' serial_content
              return $ mapM makeJobId [(current+1)..(current+n)]

-- | Allocate one new job id.
allocateJobId :: [Node] -> Lock -> IO (Result JobId)
allocateJobId mastercandidates lock = do
  jids <- allocateJobIds mastercandidates lock 1
  return (jids >>= monadicThe "Failed to allocate precisely one Job ID")

-- | Decide if job queue is open
isQueueOpen :: IO Bool
isQueueOpen = liftM not (jobQueueDrainFile >>= doesFileExist)

-- | Start enqueued jobs by executing the Python code.
startJobs :: Livelock -- ^ Luxi's livelock path
          -> Lock -- ^ lock for forking new processes
          -> [QueuedJob] -- ^ the list of jobs to start
          -> IO [ErrorResult QueuedJob]
startJobs luxiLivelock forkLock jobs = do
  qdir <- queueDir
  let updateJob job llfile =
        void . mkResultT . writeJobToDisk qdir
          $ job { qjLivelock = Just llfile }
  let runJob job = withLock forkLock $ do
        (llfile, _) <- Exec.forkJobProcess job luxiLivelock
                                           (updateJob job)
        return $ job { qjLivelock = Just llfile }
  mapM (runResultT . runJob) jobs

-- | Try to prove that a queued job is dead. This function needs to know
-- the livelock of the caller (i.e., luxid) to avoid considering a job dead
-- that is in the process of forking off.
isQueuedJobDead :: MonadIO m => Livelock -> QueuedJob -> m Bool
isQueuedJobDead ownlivelock =
  maybe (return False) (liftIO . isDead)
  . mfilter (/= ownlivelock)
  . qjLivelock

-- | Waits for a job's process to exit
waitUntilJobExited :: Livelock -- ^ LuxiD's own livelock
                   -> QueuedJob -- ^ the job to wait for
                   -> Int -- ^ timeout in milliseconds
                   -> ResultG (Bool, String)
waitUntilJobExited ownlivelock job tmout = do
  let sleepDelay = 100 :: Int -- ms
      jName = ("Job " ++) . show . fromJobId . qjId $ job
  logDebug $ "Waiting for " ++ jName ++ " to exit"

  start <- liftIO getClockTime
  let tmoutPicosec :: Integer
      tmoutPicosec = fromIntegral $ tmout * 1000 * 1000 * 1000
      wait = noTimeDiff { tdPicosec = tmoutPicosec }
      deadline = addToClockTime wait start

  liftIO . fix $ \loop -> do
    -- fail if the job is in the startup phase or has no livelock
    dead <- maybe (fail $ jName ++ " has not yet started up")
      (liftIO . isDead) . mfilter (/= ownlivelock) . qjLivelock $ job
    curtime <- getClockTime
    let elapsed = timeDiffToString $ System.Time.diffClockTimes
                  curtime start
    case dead of
      True -> return (True, jName ++ " process exited after " ++ elapsed)
      _ | curtime < deadline -> threadDelay (sleepDelay * 1000) >> loop
      _ -> fail $ jName ++ " still running after " ++ elapsed

-- | Waits for a job ordered to cancel to react, and returns whether it was
-- canceled, and a user-intended description of the reason.
waitForJobCancelation :: JobId -> Int -> ResultG (Bool, String)
waitForJobCancelation jid tmout = do
  qDir <- liftIO queueDir
  let jobfile = liveJobFile qDir jid
      load = liftM fst <$> loadJobFromDisk qDir False jid
      finalizedR = genericResult (const False) jobFinalized
  jobR <- liftIO $ watchFileBy jobfile tmout finalizedR load
  case calcJobStatus <$> jobR of
    Ok s | s == JOB_STATUS_CANCELED ->
             return (True, "Job successfully cancelled")
         | finalizedR jobR ->
            return (False, "Job exited before it could have been canceled,\
                           \ status " ++ show s)
         | otherwise ->
             return (False, "Job could not be canceled, status "
                            ++ show s)
    Bad e -> failError $ "Can't read job status: " ++ e

-- | Try to cancel a job that has already been handed over to execution,
-- by terminating the process.
cancelJob :: Bool -- ^ if True, use sigKILL instead of sigTERM
          -> Livelock -- ^ Luxi's livelock path
          -> JobId -- ^ the job to cancel
          -> IO (ErrorResult (Bool, String))
cancelJob kill luxiLivelock jid = runResultT $ do
  -- we can't terminate the job if it's just being started, so
  -- retry several times in such a case
  result <- runMaybeT . msum . flip map [0..5 :: Int] $ \tryNo -> do
    -- if we're retrying, sleep for some time
    when (tryNo > 0) . liftIO . threadDelay $ 100000 * (2 ^ tryNo)

    -- first check if the job is alive so that we don't kill some other
    -- process by accident
    qDir <- liftIO queueDir
    (job, _) <- lift . mkResultT $ loadJobFromDisk qDir True jid
    let jName = ("Job " ++) . show . fromJobId . qjId $ job
    dead <- isQueuedJobDead luxiLivelock job
    case qjProcessId job of
      _ | dead ->
        return (True, jName ++ " has been already dead")
      Just pid -> do
        liftIO $ signalProcess (if kill then sigKILL else sigTERM) pid
        if not kill then
          if calcJobStatus job > JOB_STATUS_WAITING
            then return (False, "Job no longer waiting, can't cancel\
                                \ (informed it anyway)")
            else lift $ waitForJobCancelation jid C.luxiCancelJobTimeout
          else return (True, "SIGKILL send to the process")
      _ -> do
        logDebug $ jName ++ " in its startup phase, retrying"
        mzero
  return $ fromMaybe (False, "Timeout: job still in its startup phase") result

-- | Inform a job that it is requested to change its priority. This is done
-- by writing the new priority to a file and sending SIGUSR1.
tellJobPriority :: Livelock -- ^ Luxi's livelock path
                -> JobId -- ^ the job to inform
                -> Int -- ^ the new priority
                -> IO (ErrorResult (Bool, String))
tellJobPriority luxiLivelock jid prio = runResultT $ do
  let  jidS = show $ fromJobId jid
       jName = "Job " ++ jidS
  mDir <- liftIO luxidMessageDir
  let prioFile = mDir </> jidS ++ ".prio"
  liftIO . atomicWriteFile prioFile $ show prio
  qDir <- liftIO queueDir
  (job, _) <- mkResultT $ loadJobFromDisk qDir True jid
  dead <- isQueuedJobDead luxiLivelock job
  case qjProcessId job of
    _ | dead -> do
      liftIO $ removeFile prioFile
      return (False, jName ++ " is dead")
    Just pid -> do
      liftIO $ signalProcess sigUSR1 pid
      return (True, jName ++ " with pid " ++ show pid ++ " signaled")
    _ -> return (False, jName ++ "'s pid unknown")

-- | Notify a job that something relevant happened, e.g., a lock became
-- available. We do this by sending sigHUP to the process.
notifyJob :: ProcessID  -> IO (ErrorResult ())
notifyJob pid = runResultT $ do
  logDebug $ "Signalling process " ++ show pid
  liftIO $ signalProcess sigHUP pid

-- | Permissions for the archive directories.
queueDirPermissions :: FilePermissions
queueDirPermissions = FilePermissions { fpOwner = Just GanetiMasterd
                                      , fpGroup = Just $ ExtraGroup DaemonsGroup
                                      , fpPermissions = 0o0750
                                      }

-- | Try, at most until the given endtime, to archive some of the given
-- jobs, if they are older than the specified cut-off time; also replicate
-- archival of the additional jobs. Return the pair of the number of jobs
-- archived, and the number of jobs remaining int he queue, asuming the
-- given numbers about the not considered jobs.
archiveSomeJobsUntil :: ([JobId] -> IO ()) -- ^ replication function
                        -> FilePath -- ^ queue root directory
                        -> ClockTime -- ^ Endtime
                        -> Timestamp -- ^ cut-off time for archiving jobs
                        -> Int -- ^ number of jobs alread archived
                        -> [JobId] -- ^ Additional jobs to replicate
                        -> [JobId] -- ^ List of job-ids still to consider
                        -> IO (Int, Int)
archiveSomeJobsUntil replicateFn _ _ _ arch torepl [] = do
  unless (null torepl) . (>> return ())
   . forkIO $ replicateFn torepl
  return (arch, 0)

archiveSomeJobsUntil replicateFn qDir endt cutt arch torepl (jid:jids) = do
  let archiveMore = archiveSomeJobsUntil replicateFn qDir endt cutt
      continue = archiveMore arch torepl jids
      jidname = show $ fromJobId jid
  time <- getClockTime
  if time >= endt
    then do
      _ <- forkIO $ replicateFn torepl
      return (arch, length (jid:jids))
    else do
      logDebug $ "Inspecting job " ++ jidname ++ " for archival"
      loadResult <- loadJobFromDisk qDir False jid
      case loadResult of
        Bad _ -> continue
        Ok (job, _) ->
          if jobArchivable cutt job
            then do
              let live = liveJobFile qDir jid
                  archive = archivedJobFile qDir jid
              renameResult <- safeRenameFile queueDirPermissions
                                live archive
              case renameResult of
                Bad s -> do
                  logWarning $ "Renaming " ++ live ++ " to " ++ archive
                                 ++ " failed unexpectedly: " ++ s
                  continue
                Ok () -> do
                  let torepl' = jid:torepl
                  if length torepl' >= 10
                    then do
                      _ <- forkIO $ replicateFn torepl'
                      archiveMore (arch + 1) [] jids
                    else archiveMore (arch + 1) torepl' jids
            else continue

-- | Archive jobs older than the given time, but do not exceed the timeout for
-- carrying out this task.
archiveJobs :: ConfigData -- ^ cluster configuration
               -> Int  -- ^ time the job has to be in the past in order
                       -- to be archived
               -> Int -- ^ timeout
               -> [JobId] -- ^ jobs to consider
               -> IO (Int, Int)
archiveJobs cfg age timeout jids = do
  now <- getClockTime
  qDir <- queueDir
  let endtime = addToClockTime (noTimeDiff { tdSec = timeout }) now
      cuttime = if age < 0 then noTimestamp
                           else advanceTimestamp (- age) (fromClockTime now)
      mcs = Config.getMasterCandidates cfg
      replicateFn jobs = do
        let olds = map (liveJobFile qDir) jobs
            news = map (archivedJobFile qDir) jobs
        _ <- executeRpcCall mcs . RpcCallJobqueueRename $ zip olds news
        return ()
  archiveSomeJobsUntil replicateFn qDir endtime cuttime 0 [] jids

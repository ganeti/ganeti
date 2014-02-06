{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the job queue.

-}

{-

Copyright (C) 2010, 2012 Google Inc.

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

module Ganeti.JQueue
    ( QueuedOpCode(..)
    , QueuedJob(..)
    , InputOpCode(..)
    , queuedOpCodeFromMetaOpCode
    , queuedJobFromOpCodes
    , changeOpCodePriority
    , changeJobPriority
    , cancelQueuedJob
    , Timestamp
    , fromClockTime
    , noTimestamp
    , currentTimestamp
    , advanceTimestamp
    , setReceivedTimestamp
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
    , isQueueOpen
    , startJobs
    , cancelJob
    , queueDirPermissions
    , archiveJobs
    ) where

import Control.Applicative (liftA2, (<|>))
import Control.Arrow (first, second)
import Control.Concurrent (forkIO)
import Control.Concurrent.MVar
import Control.Exception
import Control.Monad
import Control.Monad.IO.Class
import Data.Functor ((<$))
import Data.List
import Data.Maybe
import Data.Ord (comparing)
-- workaround what seems to be a bug in ghc 7.4's TH shadowing code
import Prelude hiding (id, log)
import System.Directory
import System.FilePath
import System.IO.Error (isDoesNotExistError)
import System.Posix.Files
import System.Time
import qualified Text.JSON
import Text.JSON.Types

import Ganeti.BasicTypes
import qualified Ganeti.Config as Config
import qualified Ganeti.Constants as C
import Ganeti.Errors (ErrorResult)
import Ganeti.JSON
import Ganeti.Logging
import Ganeti.Luxi
import Ganeti.Objects (ConfigData, Node)
import Ganeti.OpCodes
import Ganeti.Path
import Ganeti.Rpc (executeRpcCall, ERpcError, logRpcErrors,
                   RpcCallJobqueueUpdate(..), RpcCallJobqueueRename(..))
import Ganeti.THH
import Ganeti.Types
import Ganeti.Utils
import Ganeti.VCluster (makeVirtualPath)

-- * Data types

-- | The ganeti queue timestamp type. It represents the time as the pair
-- of seconds since the epoch and microseconds since the beginning of the
-- second.
type Timestamp = (Int, Int)

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

-- | An input opcode.
data InputOpCode = ValidOpCode MetaOpCode -- ^ OpCode was parsed successfully
                 | InvalidOpCode JSValue  -- ^ Invalid opcode
                   deriving (Show, Eq)

-- | JSON instance for 'InputOpCode', trying to parse it and if
-- failing, keeping the original JSValue.
instance Text.JSON.JSON InputOpCode where
  showJSON (ValidOpCode mo) = Text.JSON.showJSON mo
  showJSON (InvalidOpCode inv) = inv
  readJSON v = case Text.JSON.readJSON v of
                 Text.JSON.Error _ -> return $ InvalidOpCode v
                 Text.JSON.Ok mo -> return $ ValidOpCode mo

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

$(buildObject "QueuedOpCode" "qo"
  [ simpleField "input"           [t| InputOpCode |]
  , simpleField "status"          [t| OpStatus    |]
  , simpleField "result"          [t| JSValue     |]
  , defaultField [| [] |] $
    simpleField "log"             [t| [(Int, Timestamp, ELogType, JSValue)] |]
  , simpleField "priority"        [t| Int         |]
  , optionalNullSerField $
    simpleField "start_timestamp" [t| Timestamp   |]
  , optionalNullSerField $
    simpleField "exec_timestamp"  [t| Timestamp   |]
  , optionalNullSerField $
    simpleField "end_timestamp"   [t| Timestamp   |]
  ])

$(buildObject "QueuedJob" "qj"
  [ simpleField "id"                 [t| JobId          |]
  , simpleField "ops"                [t| [QueuedOpCode] |]
  , optionalNullSerField $
    simpleField "received_timestamp" [t| Timestamp      |]
  , optionalNullSerField $
    simpleField "start_timestamp"    [t| Timestamp      |]
  , optionalNullSerField $
    simpleField "end_timestamp"      [t| Timestamp      |]
  ])

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
                   }

-- | Attach a received timestamp to a Queued Job.
setReceivedTimestamp :: Timestamp -> QueuedJob -> QueuedJob
setReceivedTimestamp ts job = job { qjReceivedTimestamp = Just ts }

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
  in job { qjOps = ops', qjEndTimestamp = Just now}

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
  logRpcErrors result
  return result

-- | Replicate many jobs to all master candidates.
replicateManyJobs :: FilePath -> [Node] -> [QueuedJob] -> IO ()
replicateManyJobs rootdir mastercandidates =
  mapM_ (replicateJob rootdir mastercandidates)

-- | Read the job serial number from disk.
readSerialFromDisk :: IO (Result JobId)
readSerialFromDisk = do
  filename <- jobQueueSerialFile
  tryAndLogIOError (readFile filename) "Failed to read serial file"
                   (makeJobIdS . rStripSpace)

-- | Allocate new job ids.
-- To avoid races while accessing the serial file, the threads synchronize
-- over a lock, as usual provided by an MVar.
allocateJobIds :: [Node] -> MVar () -> Int -> IO (Result [JobId])
allocateJobIds mastercandidates lock n =
  if n <= 0
    then return . Bad $ "Can only allocate positive number of job ids"
    else do
      takeMVar lock
      rjobid <- readSerialFromDisk
      case rjobid of
        Bad s -> do
          putMVar lock ()
          return . Bad $ s
        Ok jid -> do
          let current = fromJobId jid
              serial_content = show (current + n) ++  "\n"
          serial <- jobQueueSerialFile
          write_result <- try $ atomicWriteFile serial serial_content
                          :: IO (Either IOError ())
          case write_result of
            Left e -> do
              putMVar lock ()
              let msg = "Failed to write serial file: " ++ show e
              logError msg
              return . Bad $ msg 
            Right () -> do
              serial' <- makeVirtualPath serial
              _ <- executeRpcCall mastercandidates
                     $ RpcCallJobqueueUpdate serial' serial_content
              putMVar lock ()
              return $ mapM makeJobId [(current+1)..(current+n)]

-- | Allocate one new job id.
allocateJobId :: [Node] -> MVar () -> IO (Result JobId)
allocateJobId mastercandidates lock = do
  jids <- allocateJobIds mastercandidates lock 1
  return (jids >>= monadicThe "Failed to allocate precisely one Job ID")

-- | Decide if job queue is open
isQueueOpen :: IO Bool
isQueueOpen = liftM not (jobQueueDrainFile >>= doesFileExist)

-- | Start enqueued jobs, currently by handing them over to masterd.
startJobs :: [QueuedJob] -> IO ()
startJobs jobs = do
  socketpath <- defaultMasterSocket
  client <- getLuxiClient socketpath
  pickupResults <- mapM (flip callMethod client . PickupJob . qjId) jobs
  let failures = map show $ justBad pickupResults
  unless (null failures)
   . logWarning . (++) "Failed to notify masterd: " . commaJoin $ failures

-- | Try to cancel a job that has already been handed over to execution,
-- currently by asking masterd to cancel it.
cancelJob :: JobId -> IO (ErrorResult JSValue)
cancelJob jid = do
  socketpath <- defaultMasterSocket
  client <- getLuxiClient socketpath
  callMethod (CancelJob jid) client

-- | Permissions for the archive directories.
queueDirPermissions :: FilePermissions
queueDirPermissions = FilePermissions { fpOwner = Just C.masterdUser
                                      , fpGroup = Just C.daemonsGroup
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

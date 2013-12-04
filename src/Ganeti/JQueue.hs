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
    , Timestamp
    , noTimestamp
    , currentTimestamp
    , setReceivedTimestamp
    , opStatusFinalized
    , extractOpSummary
    , calcJobStatus
    , jobStarted
    , jobFinalized
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
    ) where

import Control.Concurrent.MVar
import Control.Exception
import Control.Monad
import Data.List
import Data.Maybe
import Data.Ord (comparing)
-- workaround what seems to be a bug in ghc 7.4's TH shadowing code
import Prelude hiding (log, id)
import System.Directory
import System.FilePath
import System.IO.Error (isDoesNotExistError)
import System.Posix.Files
import System.Time
import qualified Text.JSON
import Text.JSON.Types

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.JSON
import Ganeti.Logging
import Ganeti.Luxi
import Ganeti.Objects (Node)
import Ganeti.OpCodes
import Ganeti.Path
import Ganeti.Rpc (executeRpcCall, ERpcError, logRpcErrors,
                   RpcCallJobqueueUpdate(..))
import Ganeti.THH
import Ganeti.Types
import Ganeti.Utils

-- * Data types

-- | The ganeti queue timestamp type. It represents the time as the pair
-- of seconds since the epoch and microseconds since the beginning of the
-- second.
type Timestamp = (Int, Int)

-- | Missing timestamp type.
noTimestamp :: Timestamp
noTimestamp = (-1, -1)

-- | Get the current time in the job-queue timestamp format.
currentTimestamp :: IO Timestamp
currentTimestamp = do
  TOD ctime pico <- getClockTime
  return (fromIntegral ctime, fromIntegral $ pico `div` 1000000)

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

-- Function equivalent to the \'sequence\' function, that cannot be used because
-- of library version conflict on Lucid.
-- FIXME: delete this and just use \'sequence\' instead when Lucid compatibility
-- will not be required anymore.
sequencer :: [Either IOError [JobId]] -> Either IOError [[JobId]]
sequencer l = fmap reverse $ foldl seqFolder (Right []) l

-- | Folding function for joining multiple [JobIds] into one list.
seqFolder :: Either IOError [[JobId]]
          -> Either IOError [JobId]
          -> Either IOError [[JobId]]
seqFolder (Left e) _ = Left e
seqFolder (Right _) (Left e) = Left e
seqFolder (Right l) (Right el) = Right $ el:l

-- | Computes the list of all jobs in the given directories.
getJobIDs :: [FilePath] -> IO (Either IOError [JobId])
getJobIDs paths = liftM (fmap concat . sequencer) (mapM getDirJobIDs paths)

-- | Sorts the a list of job IDs.
sortJobIDs :: [JobId] -> [JobId]
sortJobIDs = sortBy (comparing fromJobId)

-- | Computes the list of jobs in a given directory.
getDirJobIDs :: FilePath -> IO (Either IOError [JobId])
getDirJobIDs path = do
  either_contents <-
    try (getDirectoryContents path) :: IO (Either IOError [FilePath])
  case either_contents of
    Left e -> do
      logWarning $ "Failed to list job directory " ++ path ++ ": " ++ show e
      return $ Left e
    Right contents -> do
      let jids = foldl (\ids file ->
                         case parseJobFileId file of
                           Nothing -> ids
                           Just new_id -> new_id:ids) [] contents
      return . Right $ reverse jids

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
  result <- executeRpcCall mastercandidates
              $ RpcCallJobqueueUpdate filename content
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
              _ <- executeRpcCall mastercandidates
                     $ RpcCallJobqueueUpdate serial serial_content
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
  client <- getClient socketpath
  pickupResults <- mapM (flip callMethod client . PickupJob . qjId) jobs
  let failures = map show $ justBad pickupResults
  unless (null failures)
   . logWarning . (++) "Failed to notify masterd: " . commaJoin $ failures

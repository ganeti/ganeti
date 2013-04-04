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
    , Timestamp
    , noTimestamp
    , opStatusFinalized
    , extractOpSummary
    , calcJobStatus
    , calcJobPriority
    , jobFileName
    , liveJobFile
    , archivedJobFile
    , determineJobDirectories
    , getJobIDs
    , sortJobIDs
    , loadJobFromDisk
    , noSuchJob
    ) where

import Control.Exception
import Control.Monad
import Data.List
import Data.Ord (comparing)
-- workaround what seems to be a bug in ghc 7.4's TH shadowing code
import Prelude hiding (log, id)
import System.Directory
import System.FilePath
import System.IO.Error (isDoesNotExistError)
import System.Posix.Files
import qualified Text.JSON
import Text.JSON.Types

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.JSON
import Ganeti.Logging
import Ganeti.OpCodes
import Ganeti.Path
import Ganeti.THH
import Ganeti.Types

-- * Data types

-- | The ganeti queue timestamp type
type Timestamp = (Int, Int)

-- | Missing timestamp type.
noTimestamp :: Timestamp
noTimestamp = (-1, -1)

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
getJobIDs :: [FilePath] -> IO (Either IOError [JobId])
getJobIDs paths = liftM (fmap concat . sequence) (mapM getDirJobIDs paths)

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

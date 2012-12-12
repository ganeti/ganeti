{-| Generic code to work with jobs, e.g. submit jobs and check their status.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Ganeti.Jobs
  ( execJobsWait
  , waitForJobs
  ) where

import Control.Concurrent (threadDelay)

import Ganeti.BasicTypes
import Ganeti.Errors
import qualified Ganeti.Luxi as L
import Ganeti.OpCodes
import Ganeti.Types

-- | Executes a set of jobs and waits for their completion, returning their
-- status.
execJobsWait :: [[MetaOpCode]]        -- ^ The list of jobs
             -> ([L.JobId] -> IO ())  -- ^ Post-submission callback
             -> L.Client              -- ^ The Luxi client
             -> IO (Result [(L.JobId, JobStatus)])
execJobsWait opcodes callback client = do
  jids <- L.submitManyJobs client opcodes
  case jids of
    Bad e -> return . Bad $ "Job submission error: " ++ formatError e
    Ok jids' -> do
      callback jids'
      waitForJobs jids' client

-- | Polls a set of jobs at a fixed interval until all are finished
-- one way or another.
waitForJobs :: [L.JobId] -> L.Client -> IO (Result [(L.JobId, JobStatus)])
waitForJobs jids client = do
  sts <- L.queryJobsStatus client jids
  case sts of
    Bad e -> return . Bad $ "Checking job status: " ++ formatError e
    Ok sts' -> if any (<= JOB_STATUS_RUNNING) sts'
            then do
              -- TODO: replace hardcoded value with a better thing
              threadDelay (1000000 * 15)
              waitForJobs jids client
            else return . Ok $ zip jids sts'

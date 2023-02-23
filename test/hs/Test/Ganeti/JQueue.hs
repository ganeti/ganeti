{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for the job queue functionality.

-}

{-

Copyright (C) 2012, 2013 Google Inc.
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

module Test.Ganeti.JQueue (testJQueue) where

import Control.Monad (when)
import Data.Char (isAscii)
import Data.List (nub, sort)
import System.Directory
import System.FilePath
import System.IO.Temp
import System.Posix.Files
import Test.HUnit
import Test.QuickCheck as QuickCheck
import Test.QuickCheck.Monadic
import Text.JSON

import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper
import Test.Ganeti.Types ()

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.JQueue
import Ganeti.OpCodes
import Ganeti.Path
import Ganeti.Types as Types
import Test.Ganeti.JQueue.Objects (justNoTs, genQueuedOpCode, emptyJob,
                                   genJobId)

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Test cases

-- | Tests default priority value.
case_JobPriorityDef :: Assertion
case_JobPriorityDef = do
  ej <- emptyJob
  assertEqual "for default priority" C.opPrioDefault $ calcJobPriority ej

-- | Test arbitrary priorities.
prop_JobPriority :: Property
prop_JobPriority =
  forAll (listOf1 (genQueuedOpCode `suchThat`
                   (not . opStatusFinalized . qoStatus)))
         $ \ops -> property $ do
  jid0 <- makeJobId 0
  let job = QueuedJob jid0 ops justNoTs justNoTs justNoTs Nothing Nothing
  return $ calcJobPriority job ==? minimum (map qoPriority ops) :: Gen Property

-- | Tests default job status.
case_JobStatusDef :: Assertion
case_JobStatusDef = do
  ej <- emptyJob
  assertEqual "for job status" JOB_STATUS_SUCCESS $ calcJobStatus ej

-- | Test some job status properties.
prop_JobStatus :: Property
prop_JobStatus =
  forAll genJobId $ \jid ->
  forAll genQueuedOpCode $ \op ->
  let job1 = QueuedJob jid [op] justNoTs justNoTs justNoTs Nothing Nothing
      st1 = calcJobStatus job1
      op_succ = op { qoStatus = OP_STATUS_SUCCESS }
      op_err  = op { qoStatus = OP_STATUS_ERROR }
      op_cnl  = op { qoStatus = OP_STATUS_CANCELING }
      op_cnd  = op { qoStatus = OP_STATUS_CANCELED }
      -- computes status for a job with an added opcode before
      st_pre_op pop = calcJobStatus (job1 { qjOps = pop:qjOps job1 })
      -- computes status for a job with an added opcode after
      st_post_op pop = calcJobStatus (job1 { qjOps = qjOps job1 ++ [pop] })
  in conjoin
     [ counterexample "pre-success doesn't change status"
       (st_pre_op op_succ ==? st1)
     , counterexample "post-success doesn't change status"
       (st_post_op op_succ ==? st1)
     , counterexample "pre-error is error"
       (st_pre_op op_err ==? JOB_STATUS_ERROR)
     , counterexample "pre-canceling is canceling"
       (st_pre_op op_cnl ==? JOB_STATUS_CANCELING)
     , counterexample "pre-canceled is canceled"
       (st_pre_op op_cnd ==? JOB_STATUS_CANCELED)
     ]

-- | Tests job status equivalence with Python. Very similar to OpCodes test.
case_JobStatusPri_py_equiv :: Assertion
case_JobStatusPri_py_equiv = do
  let num_jobs = 2000::Int
  jobs <- genSample (vectorOf num_jobs $ do
                       num_ops <- choose (1, 5)
                       ops <- vectorOf num_ops genQueuedOpCode
                       jid <- genJobId
                       return $ QueuedJob jid ops justNoTs justNoTs justNoTs
                                          Nothing Nothing)
  let serialized = encode jobs
  -- check for non-ASCII fields, usually due to 'arbitrary :: String'
  mapM_ (\job -> when (any (not . isAscii) (encode job)) .
                 assertFailure $ "Job has non-ASCII fields: " ++ show job
        ) jobs
  py_stdout <-
     runPython "from ganeti import jqueue\n\
               \from ganeti import serializer\n\
               \import sys\n\
               \job_data = serializer.Load(sys.stdin.read())\n\
               \decoded = [jqueue._QueuedJob.Restore(None, o, False, False)\n\
               \           for o in job_data]\n\
               \encoded = [(job.CalcStatus(), job.CalcPriority())\n\
               \           for job in decoded]\n\
               \print serializer.Dump(encoded)" serialized
     >>= checkPythonResult
  let deserialised = decode py_stdout::Text.JSON.Result [(String, Int)]
  decoded <- case deserialised of
               Text.JSON.Ok jobs' -> return jobs'
               Error msg ->
                 assertFailure ("Unable to decode jobs: " ++ msg)
                 -- this already raised an exception, but we need it
                 -- for proper types
                 >> fail "Unable to decode jobs"
  assertEqual "Mismatch in number of returned jobs"
    (length decoded) (length jobs)
  mapM_ (\(py_sp, job) ->
           let hs_sp = (jobStatusToRaw $ calcJobStatus job,
                        calcJobPriority job)
           in assertEqual ("Different result after encoding/decoding for " ++
                           show job) hs_sp py_sp
        ) $ zip decoded jobs

-- | Tests listing of Job ids.
prop_ListJobIDs :: Property
prop_ListJobIDs = monadicIO $ do
  let extractJobIDs :: (Show e, Monad m) => m (GenericResult e a) -> m a
      extractJobIDs = (>>= genericResult (fail . show) return)
  jobs <- pick $ resize 10 (listOf1 genJobId `suchThat` (\l -> l == nub l))
  (e, f, g) <-
    run . withSystemTempDirectory "jqueue-test-ListJobIDs." $ \tempdir -> do
    empty_dir <- extractJobIDs $ getJobIDs [tempdir]
    mapM_ (\jid -> writeFile (tempdir </> jobFileName jid) "") jobs
    full_dir <- extractJobIDs $ getJobIDs [tempdir]
    invalid_dir <- getJobIDs [tempdir </> "no-such-dir"]
    return (empty_dir, sortJobIDs full_dir, invalid_dir)
  _ <- stop $ conjoin [ counterexample "empty directory" $ e ==? []
                      , counterexample "directory with valid names" $
                        f ==? sortJobIDs jobs
                      , counterexample "invalid directory" $ isBad g
                      ]
  return ()

-- | Tests loading jobs from disk.
prop_LoadJobs :: Property
prop_LoadJobs = monadicIO $ do
  ops <- pick $ resize 5 (listOf1 genQueuedOpCode)
  jid <- pick genJobId
  let job = QueuedJob jid ops justNoTs justNoTs justNoTs Nothing Nothing
      job_s = encode job
  -- check that jobs in the right directories are parsed correctly
  (missing, current, archived, missing_current, broken) <-
    run  . withSystemTempDirectory "jqueue-test-LoadJobs." $ \tempdir -> do
    let load a = loadJobFromDisk tempdir a jid
        live_path = liveJobFile tempdir jid
        arch_path = archivedJobFile tempdir jid
    createDirectory $ tempdir </> jobQueueArchiveSubDir
    createDirectory $ dropFileName arch_path
    -- missing job
    missing <- load True
    writeFile live_path job_s
    -- this should exist
    current <- load False
    removeFile live_path
    writeFile arch_path job_s
    -- this should exist (archived)
    archived <- load True
    -- this should be missing
    missing_current <- load False
    removeFile arch_path
    writeFile live_path "invalid job"
    broken <- load True
    return (missing, current, archived, missing_current, broken)
  _ <- stop $ conjoin [ missing ==? noSuchJob
                      , current ==? Ganeti.BasicTypes.Ok (job, False)
                      , archived ==? Ganeti.BasicTypes.Ok (job, True)
                      , missing_current ==? noSuchJob
                      , counterexample "broken job" (isBad broken)
                      ]
  return ()

-- | Tests computing job directories. Creates random directories,
-- files and stale symlinks in a directory, and checks that we return
-- \"the right thing\".
prop_DetermineDirs :: Property
prop_DetermineDirs = monadicIO $ do
  count <- pick $ choose (2, 10)
  nums <- pick $ genUniquesList count
          (arbitrary::Gen (QuickCheck.Positive Int))
  let (valid, invalid) = splitAt (count `div` 2) $
                         map (\(QuickCheck.Positive i) -> show i) nums
  (tempdir, non_arch, with_arch, invalid_root) <-
    run  . withSystemTempDirectory "jqueue-test-DetermineDirs." $ \tempdir -> do
    let arch_dir = tempdir </> jobQueueArchiveSubDir
    createDirectory arch_dir
    mapM_ (createDirectory . (arch_dir </>)) valid
    mapM_ (\p -> writeFile (arch_dir </> p) "") invalid
    mapM_ (\p -> createSymbolicLink "/dev/null/no/such/file"
                 (arch_dir </> p <.> "missing")) invalid
    non_arch <- determineJobDirectories tempdir False
    with_arch <- determineJobDirectories tempdir True
    invalid_root <- determineJobDirectories (tempdir </> "no-such-subdir") True
    return (tempdir, non_arch, with_arch, invalid_root)
  let arch_dir = tempdir </> jobQueueArchiveSubDir
  _ <- stop $ conjoin [ non_arch ==? [tempdir]
                      , sort with_arch ==?
                          sort (tempdir:map (arch_dir </>) valid)
                      , invalid_root ==? [tempdir </> "no-such-subdir"]
                      ]
  return ()

-- | Tests the JSON serialisation for 'InputOpCode'.
prop_InputOpCode :: MetaOpCode -> Int -> Property
prop_InputOpCode meta i =
  conjoin [ readJSON (showJSON valid)   ==? Text.JSON.Ok valid
          , readJSON (showJSON invalid) ==? Text.JSON.Ok invalid
          ]
    where valid = ValidOpCode meta
          invalid = InvalidOpCode (showJSON i)

-- | Tests 'extractOpSummary'.
prop_extractOpSummary :: MetaOpCode -> Int -> Property
prop_extractOpSummary meta i =
  conjoin [ counterexample "valid opcode" $
            extractOpSummary (ValidOpCode meta)      ==? summary
          , counterexample "invalid opcode, correct object" $
            extractOpSummary (InvalidOpCode jsobj)   ==? summary
          , counterexample "invalid opcode, empty object" $
            extractOpSummary (InvalidOpCode emptyo)  ==? invalid
          , counterexample "invalid opcode, object with invalid OP_ID" $
            extractOpSummary (InvalidOpCode invobj)  ==? invalid
          , counterexample "invalid opcode, not jsobject" $
            extractOpSummary (InvalidOpCode jsinval) ==? invalid
          ]
    where summary = opSummary (metaOpCode meta)
          jsobj = showJSON $ toJSObject [("OP_ID",
                                          showJSON ("OP_" ++ summary))]
          emptyo = showJSON $ toJSObject ([]::[(String, JSValue)])
          invobj = showJSON $ toJSObject [("OP_ID", showJSON False)]
          jsinval = showJSON i
          invalid = "INVALID_OP"

testSuite "JQueue"
            [ 'case_JobPriorityDef
            , 'prop_JobPriority
            , 'case_JobStatusDef
            , 'prop_JobStatus
            , 'case_JobStatusPri_py_equiv
            , 'prop_ListJobIDs
            , 'prop_LoadJobs
            , 'prop_DetermineDirs
            , 'prop_InputOpCode
            , 'prop_extractOpSummary
            ]

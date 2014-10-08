{-# LANGUAGE TupleSections #-}
{-| Ad-hoc rate limiting for the JQScheduler based on reason trails.

-}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.JQScheduler.ReasonRateLimiting
  ( reasonRateLimit
  -- * For testing only
  , parseReasonRateLimit
  , countMapFromJob
  , slotMapFromJobs
  ) where

import Data.List
import Data.Maybe
import qualified Data.Map as Map

import Ganeti.Lens hiding (chosen)
import Ganeti.JQScheduler.Types
import Ganeti.JQueue (QueuedJob(..))
import Ganeti.JQueue.Lens
import Ganeti.OpCodes.Lens
import Ganeti.SlotMap
import Ganeti.Utils



-- | Ad-hoc rate limiting buckets are identified by the /combination/
-- `REASONSTRING:n`, so "mybucket:3" and "mybucket:4" are /different/ buckets.
type AdHocReasonKey = String


-- | Parses an ad-hoc rate limit from a reason trail, as defined under
-- "Ad-Hoc Rate Limiting" in `doc/design-optables.rst`.
--
-- The parse succeeds only on reasons of form `rate-limit:n:REASONSTRING`
-- where `n` is a positive integer and `REASONSTRING` is an arbitrary
-- string (may include spaces).
parseReasonRateLimit :: (Monad m) => String -> m (String, Int)
parseReasonRateLimit reason = case sepSplit ':' reason of
  "rate-limit":nStr:rest
    | Just n <- readMaybe nStr
    , n > 0 -> return (intercalate ":" (nStr:rest), n)
  _ -> fail $ "'" ++ reason ++ "' is not a valid ad-hoc rate limit reason"


-- | Computes the bucket slots required by a job, also extracting how many
-- slots are available from the reason rate limits in the job reason trails.
--
-- A job can have multiple `OpCode`s, and the `ReasonTrail`s
-- can be different for each `OpCode`. The `OpCode`s of a job are
-- run sequentially, so a job can only take 1 slot.
-- Thus a job takes part in a set of buckets, requiring 1 slot in
-- each of them.
labelCountMapFromJob :: QueuedJob -> CountMap (String, Int)
labelCountMapFromJob job =
  let reasonsStrings =
        job ^.. qjOpsL . traverse . qoInputL . validOpCodeL
                . metaParamsL . opReasonL . traverse . _2

      buckets = ordNub . mapMaybe parseReasonRateLimit $ reasonsStrings

  -- Buckets are already unique from `ordNub`.
  in Map.fromList $ map (, 1) buckets


-- | Computes the bucket slots required by a job.
countMapFromJob :: QueuedJob -> CountMap AdHocReasonKey
countMapFromJob = Map.mapKeys (\(str, n) -> str ++ ":" ++ show n)
                    . labelCountMapFromJob


-- | Map of how many slots are in use for a given bucket, for a list of jobs.
-- The slot limits are taken from the ad-hoc reason rate limiting strings.
slotMapFromJobs :: [QueuedJob] -> SlotMap AdHocReasonKey
slotMapFromJobs jobs =
  Map.mapKeys (\(str, n) -> str ++ ":" ++ show n)
    . Map.mapWithKey (\(_str, limit) occup -> Slot occup limit)
    . Map.unionsWith (+) . map labelCountMapFromJob
    $ jobs


-- | Like `slotMapFromJobs`, but setting all occupation counts to 0.
-- Useful to find what the bucket limits of a set of jobs are.
unoccupiedSlotMapFromJobs :: [QueuedJob] -> SlotMap AdHocReasonKey
unoccupiedSlotMapFromJobs = Map.map (\s -> s{ slotOccupied = 0 })
                              . slotMapFromJobs


-- | Implements ad-hoc rate limiting using the reason trail as specified
-- in `doc/design-optables.rst`.
--
-- Reasons of form `rate-limit:n:REASONSTRING` define buckets that limit
-- how many jobs with that reason can be running at the same time to
-- a positive integer n of available slots.
--
-- The used buckets map is currently not cached across `selectJobsToRun`
-- invocations because the number of running jobs is typically small
-- (< 100).
reasonRateLimit :: Queue -> [JobWithStat] -> [JobWithStat]
reasonRateLimit queue jobs =
  let -- For the purpose of rate limiting, manipulated jobs count as running.
      running    = map jJob $ qRunning queue ++ qManipulated queue
      candidates = map jJob jobs

      -- Reason rate limiting slot map of the jobs running in the queue.
      -- All jobs determine the reason buckets, but only running jobs count
      -- to the initial limits.
      initSlotMap = unoccupiedSlotMapFromJobs (running ++ candidates)
                    `occupySlots`
                    toCountMap (slotMapFromJobs running)

      -- A job can be run (fits) if all buckets it takes part in have
      -- a free slot. If yes, accept the job and update the slotMap.
      -- Note: If the slotMap is overfull in some slots, but the job
      -- doesn't take part in any of those, it is to be accepted.
      accumFittingJobs slotMap job =
        let jobBuckets = countMapFromJob (jJob job)
        in if slotMap `hasSlotsFor` jobBuckets
          then (slotMap `occupySlots` jobBuckets, Just job) -- job fits
          else (slotMap, Nothing)                           -- job doesn't fit

  in catMaybes . snd . mapAccumL accumFittingJobs initSlotMap $ jobs

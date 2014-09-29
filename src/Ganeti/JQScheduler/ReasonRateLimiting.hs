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
  , RateLimitBucket(bucketCount)
  , parseRateLimit
  , SlotMap
  , isOverfull
  , joinSlotMap
  , slotMapFromJob
  , hasSlotsFor
  ) where

import Data.List
import Data.Maybe
import Data.Map (Map)
import qualified Data.Map as Map

import Ganeti.Lens hiding (chosen)
import Ganeti.JQScheduler.Types
import Ganeti.JQueue (QueuedJob)
import Ganeti.JQueue.Lens
import Ganeti.OpCodes.Lens
import Ganeti.Utils

-- | Ad-hoc rate limiting buckets are identified by the /combination/
-- `(BUCKETLABEL, n)`, so `("mybucket", 3)` and `("mybucket", 4)` are
-- /different/ buckets).
data RateLimitBucket = RateLimitBucket
  { _bucketLabel :: String
  , bucketCount :: Int
  } deriving (Eq, Ord, Show)


-- | Parses an ad-hoc rate limit from a reason trail, as defined under
-- "Ad-Hoc Rate Limiting" in `doc/design-optables.rst`.
--
-- The parse succeeds only on reasons of form `rate-limit:n:BUCKETLABEL`
-- where `n` is a positive integer and `BUCKETLABEL` is an arbitrary
-- string (may include spaces).
parseRateLimit :: (Monad m) => String -> m RateLimitBucket
parseRateLimit reason = case sepSplit ':' reason of
  "rate-limit":nStr:rest
    | Just n <- readMaybe nStr
    , n > 0 -> return $ RateLimitBucket (intercalate ":" rest) n
  _ -> fail $ "'" ++ reason ++ "' is not a valid ad-hoc rate limit reason"


-- | A set of buckets and how many slots are (to be) taken per bucket.
--
-- Some buckets can be overfull (more slots taken than available.)
type SlotMap = Map RateLimitBucket Int


-- | Whether any more slots are taken than available.
isOverfull :: SlotMap -> Bool
isOverfull m = or [ j > bucketCount b | (b, j) <- Map.toList m ]


-- | Combine two `SlotMap`s by adding the occupied bucket slots.
joinSlotMap :: SlotMap -> SlotMap -> SlotMap
joinSlotMap = Map.unionWith (+)


-- | Computes the bucket slots required by a job.
--
-- A job can have multiple `OpCode`s, and the `ReasonTrail`s
-- can be different for each `OpCode`. The `OpCode`s of a job are
-- run sequentially, so a job can only take 1 slot.
-- Thus a job takes part in a set of buckets, requiring 1 slot in
-- each of them.
slotMapFromJob :: QueuedJob -> SlotMap
slotMapFromJob job =
  let reasonsStrings =
        job ^.. qjOpsL . traverse . qoInputL . validOpCodeL
                . metaParamsL . opReasonL . traverse . _2

      buckets = ordNub . mapMaybe parseRateLimit $ reasonsStrings

  in Map.fromList $ map (, 1) buckets  -- buckets are already unique


-- | Whether the first `SlotMap` has enough slots free to accomodate the
-- bucket slots of the second `SlotMap`.
hasSlotsFor :: SlotMap -> SlotMap -> Bool
slotMap `hasSlotsFor` newSlots =
  let relevantSlots = slotMap `Map.intersection` newSlots
  in not $ isOverfull (newSlots `joinSlotMap` relevantSlots)


--- | Map of how many slots are in use for a given bucket,
--- for the jobs that are currently running in the queue.
--- Both `qRunning` and `qManipulated` count to the rate limit.
queueSlotMap :: Queue -> SlotMap
queueSlotMap queue = Map.unionsWith (+) . map (slotMapFromJob . jJob)
                       $ qRunning queue ++ qManipulated queue


-- | Implements ad-hoc rate limiting using the reason trail as specified
-- in `doc/design-optables.rst`.
--
-- Reasons of form `rate-limit:n:BUCKETLABEL` define buckets that limit
-- how many jobs with that reason can be running at the same time to
-- a positive integer n of available slots.
--
-- The used buckets map is currently not cached across `selectJobsToRun`
-- invocations because the number of running jobs is typically small
-- (< 100).
reasonRateLimit :: Queue -> [JobWithStat] -> [JobWithStat]
reasonRateLimit queue =
  let initSlotMap = queueSlotMap queue

      -- A job can be run (fits) if all buckets it takes part in have
      -- a free slot. If yes, accept the job and update the slotMap.
      -- Note: If the slotMap is overfull in some slots, but the job
      -- doesn't take part in any of those, it is to be accepted.
      accumFittingJobs slotMap job =
        let jobSlots = slotMapFromJob (jJob job)
        in if slotMap `hasSlotsFor` jobSlots
          then (jobSlots `joinSlotMap` slotMap, Just job) -- job fits
          else (slotMap, Nothing)                  -- job doesn't fit

  in catMaybes . snd . mapAccumL accumFittingJobs initSlotMap

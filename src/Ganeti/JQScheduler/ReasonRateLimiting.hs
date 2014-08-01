{-# LANGUAGE TupleSections #-}
{-| Ad-hoc rate limiting for the JQScheduler based on reason trails.

-}

{-

Copyright (C) 2014 Google Inc.

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
slotMapFromJob :: JobWithStat -> SlotMap
slotMapFromJob job =
  let reasonsStrings =
        job ^.. jJobL . qjOpsL . traverse . qoInputL . validOpCodeL
                . metaParamsL . opReasonL . traverse . _2

      buckets = ordNub . mapMaybe parseRateLimit $ reasonsStrings

  in Map.fromList $ map (, 1) buckets  -- buckets are already unique


-- | Whether the first `SlotMap` has enough slots free to accomodate the
-- bucket slots of the second `SlotMap`.
hasSlotsFor :: SlotMap -> SlotMap -> Bool
slotMap `hasSlotsFor` newSlots =
  let relevantSlots = slotMap `Map.intersection` newSlots
  in not $ isOverfull (newSlots `joinSlotMap` relevantSlots)


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
  let
      -- Map of how many slots are in use for a given bucket,
      -- for the jobs that are currently running.
      -- Both `qRunning` and `qManipulated` count to the rate limit.
      initSlotMap :: SlotMap
      initSlotMap = Map.unionsWith (+) . map slotMapFromJob $
                      qRunning queue ++ qManipulated queue

      -- A job can be run (fits) if all buckets it takes part in have
      -- a free slot. If yes, accept the job and update the slotMap.
      -- Note: If the slotMap is overfull in some slots, but the job
      -- doesn't take part in any of those, it is to be accepted.
      accumFittingJobs slotMap job =
        let jobSlots = slotMapFromJob job
        in if slotMap `hasSlotsFor` jobSlots
          then (jobSlots `joinSlotMap` slotMap, Just job) -- job fits
          else (slotMap, Nothing)                  -- job doesn't fit

  in catMaybes . snd . mapAccumL accumFittingJobs initSlotMap

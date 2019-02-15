{-# LANGUAGE TupleSections, NamedFieldPuns, ScopedTypeVariables, RankNTypes,
             GADTs #-}
{-| Filtering of jobs for the Ganeti job queue.

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

module Ganeti.JQScheduler.Filtering
  ( applyingFilter
  , jobFiltering
  -- * For testing only
  , matchPredicate
  , matches
  ) where

import qualified Data.ByteString as BS
import Data.List
import Data.Maybe
import qualified Data.Map as Map
import Data.Set (Set)
import qualified Data.Set as Set
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Lens hiding (chosen)
import Ganeti.JQScheduler.Types
import Ganeti.JQueue (QueuedJob(..))
import Ganeti.JQueue.Lens
import Ganeti.JSON (nestedAccessByKeyDotted)
import Ganeti.Objects (FilterRule(..), FilterAction(..), FilterPredicate(..),
                       filterRuleOrder)
import Ganeti.OpCodes (OpCode)
import Ganeti.OpCodes.Lens
import Ganeti.Query.Language
import Ganeti.Query.Filter (evaluateFilterM, evaluateFilterJSON, Comparator,
                            FilterOp(..), toCompFun)
import Ganeti.SlotMap
import Ganeti.Types (JobId(..), ReasonElem)


-- | Accesses a field of the JSON representation of an `OpCode` using a dotted
-- accessor (like @"a.b.c"@).
accessOpCodeField :: OpCode -> String -> ErrorResult J.JSValue
accessOpCodeField opc s = case nestedAccessByKeyDotted s (J.showJSON opc) of
  J.Ok x    -> Ok x
  J.Error e -> Bad . ParameterError $ e


-- | All `OpCode`s of a job.
opCodesOf :: QueuedJob -> [OpCode]
opCodesOf job =
  job ^.. qjOpsL . traverse . qoInputL . validOpCodeL . metaOpCodeL


-- | All `ReasonElem`s of a job.
reasonsOf :: QueuedJob -> [ReasonElem]
reasonsOf job = job ^.. qjOpsL . traverse . qoInputL . validOpCodeL
                        . metaParamsL . opReasonL . traverse


-- | Like `evaluateFilterM`, but allowing only `Comparator` operations;
-- all other filter language operations are evaluated as `False`.
--
-- The passed function is supposed to return `Just True/False` depending
-- on whether the comparing operation succeeds or not, and `Nothing` if
-- the comparison itself is invalid (e.g. comparing to a field that doesn't
-- exist).
evaluateFilterComparator :: (Ord field)
                         => Filter field
                         -> (Comparator -> field -> FilterValue -> Maybe Bool)
                         -> Bool
evaluateFilterComparator fil opFun =
  fromMaybe False $
    evaluateFilterM
      (\filterOp -> case filterOp of
         Comp cmp -> opFun (toCompFun cmp)
         _        -> \_ _ -> Nothing -- non-comparisons (become False)
      )
      fil


-- | Whether a `FilterPredicate` is true for a job.
matchPredicate :: QueuedJob
               -> JobId            -- ^ the watermark to compare against
                                   --   if the predicate references it
               -> FilterPredicate
               -> Bool
matchPredicate job watermark predicate = case predicate of

  FPJobId fil ->
    let jid    = qjId job
        jidInt = fromIntegral (fromJobId jid)

    in evaluateFilterComparator fil $ \comp field val -> case field of
         "id" -> case val of
           NumericValue i           -> Just $ jidInt `comp` i
           QuotedString "watermark" -> Just $ jid `comp` watermark
           QuotedString _           -> Nothing
         _    -> Nothing

  FPOpCode fil ->
    let opMatches opc = genericResult (const False) id $ do
          jsonFilter <- traverse (accessOpCodeField opc) fil
          evaluateFilterJSON jsonFilter
    in any opMatches (opCodesOf job)

  FPReason fil ->
    let reasonMatches (source, reason, timestamp) =
          evaluateFilterComparator fil $ \comp field val -> case field of
            "source"    -> Just $ QuotedString source `comp` val
            "reason"    -> Just $ QuotedString reason `comp` val
            "timestamp" -> Just $ NumericValue timestamp `comp` val
            _           -> Nothing
    in any reasonMatches (reasonsOf job)


-- | Whether all predicates of the filter rule are true for the job.
matches :: QueuedJob -> FilterRule -> Bool
matches job FilterRule{ frPredicates, frWatermark } =
  all (matchPredicate job frWatermark) frPredicates


-- | Filters need to be processed in the order as given by the spec;
-- see `filterRuleOrder`.
orderFilters :: Set FilterRule -> [FilterRule]
orderFilters = sortBy filterRuleOrder . Set.toList


-- | Finds the first filter whose predicates all match the job and whose
-- action is not `Continue`. This is the /applying/ filter.
applyingFilter :: Set FilterRule -> QueuedJob -> Maybe FilterRule
applyingFilter filters job =
  -- Skip over all `Continue`s, to the first filter that matches.
  find ((Continue /=) . frAction)
    . filter (matches job)
    . orderFilters
    $ filters


-- | SlotMap for filter rule rate limiting, having `FilterRule` UUIDs as keys.
type RateLimitSlotMap = SlotMap BS.ByteString
-- We would prefer FilterRule here but that has no Ord instance (yet).


-- | State to be accumulated while traversing filters.
data FilterChainState = FilterChainState
  { rateLimitSlotMap :: RateLimitSlotMap -- ^ counts
  } deriving (Eq, Ord, Show)


-- | Update a `FilterChainState` if the given `CountMap` fits into its
-- filtering SlotsMap.
tryFitSlots :: FilterChainState
            -> CountMap BS.ByteString
            -> Maybe FilterChainState
tryFitSlots st@FilterChainState{ rateLimitSlotMap = slotMap } countMap =
  if slotMap `hasSlotsFor` countMap
    then Just st{ rateLimitSlotMap = slotMap `occupySlots` countMap }
    else Nothing


-- | For a given job queue and set of filters, calculates how many rate
-- limiting filter slots are available and how many are taken by running jobs
-- in the queue.
queueRateLimitSlotMap :: Queue -> Set FilterRule -> RateLimitSlotMap
queueRateLimitSlotMap queue filters =
  let -- Rate limiting slots for each filter, with 0 occupied count each
      -- (limits only).
      emptyFilterSlots =
        Map.fromList
          [ (uuid, Slot 0 n)
          | FilterRule{ frUuid   = uuid
                      , frAction = RateLimit n } <- Set.toList filters ]

      -- How many rate limiting slots are taken by the jobs currently running
      -- in the queue jobs (counts only).
      -- A job takes a slot of a RateLimit filter if that filter is the first
      -- one that matches for the job.
      runningJobSlots = Map.fromListWith (+)
        [ (frUuid, 1) | Just FilterRule{ frUuid, frAction = RateLimit _ } <-
                          map (applyingFilter filters . jJob)
                            $ qRunning queue ++ qManipulated queue ]

  in -- Fill limits from above with counts from above.
     emptyFilterSlots `occupySlots` runningJobSlots


-- | Implements job filtering as specified in `doc/design-optables.rst`.
--
-- Importantly, the filter that *applies* is the first one of which all
-- predicates match; this is implemented in `applyingFilter`.
--
-- The initial `FilterChainState` is currently not cached across
-- `selectJobsToRun` invocations because the number of running jobs is
-- typically small (< 100).
jobFiltering :: Queue -> Set FilterRule -> [JobWithStat] -> [JobWithStat]
jobFiltering queue filters =
  let
      processFilters :: FilterChainState
                     -> JobWithStat
                     -> (FilterChainState, Maybe JobWithStat)
      processFilters state job =
        case applyingFilter filters (jJob job) of
          Nothing -> (state, Just job) -- no filter applies, accept job
          Just FilterRule{ frUuid, frAction } -> case frAction of
            Accept      -> (state, Just job)
            Continue    -> (state, Just job)
            Pause       -> (state, Nothing)
            Reject      -> (state, Nothing)
            RateLimit _ -> -- A matching job takes 1 slot.
                           let jobSlots = Map.fromList [(frUuid, 1)]
                           in case tryFitSlots state jobSlots of
                                Nothing     -> (state,  Nothing)
                                Just state' -> (state', Just job)

  in catMaybes . snd . mapAccumL processFilters FilterChainState
       { rateLimitSlotMap = queueRateLimitSlotMap queue filters
       }

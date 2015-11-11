{-# LANGUAGE TemplateHaskell, ScopedTypeVariables, NamedFieldPuns #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for the job scheduler.

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

module Test.Ganeti.JQScheduler (testJQScheduler) where

import Control.Applicative
import Control.Lens ((&), (.~), _2)
import qualified Data.ByteString.UTF8 as UTF8
import Data.List (inits)
import Data.Maybe
import qualified Data.Map as Map
import Data.Set (Set, difference)
import qualified Data.Set as Set
import Data.Traversable (traverse)
import Text.JSON (JSValue(..))
import Test.HUnit
import Test.QuickCheck

import Test.Ganeti.JQueue.Objects (genQueuedOpCode, genJobId, justNoTs)
import Test.Ganeti.SlotMap (genTestKey, overfullKeys)
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper
import Test.Ganeti.Types ()

import Ganeti.JQScheduler.Filtering
import Ganeti.JQScheduler.ReasonRateLimiting
import Ganeti.JQScheduler.Types
import Ganeti.JQueue.Lens
import Ganeti.JQueue.Objects
import Ganeti.Objects (FilterRule(..), FilterPredicate(..), FilterAction(..),
                       filterRuleOrder)
import Ganeti.OpCodes
import Ganeti.OpCodes.Lens
import Ganeti.Query.Language (Filter(..), FilterValue(..))
import Ganeti.SlotMap
import Ganeti.Types
import Ganeti.Utils (isSubsequenceOf, newUUID)

{-# ANN module "HLint: ignore Use camelCase" #-}


genRateLimitReason :: Gen String
genRateLimitReason = do
  Slot{ slotLimit = n } <- arbitrary
  l <- genTestKey
  return $ "rate-limit:" ++ show n ++ ":" ++ l


instance Arbitrary QueuedJob where
  arbitrary = do
    -- For our scheduler testing purposes here, we only care about
    -- opcodes, job ID and reason rate limits.
    jid <- genJobId

    ops <- resize 5 . listOf1 $ do
      o <- genQueuedOpCode
      -- Put some rate limits into the OpCode.
      limitString <- genRateLimitReason
      return $
        o & qoInputL . validOpCodeL . metaParamsL . opReasonL . traverse . _2
          .~ limitString

    return $ QueuedJob jid ops justNoTs justNoTs justNoTs Nothing Nothing


instance Arbitrary JobWithStat where
  arbitrary = nullJobWithStat <$> arbitrary
  shrink job = [ job { jJob = x } | x <- shrink (jJob job) ]


instance Arbitrary Queue where
  arbitrary = do

    let genJobsUniqueJIDs :: [JobWithStat] -> Gen [JobWithStat]
        genJobsUniqueJIDs = listOfUniqueBy arbitrary (qjId . jJob)

    queued  <- genJobsUniqueJIDs []
    running <- genJobsUniqueJIDs queued
    manip   <- genJobsUniqueJIDs (queued ++ running)

    return $ Queue queued running manip
  shrink q =
    [ q { qEnqueued = x }    | x <- shrink (qEnqueued q) ] ++
    [ q { qRunning = x }     | x <- shrink (qRunning q) ] ++
    [ q { qManipulated = x } | x <- shrink (qManipulated q) ]


-- * Test cases

-- | Tests rate limit reason trail parsing.
case_parseReasonRateLimit :: Assertion
case_parseReasonRateLimit = do

  assertBool "default case" $
    let a = parseReasonRateLimit "rate-limit:20:my label"
        b = parseReasonRateLimit "rate-limit:21:my label"
    in and
         [ a == Just ("20:my label", 20)
         , b == Just ("21:my label", 21)
         ]

  assertEqual "be picky about whitespace"
    Nothing
    (parseReasonRateLimit " rate-limit:20:my label")


-- | Tests that "rateLimit:n:..." and "rateLimit:m:..." become different
-- rate limiting buckets.
prop_slotMapFromJob_conflicting_buckets :: Property
prop_slotMapFromJob_conflicting_buckets = do

  let sameBucketReasonStringGen :: Gen (String, String)
      sameBucketReasonStringGen = do
        (Positive (n :: Int), Positive (m :: Int)) <- arbitrary
        l <- genPrintableAsciiString
        return ( "rate-limit:" ++ show n ++ ":" ++ l
               , "rate-limit:" ++ show m ++ ":" ++ l )

  forAll sameBucketReasonStringGen $ \(s1, s2) ->
    (s1 /= s2) ==> do
      (lab1, lim1) <- parseReasonRateLimit s1
      (lab2, _   ) <- parseReasonRateLimit s2
      let sm = Map.fromList [(lab1, Slot 1 lim1)]
          cm = Map.fromList [(lab2, 1)]
       in return $
            (sm `occupySlots` cm) ==? Map.fromList [ (lab1, Slot 1 lim1)
                                                   , (lab2, Slot 1 0)
                                                   ] :: Gen Property


-- | Tests some basic cases for reason rate limiting.
case_reasonRateLimit :: Assertion
case_reasonRateLimit = do

  let mkJobWithReason jobNum reasonTrail = do
        opc <- genSample genQueuedOpCode
        jid <- makeJobId jobNum
        let opc' = opc & (qoInputL . validOpCodeL . metaParamsL . opReasonL)
                       .~ reasonTrail
        return . nullJobWithStat
          $ QueuedJob
              { qjId = jid
              , qjOps = [opc']
              , qjReceivedTimestamp = Nothing
              , qjStartTimestamp = Nothing
              , qjEndTimestamp = Nothing
              , qjLivelock = Nothing
              , qjProcessId = Nothing
              }

  -- 3 jobs, limited to 2 of them running.
  j1 <- mkJobWithReason 1 [("source1", "rate-limit:2:hello", 0)]
  j2 <- mkJobWithReason 2 [("source1", "rate-limit:2:hello", 0)]
  j3 <- mkJobWithReason 3 [("source1", "rate-limit:2:hello", 0)]

  assertEqual "[j1] should not be rate-limited"
    [j1]
    (reasonRateLimit (Queue [j1] [] []) [j1])

  assertEqual "[j1, j2] should not be rate-limited"
    [j1, j2]
    (reasonRateLimit (Queue [j1, j2] [] []) [j1, j2])

  assertEqual "j3 should be rate-limited 1"
    [j1, j2]
    (reasonRateLimit (Queue [j1, j2, j3] [] []) [j1, j2, j3])

  assertEqual "j3 should be rate-limited 2"
    [j2]
    (reasonRateLimit (Queue [j2, j3] [j1] []) [j2, j3])

  assertEqual "j3 should be rate-limited 3"
    []
    (reasonRateLimit (Queue [j3] [j1] [j2]) [j3])


-- | Tests the specified properties of `reasonRateLimit`, as defined in
-- `doc/design-optables.rst`.
prop_reasonRateLimit :: Property
prop_reasonRateLimit =
  forAllShrink arbitrary shrink $ \q ->

    let slotMapFromJobWithStat = slotMapFromJobs . map jJob

        enqueued = qEnqueued q

        toRun    = reasonRateLimit q enqueued

        oldSlots         = slotMapFromJobWithStat (qRunning q)
        newSlots         = slotMapFromJobWithStat (qRunning q ++ toRun)
        -- What would happen without rate limiting.
        newSlotsNoLimits = slotMapFromJobWithStat (qRunning q ++ enqueued)

    in -- Ensure it's unlikely that jobs are all in different buckets.
       cover
         (any ((> 1) . slotOccupied) . Map.elems $ newSlotsNoLimits)
         50
         "some jobs have the same rate-limit bucket"

       -- Ensure it's likely that rate limiting has any effect.
       . cover
           (overfullKeys newSlotsNoLimits
              `difference` overfullKeys oldSlots /= Set.empty)
           50
           "queued jobs cannot be started because of rate limiting"

       $ conjoin
           [ counterexample "scheduled jobs must be subsequence" $
               toRun `isSubsequenceOf` enqueued

           -- This is the key property:
           , counterexample "no job may exceed its bucket limits, except from\
                            \ jobs that were already running with exceeded\
                            \ limits; those must not increase" $
               conjoin
                 [ if occup <= limit
                     -- Within limits, all fine.
                     then passTest
                     -- Bucket exceeds limits - it must have exceeded them
                     -- in the initial running list already, with the same
                     -- slot count.
                     else Map.lookup k oldSlots ==? Just slot
                 | (k, slot@(Slot occup limit)) <- Map.toList newSlots ]
           ]

-- | Tests that filter rule ordering is determined (solely) by priority,
-- watermark and UUID, as defined in `doc/design-optables.rst`.
prop_filterRuleOrder :: Property
prop_filterRuleOrder = property $ do
  a <- arbitrary
  b <- arbitrary `suchThat` ((frUuid a /=) . frUuid)
  return $ filterRuleOrder a b ==? (frPriority a, frWatermark a, frUuid a)
                                   `compare`
                                   (frPriority b, frWatermark b, frUuid b)


-- | Tests common inputs for `matchPredicate`, especially the predicates
-- and fields available to them as defined in the spec.
case_matchPredicate :: Assertion
case_matchPredicate = do

  jid1 <- makeJobId 1
  clusterName <- mkNonEmpty "cluster1"

  let job =
        QueuedJob
          { qjId = jid1
          , qjOps =
              [ QueuedOpCode
                  { qoInput = ValidOpCode MetaOpCode
                      { metaParams = CommonOpParams
                          { opDryRun = Nothing
                          , opDebugLevel = Nothing
                          , opPriority = OpPrioHigh
                          , opDepends = Just []
                          , opComment = Nothing
                          , opReason = [("source1", "reason1", 1234)]
                          }
                      , metaOpCode = OpClusterRename
                          { opName = clusterName
                          }
                      }
                  , qoStatus = OP_STATUS_QUEUED
                  , qoResult = JSNull
                  , qoLog = []
                  , qoPriority = -1
                  , qoStartTimestamp = Nothing
                  , qoExecTimestamp = Nothing
                  , qoEndTimestamp = Nothing
                  }
              ]
          , qjReceivedTimestamp = Nothing
          , qjStartTimestamp = Nothing
          , qjEndTimestamp = Nothing
          , qjLivelock = Nothing
          , qjProcessId = Nothing
          }

  let watermark = jid1

      check = matchPredicate job watermark

  -- jobid filters

  assertEqual "matching jobid filter"
    True
    . check $ FPJobId (EQFilter "id" (NumericValue 1))

  assertEqual "non-matching jobid filter"
    False
    . check $ FPJobId (EQFilter "id" (NumericValue 2))

  assertEqual "non-matching jobid filter (string passed)"
    False
    . check $ FPJobId (EQFilter "id" (QuotedString "1"))

  -- jobid filters: watermarks

  assertEqual "matching jobid watermark filter"
    True
    . check $ FPJobId (EQFilter "id" (QuotedString "watermark"))

  -- opcode filters

  assertEqual "matching opcode filter (type of opcode)"
    True
    . check $ FPOpCode (EQFilter "OP_ID" (QuotedString "OP_CLUSTER_RENAME"))

  assertEqual "non-matching opcode filter (type of opcode)"
    False
    . check $ FPOpCode (EQFilter "OP_ID" (QuotedString "OP_INSTANCE_CREATE"))

  assertEqual "matching opcode filter (nested access)"
    True
    . check $ FPOpCode (EQFilter "name" (QuotedString "cluster1"))

  assertEqual "non-matching opcode filter (nonexistent nested access)"
    False
    . check $ FPOpCode (EQFilter "something" (QuotedString "cluster1"))

  -- reason filters

  assertEqual "matching reason filter (reason field)"
    True
    . check $ FPReason (EQFilter "reason" (QuotedString "reason1"))

  assertEqual "non-matching reason filter (reason field)"
    False
    . check $ FPReason (EQFilter "reason" (QuotedString "reasonGarbage"))

  assertEqual "matching reason filter (source field)"
    True
    . check $ FPReason (EQFilter "source" (QuotedString "source1"))

  assertEqual "matching reason filter (timestamp field)"
    True
    . check $ FPReason (EQFilter "timestamp" (NumericValue 1234))

  assertEqual "non-matching reason filter (nonexistent field)"
    False
    . check $ FPReason (EQFilter "something" (QuotedString ""))


-- | Tests that jobs selected by `applyingFilter` actually match
-- and have an effect (are not CONTINUE filters).
prop_applyingFilter :: Property
prop_applyingFilter =
  forAllShrink arbitrary shrink $ \(job, filters) ->

    let applying = applyingFilter (Set.fromList filters) job

    in isJust applying ==> case applying of
         Just f  -> job `matches` f && frAction f /= Continue
         Nothing -> True


case_jobFiltering :: Assertion
case_jobFiltering = do

  clusterName <- mkNonEmpty "cluster1"
  jid1 <- makeJobId 1
  jid2 <- makeJobId 2
  jid3 <- makeJobId 3
  jid4 <- makeJobId 4
  unsetPrio <- mkNonNegative 1234
  uuid1 <- fmap UTF8.fromString newUUID

  let j1 =
        nullJobWithStat QueuedJob
          { qjId = jid1
          , qjOps =
              [ QueuedOpCode
                  { qoInput = ValidOpCode MetaOpCode
                      { metaParams = CommonOpParams
                          { opDryRun = Nothing
                          , opDebugLevel = Nothing
                          , opPriority = OpPrioHigh
                          , opDepends = Just []
                          , opComment = Nothing
                          , opReason = [("source1", "reason1", 1234)]}
                          , metaOpCode = OpClusterRename
                              { opName = clusterName
                              }
                        }
                  , qoStatus = OP_STATUS_QUEUED
                  , qoResult = JSNull
                  , qoLog = []
                  , qoPriority = -1
                  , qoStartTimestamp = Nothing
                  , qoExecTimestamp = Nothing
                  , qoEndTimestamp = Nothing
                  }
              ]
          , qjReceivedTimestamp = Nothing
          , qjStartTimestamp = Nothing
          , qjEndTimestamp = Nothing
          , qjLivelock = Nothing
          , qjProcessId = Nothing
          }

      j2 = j1 & jJobL . qjIdL .~ jid2
      j3 = j1 & jJobL . qjIdL .~ jid3
      j4 = j1 & jJobL . qjIdL .~ jid4


      fr1 =
        FilterRule
          { frWatermark   = jid1
          , frPriority    = unsetPrio
          , frPredicates  = [FPJobId (EQFilter "id" (NumericValue 1))]
          , frAction      = Reject
          , frReasonTrail = []
          , frUuid        = uuid1
          }

      -- Gives the rule a new UUID.
      rule fr = do
        uuid <- fmap UTF8.fromString newUUID
        return fr{ frUuid = uuid }

      -- Helper to create filter chains: assigns the filters in the list
      -- increasing priorities, so that filters listed first are processed
      -- first.
      chain :: [FilterRule] -> Set FilterRule
      chain frs
        | any ((/= unsetPrio) . frPriority) frs =
            error "Filter was passed to `chain` that already had a priority."
        | otherwise =
            Set.fromList
              [ fr{ frPriority = prio }
              | (fr, Just prio) <- zip frs (map mkNonNegative [1..]) ]

  fr2 <- rule fr1{ frAction = Accept }
  fr3 <- rule fr1{ frAction = Pause }

  fr4 <- rule fr1{ frPredicates =
                     [FPJobId (GTFilter "id" (QuotedString "watermark"))]
                 }

  fr5 <- rule fr1{ frPredicates = [] }

  fr6 <- rule fr5{ frAction = Continue }
  fr7 <- rule fr6{ frAction = RateLimit 2 }

  fr8 <- rule fr4{ frAction = Continue, frWatermark = jid1 }
  fr9 <- rule fr8{ frAction = RateLimit 2 }

  assertEqual "j1 should be rejected (by fr1)"
    []
    (jobFiltering (Queue [j1] [] []) (chain [fr1]) [j1])

  assertEqual "j1 should be rejected (by fr1, it has priority)"
    []
    (jobFiltering (Queue [j1] [] []) (chain [fr1, fr2]) [j1])

  assertEqual "j1 should be accepted (by fr2, it has priority)"
    [j1]
    (jobFiltering (Queue [j1] [] []) (chain [fr2, fr1]) [j1])

  assertEqual "j1 should be paused (by fr3)"
    []
    (jobFiltering (Queue [j1] [] []) (chain [fr3]) [j1])

  assertEqual "j2 should be rejected (over watermark1)"
    [j1]
    (jobFiltering (Queue [j1, j2] [] []) (chain [fr4]) [j1, j2])

  assertEqual "all jobs should be rejected (since no predicates)"
    []
    (jobFiltering (Queue [j1, j2] [] []) (chain [fr5]) [j1, j2])

  assertEqual "j3 should be rate-limited"
    [j1, j2]
    (jobFiltering (Queue [j1, j2, j3] [] []) (chain [fr6, fr7]) [j1, j2, j3])

  assertEqual "j4 should be rate-limited"
    -- j1 doesn't apply to fr8/fr9 (since they match only watermark > jid1)
    -- so j1 gets scheduled
    [j1, j2, j3]
    (jobFiltering (Queue [j1, j2, j3, j4] [] []) (chain [fr8, fr9])
                  [j1, j2, j3, j4])


-- | Tests the specified properties of `jobFiltering`, as defined in
-- `doc/design-optables.rst`.
prop_jobFiltering :: Property
prop_jobFiltering =
  forAllShrink arbitrary shrink $ \q ->
    forAllShrink (resize 4 arbitrary) shrink $ \(NonEmpty filterList) ->

      let running  = qRunning q ++ qManipulated q
          enqueued = qEnqueued q

          filters = Set.fromList filterList

          toRun = jobFiltering q filters enqueued -- do the filtering

          -- Helpers

          -- Whether `fr` applies to more than `n` of the `jobs`
          -- (that is, more than allowed).
          exceeds :: Int -> FilterRule -> [JobWithStat] -> Bool
          exceeds n fr jobs =
            n < (length
                 . filter ((frUuid fr ==) . frUuid)
                 . mapMaybe (applyingFilter filters)
                 $ map jJob jobs)

          -- Helpers for ensuring sensible coverage.

          -- Makes sure that each action appears with some probability.
          actionName = head . words . show
          allActions = map actionName [ Accept, Continue, Pause, Reject
                                      , RateLimit 0 ]
          applyingActions = map (actionName . frAction)
                              . mapMaybe (applyingFilter filters)
                              $ map jJob enqueued
          perc = 4 -- percent; low because it's per action
          actionCovers =
            foldr (.) id
              [ stableCover (a `elem` applyingActions) perc ("is " ++ a)
              | a <- allActions ]

      -- `covers` should be after `==>` and before `conjoin` (see QuickCheck
      -- bugs 25 and 27).
      in (enqueued /= []) ==> actionCovers $ conjoin

           [ counterexample "scheduled jobs must be subsequence" $
               toRun `isSubsequenceOf` enqueued

           , counterexample "a reason for each job (not) being scheduled" .

               -- All enqueued jobs must have a reason why they were (not)
               -- scheduled, determined by the filter that applies.
               flip all enqueued $ \job ->
                 case applyingFilter filters (jJob job) of
                   -- If no filter matches, the job must run.
                   Nothing -> job `elem` toRun
                   Just fr@FilterRule{ frAction } -> case frAction of
                     -- ACCEPT filter permit the job immediately,
                     -- PAUSE/REJECT forbid running, CONTINUE filters cannot
                     -- be the output of `applyingFilter`, and
                     -- RATE_LIMIT filters have a more more complex property.
                     Accept   -> job `elem` toRun
                     Continue -> error "must not happen"
                     Pause    -> job `notElem` toRun
                     Reject   -> job `notElem` toRun
                     RateLimit n ->

                       let -- Jobs in queue before our job.
                           jobsBefore = takeWhile (/= job) enqueued

                       in if job `elem` toRun
                            -- If it got scheduled, the job and any job
                            -- before it doesn't overfill the rate limit.
                            then not . exceeds n fr $ running
                                                        ++ jobsBefore ++ [job]
                            -- If didn't get scheduled, then the rate limit
                            -- was already full before scheduling or the job
                            -- or one of the jobs before made it full.
                            else any (exceeds n fr . (running ++))
                                     (inits $ jobsBefore ++ [job])
                            -- The `inits` bit includes the [] and [...job]
                            -- cases.

           ]


testSuite "JQScheduler"
            [ 'case_parseReasonRateLimit
            , 'prop_slotMapFromJob_conflicting_buckets
            , 'case_reasonRateLimit
            , 'prop_reasonRateLimit
            , 'prop_filterRuleOrder
            , 'case_matchPredicate
            , 'prop_applyingFilter
            , 'case_jobFiltering
            , 'prop_jobFiltering
            ]

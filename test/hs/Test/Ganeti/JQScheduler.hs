{-# LANGUAGE TemplateHaskell, ScopedTypeVariables #-}
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
import Control.Monad
import Data.List (foldl')
import qualified Data.Map as Map
import Data.Maybe (isJust)
import Data.Map (member, union, keys)
import Data.Set (Set, size, difference)
import qualified Data.Set as Set
import Data.Traversable (traverse)
import Test.HUnit
import Test.QuickCheck

import Test.Ganeti.JQueue.Objects (genQueuedOpCode, genJobId, justNoTs)
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper
import Test.Ganeti.Types ()

import Ganeti.JQScheduler.ReasonRateLimiting
import Ganeti.JQScheduler.Types
import Ganeti.JQueue.Lens
import Ganeti.JQueue.Objects
import Ganeti.OpCodes.Lens

{-# ANN module "HLint: ignore Use camelCase" #-}


genRateLimitReason :: Gen String
genRateLimitReason = do
  n :: Int <- frequency [ (9, choose (1, 5))
                        , (1, choose (1, 100))
                        ]
  -- Limit ourselves to a small set of reason strings
  -- with high probability to increase the chance
  -- that `SlotMap`s actually have more than one slot taken.
  l <- frequency [ (9, elements ["a", "b", "c", "d", "e"])
                 , (1, genPrintableAsciiString)
                 ]
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
    let jobListGen = listOf arbitrary
    Queue <$> jobListGen <*> jobListGen <*> jobListGen
  shrink q =
    [ q { qEnqueued = x }    | x <- shrink (qEnqueued q) ] ++
    [ q { qRunning = x }     | x <- shrink (qRunning q) ] ++
    [ q { qManipulated = x } | x <- shrink (qManipulated q) ]


instance Arbitrary RateLimitBucket where
  arbitrary = genRateLimitReason >>= parseRateLimit


genSlotMap :: Gen SlotMap
genSlotMap = do
  Positive n <- arbitrary
  buckets <- vector n
  bucketsSlots <- forM buckets $ \b -> do
    taken <- choose (1, bucketCount b * 2)
    return (b, taken)
  let slotMap = Map.fromList bucketsSlots
  return slotMap


-- | Tells which buckets of a `SlotMap` are overfull.
overfullBuckets :: SlotMap -> Set RateLimitBucket
overfullBuckets sm =
  Set.fromList [ b | (b, x) <- Map.toList sm, x > bucketCount b ]


-- | A `SlotMap` observing its limits.
--
-- Invariant: The number of taken slots is <= the number of available
-- slots.
newtype FittingSlotMap = FittingSlotMap SlotMap deriving (Eq, Show)

instance Arbitrary FittingSlotMap where
  arbitrary = do
    -- Could use
    --   FittingSlotMap <$> arbitrary `suchThat` (not . isOverfull)
    -- instead but that Gen discards too much.
    n :: Int <- frequency [ (9, choose (1, 5))
                          , (1, choose (1, 100))
                          ]
    buckets <- vector n
    bucketsSlots <- forM buckets $ \b -> do
      x <- choose (0, bucketCount b)
      return (b, x)
    let slotMap = Map.fromList bucketsSlots
    when (isOverfull slotMap) $ error "BUG: FittingSlotMap Gen is wrong"
    return $ FittingSlotMap slotMap


-- * Test cases

-- | Tests rate limit reason trail parsing.
case_parseRateLimit :: Assertion
case_parseRateLimit = do

  assertBool "default case" $
    let b1 = parseRateLimit "rate-limit:20:my label"
        b2 = parseRateLimit "rate-limit:21:my label"
    in and
         [ isJust b1
         , (bucketCount <$> b1) == Just 20
         , isJust b2
         , (bucketCount <$> b2) == Just 21
         , b1 /= b2
         ]

  assertEqual "be picky about whitespace"
    Nothing
    (parseRateLimit " rate-limit:20:my label")


case_isOverfull :: Assertion
case_isOverfull = do
  b <- parseRateLimit "rate-limit:2:a"

  assertBool "overfull"
    . isOverfull $ Map.fromList [(b, 3)]

  assertBool "not overfull"
    . not . isOverfull $ Map.fromList [(b, 2)]

  assertBool "empty"
    . not . isOverfull $ Map.fromList []


case_joinSlotMap_examples :: Assertion
case_joinSlotMap_examples = do
  a <- parseRateLimit "rate-limit:2:a"
  b <- parseRateLimit "rate-limit:4:b"
  c <- parseRateLimit "rate-limit:8:c"

  let sm1 = Map.fromList [(a, 1), (b, 2)]
      sm2 = Map.fromList [(a, 1), (b, 1), (c, 5)]

  assertEqual "fitting joinslotmap"
    (sm1 `joinSlotMap` sm2)
    (Map.fromList [(a, 2), (b, 3), (c, 5)])


-- | Tests properties of merged sets of buckets.
prop_joinSlotMap :: Property
prop_joinSlotMap =
  forAll (arbitrary :: Gen (SlotMap, SlotMap)) $ \(sm1, sm2) ->
    let smU = sm1 `joinSlotMap` sm2
    in conjoin
         [ printTestCase "input buckets are preserved" $
             all (`member` smU) (keys $ union sm1 sm2)
         , printTestCase "all buckets must come from the input buckets" $
             all (`member` union sm1 sm2) (keys smU)
         ]


-- | Tests that "rateLimit:n:..." and "rateLimit:m:..." become different
-- buckets.
prop_slotMapFromJob_conflicting_buckets :: Property
prop_slotMapFromJob_conflicting_buckets = do

  let sameBucketLabelGen :: Gen (RateLimitBucket, RateLimitBucket)
      sameBucketLabelGen = do
        (Positive (n :: Int), Positive (m :: Int)) <- arbitrary
        l <- genPrintableAsciiString
        b1 <- parseRateLimit $ "rate-limit:" ++ show n ++ ":" ++ l
        b2 <- parseRateLimit $ "rate-limit:" ++ show m ++ ":" ++ l
        return (b1, b2)

  forAll sameBucketLabelGen $ \(b1, b2) ->
    (bucketCount b1 /= bucketCount b2) ==>
      let sm1 = Map.fromList [(b1, 1)]
          sm2 = Map.fromList [(b2, 1)]
       in (sm1 `joinSlotMap` sm2) ==? Map.fromList [(b1, 1), (b2, 1)]



-- | Tests for whether there's still space for a job given its rate
-- limits.
case_hasSlotsFor_examples :: Assertion
case_hasSlotsFor_examples = do
  a <- parseRateLimit "rate-limit:2:a"
  b <- parseRateLimit "rate-limit:4:b"
  c <- parseRateLimit "rate-limit:8:c"

  let sm = Map.fromList [(a, 1), (b, 2)]

  assertBool "fits" $
    sm `hasSlotsFor` Map.fromList [(a, 1), (b, 1)]

  assertBool "doesn't fit"
    . not $ sm `hasSlotsFor` Map.fromList [(a, 1), (b, 3)]

  let smOverfull = Map.fromList [(a, 1), (b, 2), (c, 10)]

  assertBool "fits (untouched buckets overfull)" $
    isOverfull smOverfull
      && smOverfull `hasSlotsFor` Map.fromList [(a, 1), (b, 1)]

  assertBool "empty fitting" $
    Map.empty `hasSlotsFor` Map.fromList [(a, 1), (b, 2)]

  assertBool "empty not fitting"
    . not $ Map.empty `hasSlotsFor` Map.fromList [(a, 1), (b, 100)]


-- | Tests properties of `hasSlotsFor` on `SlotMap`s that are known to
-- respect their limits.
prop_hasSlotsFor_fitting :: Property
prop_hasSlotsFor_fitting =
  forAll arbitrary $ \(FittingSlotMap sm1, FittingSlotMap sm2) ->
    conjoin
      [ sm1 `hasSlotsFor` sm2 ==? sm2 `hasSlotsFor` sm1
      , sm1 `hasSlotsFor` sm2 ==? not (isOverfull $ sm1 `joinSlotMap` sm2)
      ]


-- | Tests properties of `hasSlotsFor`, irrespective of whether the
-- input `SlotMap`s respect their limits or not.
prop_hasSlotsFor :: Property
prop_hasSlotsFor =
  let -- Generates `SlotMap`s for combining.
      genMaps = resize 10 $ do  -- We don't need very large SlotMaps.
        sm1 <- genSlotMap
        -- We need to make sm2 smaller to make `hasSlots` below more
        -- likely (otherwise the LHS of ==> is always false).
        sm2 <- sized $ \n -> resize (n `div` 3) genSlotMap
        -- We also want to test (sm1, sm1); we have to make it more
        -- likely for it to ever happen.
        frequency [ (1, return (sm1, sm1))
                  , (9, return (sm1, sm2)) ]

  in forAll genMaps $ \(sm1, sm2) ->
      let fits             = sm1 `hasSlotsFor` sm2
          smU              = sm1 `joinSlotMap` sm2
          oldOverfullBucks = overfullBuckets sm1
          newOverfullBucks = overfullBuckets smU
      in conjoin
           [ printTestCase "if there's enough extra space, then the new\
                            \ overfull buckets must be as before" $
             fits ==> (newOverfullBucks ==? oldOverfullBucks)
           -- Note that the other way around does not hold:
           --   (newOverfullBucks == oldOverfullBucks) ==> fits
           , printTestCase "joining SlotMaps must not change the number of\
                            \ overfull buckets (but may change their slot\
                            \ counts"
               . property $ size newOverfullBucks >= size oldOverfullBucks
           ]


-- | Tests the specified properties of `reasonRateLimit`, as defined in
-- `doc/design-optables.rst`.
prop_reasonRateLimit :: Property
prop_reasonRateLimit =
  forAllShrink arbitrary shrink $ \q ->

    let slotMapFromJobs = foldl' joinSlotMap Map.empty . map slotMapFromJob

        toRun = reasonRateLimit q (qEnqueued q)

        oldSlots         = slotMapFromJobs (qRunning q)
        newSlots         = slotMapFromJobs (qRunning q ++ toRun)
        -- What would happen without rate limiting.
        newSlotsNoLimits = slotMapFromJobs (qRunning q ++ qEnqueued q)

    in -- Ensure it's unlikely that jobs are all in differnt buckets.
       cover
         (any (> 1) . Map.elems $ newSlotsNoLimits)
         50
         "some jobs have the same rate-limit bucket"

       -- Ensure it's likely that rate limiting has any effect.
       . cover
           (overfullBuckets newSlotsNoLimits
              `difference` overfullBuckets oldSlots /= Set.empty)
           50
           "queued jobs cannot be started because of rate limiting"

       $ conjoin
           [ printTestCase "order must be preserved" $
               toRun ==? filter (`elem` toRun) (qEnqueued q)

           -- This is the key property:
           , printTestCase "no job may exceed its bucket limits, except from\
                            \ jobs that were already running with exceeded\
                            \ limits; those must not increase" $
               conjoin
                 [ if taken <= bucketCount bucket
                     -- Within limits, all fine.
                     then passTest
                     -- Bucket exceeds limits - it must have exceeded them
                     -- in the initial running list already, with the same
                     -- slot count.
                     else Map.lookup bucket oldSlots ==? Just taken
                 | (bucket, taken) <- Map.toList newSlots ]
           ]

testSuite "JQScheduler"
            [ 'case_parseRateLimit
            , 'case_isOverfull
            , 'case_joinSlotMap_examples
            , 'prop_joinSlotMap
            , 'prop_slotMapFromJob_conflicting_buckets
            , 'case_hasSlotsFor_examples
            , 'prop_hasSlotsFor_fitting
            , 'prop_hasSlotsFor
            , 'prop_reasonRateLimit
            ]

{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Tests for lock waiting structure.

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

module Test.Ganeti.Locking.Waiting (testLocking_Waiting) where

import Control.Applicative ((<$>), (<*>), liftA2)
import Control.Monad (liftM)
import qualified Data.Map as M
import qualified Data.Set as S
import qualified Text.JSON as J

import Test.QuickCheck

import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper
import Test.Ganeti.Locking.Allocation (TestLock, TestOwner, requestSucceeded)

import Ganeti.BasicTypes (isBad, genericResult, runListHead)
import Ganeti.Locking.Allocation (LockRequest, listLocks)
import qualified Ganeti.Locking.Allocation as L
import Ganeti.Locking.Types (Lock)
import Ganeti.Locking.Waiting

{-

Ganeti.Locking.Waiting is polymorphic in the types of locks, lock owners,
and priorities. So we can use much simpler types here than Ganeti's
real locks and lock owners, knowning that polymorphic functions cannot
exploit the simplicity of the types they're deling with. To avoid code
duplication, we use the test structure from Test.Ganeti.Locking.Allocation.

-}

{-

All states of a LockWaiting ever available outside the module can be
obtained from @emptyWaiting@ applying one of the update operations.

-}

data UpdateRequest a b c = Update b [LockRequest a]
                         | UpdateWaiting c b [LockRequest a]
                         | RemovePending b
                         | IntersectRequest b [a]
                         | OpportunisticUnion b [(a, L.OwnerState)]
                         deriving Show

instance (Arbitrary a, Arbitrary b, Arbitrary c)
         => Arbitrary (UpdateRequest a b c) where
  arbitrary =
    frequency [ (2, Update <$> arbitrary <*> (choose (1, 4) >>= vector))
              , (4, UpdateWaiting <$> arbitrary <*> arbitrary
                                  <*> (choose (1, 4) >>= vector))
              , (1, RemovePending <$> arbitrary)
              , (1, IntersectRequest <$> arbitrary
                                     <*> (choose (1, 4) >>= vector))
              , (1, OpportunisticUnion <$> arbitrary
                                       <*> (choose (1, 4) >>= vector))
              ]

-- | Transform an UpdateRequest into the corresponding state transformer.
asWaitingTrans :: (Lock a, Ord b, Ord c)
               => LockWaiting a b c -> UpdateRequest a b c -> LockWaiting a b c
asWaitingTrans state (Update owner req) = fst $ updateLocks owner req state
asWaitingTrans state (UpdateWaiting prio owner req) =
  fst $ updateLocksWaiting prio owner req state
asWaitingTrans state (RemovePending owner) = removePendingRequest owner state
asWaitingTrans state (IntersectRequest owner locks) =
  fst $ intersectLocks locks owner state
asWaitingTrans state (OpportunisticUnion owner locks) =
  fst $ opportunisticLockUnion owner locks state


-- | Fold a sequence of requests to transform a waiting strucutre onto the
-- empty waiting. As we consider all exported transformations, any waiting
-- structure can be obtained this way.
foldUpdates :: (Lock a, Ord b, Ord c)
            => [UpdateRequest a b c] -> LockWaiting a b c
foldUpdates = foldl asWaitingTrans emptyWaiting

instance (Arbitrary a, Lock a, Arbitrary b, Ord b, Arbitrary c, Ord c)
         => Arbitrary (LockWaiting a b c) where
  arbitrary = foldUpdates <$> (choose (0, 8) >>= vector)

-- | Verify that an owner with a pending request cannot make any
-- changes to the lock structure.
prop_NoActionWithPendingRequests :: Property
prop_NoActionWithPendingRequests =
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll ((arbitrary :: Gen (LockWaiting TestLock TestOwner Integer))
          `suchThat` (S.member a . getPendingOwners)) $ \state ->
  forAll (arbitrary :: Gen [LockRequest TestLock]) $ \req ->
  forAll arbitrary $ \prio ->
  counterexample "Owners with pending requests may not update locks"
  . all (isBad . fst . snd)
  $ [updateLocks, updateLocksWaiting prio] <*> [a] <*> [req] <*> [state]

-- | Quantifier for blocked requests. Quantifies over the generic situation
-- that there is a state, an owner, and a request that is blocked for that
-- owner. To obtain such a situation, we use the fact that there must be a
-- different owner having at least one lock.
forAllBlocked :: (Testable prop)
              => (LockWaiting TestLock TestOwner Integer -- State
                  -> TestOwner -- The owner of the blocked request
                  -> Integer -- The priority
                  -> [LockRequest TestLock] -- Request
                  -> prop)
              -> Property
forAllBlocked predicate =
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary :: Gen Integer) $ \prio ->
  forAll (arbitrary `suchThat` (/=) a) $ \b ->
  forAll ((arbitrary :: Gen (LockWaiting TestLock TestOwner Integer))
          `suchThat` foldl (liftA2 (&&)) (const True)
              [ not . S.member a . getPendingOwners
              , M.null . listLocks a . getAllocation
              , not . M.null . listLocks b . getAllocation]) $ \state ->
  forAll ((arbitrary :: Gen [LockRequest TestLock])
          `suchThat` (genericResult (const False) (not . S.null)
                      . fst . snd . flip (updateLocksWaiting prio a) state))
          $ \req ->
  predicate state a prio req

-- | Verify that an owner has a pending request after a waiting request
-- not fullfilled immediately.
prop_WaitingRequestsGetPending :: Property
prop_WaitingRequestsGetPending =
  forAllBlocked $ \state owner prio req ->
  counterexample "After a not immediately fulfilled waiting request, owner\
                 \ must have a pending request"
  . S.member owner . getPendingOwners . fst
  $ updateLocksWaiting prio owner req state

-- | Verify that pending requests get fullfilled once all blockers release
-- their resources.
prop_PendingGetFulfilledEventually :: Property
prop_PendingGetFulfilledEventually =
  forAllBlocked $ \state owner prio req ->
  let oldpending = getPendingOwners state
      (state', (resultBlockers, _)) = updateLocksWaiting prio owner req state
      blockers = genericResult (const S.empty) id resultBlockers
      state'' = S.foldl (\s a -> fst $ releaseResources a s) state'
                  $ S.union oldpending blockers
      finallyOwned = listLocks  owner $ getAllocation state''
  in counterexample "After all blockers and old pending owners give up their\
                    \ resources, a pending request must be granted\
                    \ automatically"
     $ all (requestSucceeded finallyOwned) req

-- | Verify that the owner of a pending request gets notified once all blockers
-- release their resources.
prop_PendingGetNotifiedEventually :: Property
prop_PendingGetNotifiedEventually =
  forAllBlocked $ \state owner prio req ->
  let oldpending = getPendingOwners state
      (state', (resultBlockers, _)) = updateLocksWaiting prio owner req state
      blockers = genericResult (const S.empty) id resultBlockers
      releaseOneOwner (s, tonotify) o =
        let (s', newnotify) = releaseResources o s
        in (s', newnotify `S.union` tonotify)
      (_, notified) = S.foldl releaseOneOwner (state', S.empty)
                        $ S.union oldpending blockers
  in counterexample "After all blockers and old pending owners give up their\
                    \ resources, a pending owner must be notified"
     $ S.member owner notified

-- | Verify that some progress is made after the direct blockers give up their
-- locks. Note that we cannot guarantee that the original requester gets its
-- request granted, as someone else might have a more important priority.
prop_Progress :: Property
prop_Progress =
  forAllBlocked $ \state owner prio req ->
  let (state', (resultBlockers, _)) = updateLocksWaiting prio owner req state
      blockers = genericResult (const S.empty) id resultBlockers
      releaseOneOwner (s, tonotify) o =
        let (s', newnotify) = releaseResources o s
        in (s', newnotify `S.union` tonotify)
      (_, notified) = S.foldl releaseOneOwner (state', S.empty) blockers
  in counterexample "Some progress must be made after all blockers release\
                    \ their locks"
     . not . S.null $ notified S.\\ blockers

-- | Verify that the notifications send out are sound, i.e., upon notification
-- the requests actually are fulfilled. To be sure to have at least one
-- notification we, again, use the scenario that a request is blocked and then
-- all the blockers release their resources.
prop_ProgressSound :: Property
prop_ProgressSound =
  forAllBlocked $ \state owner prio req ->
  let (state', (resultBlockers, _)) = updateLocksWaiting prio owner req state
      blockers = genericResult (const S.empty) id resultBlockers
      releaseOneOwner (s, tonotify) o =
        let (s', newnotify) = releaseResources o s
        in (s', newnotify `S.union` tonotify)
      (state'', notified) = S.foldl releaseOneOwner (state', S.empty) blockers
      requestFulfilled o =
        runListHead False
          (\(_, _, r) ->
              all (requestSucceeded . listLocks o $ getAllocation state'') r)
          . S.toList . S.filter (\(_, b, _) -> b == o)
          . getPendingRequests $ state'
  in counterexample "If an owner gets notified, his request must be satisfied"
     . all requestFulfilled . S.toList $ notified S.\\ blockers

-- | Verify that all pending requests are valid and cannot be fulfilled in
-- the underlying lock allocation.
prop_PendingJustified :: Property
prop_PendingJustified =
  forAll ((arbitrary :: Gen (LockWaiting TestLock TestOwner Integer))
          `suchThat` (not . S.null . getPendingRequests)) $ \state ->
  let isJustified (_, b, req) =
        genericResult (const False) (not . S.null) . snd
        . L.updateLocks b req $ getAllocation state
  in counterexample "Pending requests must be good and not fulfillable"
     . all isJustified . S.toList $ getPendingRequests state

-- | Verify that `updateLocks` is idempotent, except that in the repetition,
-- no waiters are notified.
prop_UpdateIdempotent :: Property
prop_UpdateIdempotent =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \owner ->
  forAll (arbitrary :: Gen [LockRequest TestLock]) $ \req ->
  let (state', (answer', _)) = updateLocks owner req state
      (state'', (answer'', nfy)) = updateLocks owner req state'
  in conjoin [ counterexample ("repeated updateLocks waiting gave different\
                               \ answers: " ++ show answer' ++ " /= "
                               ++ show answer'') $ answer' == answer''
             , counterexample "updateLocks not idempotent"
               $ extRepr state' == extRepr state''
             , counterexample ("notifications (" ++ show nfy ++ ") on replay")
               $ S.null nfy
             ]

-- | Verify that extRepr . fromExtRepr = id for all valid extensional
-- representations.
prop_extReprPreserved :: Property
prop_extReprPreserved =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  let rep = extRepr state
      rep' = extRepr $ fromExtRepr rep
  in counterexample "a lock waiting obtained from an extensional representation\
                    \ must have the same extensional representation"
     $ rep' == rep

-- | Verify that any state is indistinguishable from its canonical version
-- (i.e., the one obtained from the extensional representation) with respect
-- to updateLocks.
prop_SimulateUpdateLocks :: Property
prop_SimulateUpdateLocks =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \owner ->
  forAll (arbitrary :: Gen [LockRequest TestLock]) $ \req ->
  let state' = fromExtRepr $ extRepr state
      (finState, (result, notify)) = updateLocks owner req state
      (finState', (result', notify')) = updateLocks owner req state'
  in counterexample "extRepr-equal states must behave equal on updateLocks"
     $ and [ result == result'
           , notify == notify'
           , extRepr finState == extRepr finState'
           ]
-- | Verify that any state is indistinguishable from its canonical version
-- (i.e., the one obtained from the extensional representation) with respect
-- to updateLocksWaiting.
prop_SimulateUpdateLocksWaiting :: Property
prop_SimulateUpdateLocksWaiting =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \owner ->
  forAll (arbitrary :: Gen Integer) $ \prio ->
  forAll (arbitrary :: Gen [LockRequest TestLock]) $ \req ->
  let state' = fromExtRepr $ extRepr state
      (finState, (result, notify)) = updateLocksWaiting prio owner req state
      (finState', (result', notify')) = updateLocksWaiting prio owner req state'
  in counterexample "extRepr-equal states must behave equal on updateLocks"
     $ and [ result == result'
           , notify == notify'
           , extRepr finState == extRepr finState'
           ]

-- | Verify that if a requestor has no pending requests, `safeUpdateWaiting`
-- conincides with `updateLocksWaiting`.
prop_SafeUpdateWaitingCorrect :: Property
prop_SafeUpdateWaitingCorrect  =
  forAll (arbitrary :: Gen TestOwner) $ \owner ->
  forAll ((arbitrary :: Gen (LockWaiting TestLock TestOwner Integer))
          `suchThat` (not . hasPendingRequest owner)) $ \state ->
  forAll (arbitrary :: Gen Integer) $ \prio ->
  forAll (arbitrary :: Gen [LockRequest TestLock]) $ \req ->
  let (state', answer') = updateLocksWaiting prio owner req state
      (state'', answer'') = safeUpdateLocksWaiting prio owner req state
  in conjoin [ counterexample ("safeUpdateLocksWaiting gave different answer: "
                              ++ show answer' ++ " /= " ++ show answer'')
               $ answer' == answer''
             , counterexample ("safeUpdateLocksWaiting gave different states\
                               \ after answer " ++ show answer' ++ ": "
                               ++ show (extRepr state') ++ " /= "
                               ++ show (extRepr state''))
               $ extRepr state' == extRepr state''
             ]

-- | Verify that `safeUpdateLocksWaiting` is idempotent, that in the repetition
-- no notifications are done.
prop_SafeUpdateWaitingIdempotent :: Property
prop_SafeUpdateWaitingIdempotent =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \owner ->
  forAll (arbitrary :: Gen Integer) $ \prio ->
  forAll (arbitrary :: Gen [LockRequest TestLock]) $ \req ->
  let (state', (answer', _)) = safeUpdateLocksWaiting prio owner req state
      (state'', (answer'', nfy)) = safeUpdateLocksWaiting prio owner req state'
  in conjoin [ counterexample ("repeated safeUpdateLocks waiting gave different\
                               \ answers: " ++ show answer' ++ " /= "
                               ++ show answer'') $ answer' == answer''
             , counterexample "safeUpdateLocksWaiting not idempotent"
               $ extRepr state' == extRepr state''
             , counterexample ("notifications (" ++ show nfy ++ ") on replay")
               $ S.null nfy
             ]

-- | Verify that for LockWaiting we have readJSON . showJSON is extensionally
-- equivalent to Ok.
prop_ReadShow :: Property
prop_ReadShow =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  (liftM extRepr . J.readJSON $ J.showJSON state) ==? (J.Ok $ extRepr state)

-- | Verify that opportunistic union only increases the locks held.
prop_OpportunisticMonotone :: Property
prop_OpportunisticMonotone =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll ((choose (1,3) >>= vector) :: Gen [(TestLock, L.OwnerState)]) $ \req ->
  let (state', _) = opportunisticLockUnion a req state
      oldOwned = listLocks a $ getAllocation state
      oldLocks = M.keys oldOwned
      newOwned = listLocks a $ getAllocation state'
  in counterexample "Opportunistic union may only increase the set of locks\
                    \ held"
     . flip all oldLocks $ \lock ->
       M.lookup lock newOwned >= M.lookup lock oldOwned

-- | Verify the result list of the opportunistic union: if a lock is not in
-- the result that, than its state has not changed, and if it is, it is as
-- requested. The latter property is tested in that liberal way, so that we
-- really can take arbitrary requests, including those that require both, shared
-- and exlusive state for the same lock.
prop_OpportunisticAnswer :: Property
prop_OpportunisticAnswer =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll ((choose (1,3) >>= vector) :: Gen [(TestLock, L.OwnerState)]) $ \req ->
  let (state', (result, _)) = opportunisticLockUnion a req state
      oldOwned = listLocks a $ getAllocation state
      newOwned = listLocks a $ getAllocation state'
      involvedLocks = M.keys oldOwned ++ map fst req
  in conjoin [ counterexample ("Locks not in the answer set " ++ show result
                                 ++ " may not be changed, but found "
                                 ++ show state')
               . flip all involvedLocks $ \lock ->
                 (lock `elem` result)
                 || (M.lookup lock oldOwned == M.lookup lock newOwned)
             , counterexample ("Locks not in the answer set " ++ show result
                                ++ " must be as requested, but found "
                                ++ show state')
               . flip all involvedLocks $ \lock ->
                 notElem lock result
                 || maybe False (flip elem req . (,) lock)
                      (M.lookup lock newOwned)
             ]


testSuite "Locking/Waiting"
 [ 'prop_NoActionWithPendingRequests
 , 'prop_WaitingRequestsGetPending
 , 'prop_PendingGetFulfilledEventually
 , 'prop_PendingGetNotifiedEventually
 , 'prop_Progress
 , 'prop_ProgressSound
 , 'prop_PendingJustified
 , 'prop_extReprPreserved
 , 'prop_UpdateIdempotent
 , 'prop_SimulateUpdateLocks
 , 'prop_SimulateUpdateLocksWaiting
 , 'prop_ReadShow
 , 'prop_SafeUpdateWaitingCorrect
 , 'prop_SafeUpdateWaitingIdempotent
 , 'prop_OpportunisticMonotone
 , 'prop_OpportunisticAnswer
 ]

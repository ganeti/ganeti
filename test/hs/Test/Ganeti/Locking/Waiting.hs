{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Tests for lock waiting structure.

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
                         deriving Show

instance (Arbitrary a, Arbitrary b, Arbitrary c)
         => Arbitrary (UpdateRequest a b c) where
  arbitrary =
    frequency [ (2, Update <$> arbitrary <*> (choose (1, 4) >>= vector))
              , (4, UpdateWaiting <$> arbitrary <*> arbitrary
                                  <*> (choose (1, 4) >>= vector))
              , (1, RemovePending <$> arbitrary)
              ]

-- | Transform an UpdateRequest into the corresponding state transformer.
asWaitingTrans :: (Lock a, Ord b, Ord c)
               => LockWaiting a b c -> UpdateRequest a b c -> LockWaiting a b c
asWaitingTrans state (Update owner req) = fst $ updateLocks owner req state
asWaitingTrans state (UpdateWaiting prio owner req) =
  fst $ updateLocksWaiting prio owner req state
asWaitingTrans state (RemovePending owner) = removePendingRequest owner state


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
  printTestCase "Owners with pending requests may not update locks"
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
  printTestCase "After a not immediately fulfilled waiting request, owner\
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
  in printTestCase "After all blockers and old pending owners give up their\
                   \ resources, a pending request must be granted automatically"
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
  in printTestCase "After all blockers and old pending owners give up their\
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
  in printTestCase "Some progress must be made after all blockers release\
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
  in printTestCase "If an owner gets notified, his request must be satisfied"
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
  in printTestCase "Pebding requests must be good and not fulfillable"
     . all isJustified . S.toList $ getPendingRequests state

-- | Verify that extRepr . fromExtRepr = id for all valid extensional
-- representations.
prop_extReprPreserved :: Property
prop_extReprPreserved =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  let rep = extRepr state
      rep' = extRepr $ fromExtRepr rep
  in printTestCase "a lock waiting obtained from an extensional representation\
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
  in printTestCase "extRepr-equal states must behave equal on updateLocks"
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
  in printTestCase "extRepr-equal states must behave equal on updateLocks"
     $ and [ result == result'
           , notify == notify'
           , extRepr finState == extRepr finState'
           ]

-- | Verify that for LockWaiting we have readJSON . showJSON is extensionally
-- equivalent to Ok.
prop_ReadShow :: Property
prop_ReadShow =
  forAll (arbitrary :: Gen (LockWaiting TestLock TestOwner Integer)) $ \state ->
  (liftM extRepr . J.readJSON $ J.showJSON state) ==? (J.Ok $ extRepr state)

testSuite "Locking/Waiting"
 [ 'prop_NoActionWithPendingRequests
 , 'prop_WaitingRequestsGetPending
 , 'prop_PendingGetFulfilledEventually
 , 'prop_PendingGetNotifiedEventually
 , 'prop_Progress
 , 'prop_ProgressSound
 , 'prop_PendingJustified
 , 'prop_extReprPreserved
 , 'prop_SimulateUpdateLocks
 , 'prop_SimulateUpdateLocksWaiting
 , 'prop_ReadShow
 ]

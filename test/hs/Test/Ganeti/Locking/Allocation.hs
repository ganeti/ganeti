{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Tests for lock allocation.

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

module Test.Ganeti.Locking.Allocation
  ( testLocking_Allocation
  , TestLock
  , TestOwner
  , requestSucceeded
  ) where

import Control.Applicative
import qualified Data.Foldable as F
import qualified Data.Map as M
import Data.Maybe (fromMaybe)
import qualified Data.Set as S
import qualified Text.JSON as J

import Test.QuickCheck

import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper

import Ganeti.BasicTypes
import Ganeti.Locking.Allocation
import Ganeti.Locking.Types

{-

Ganeti.Locking.Allocation is polymorphic in the types of locks
and lock owners. So we can use much simpler types here than Ganeti's
real locks and lock owners, knowning that polymorphic functions cannot
exploit the simplicity of the types they're deling with.

-}

data TestOwner = TestOwner Int deriving (Ord, Eq, Show)

instance Arbitrary TestOwner where
  arbitrary = TestOwner <$> choose (0, 2)

data TestLock = TestBigLock
              | TestCollectionLockA
              | TestLockA Int
              | TestCollectionLockB
              | TestLockB Int
              deriving (Ord, Eq, Show, Read)

instance Arbitrary TestLock where
  arbitrary =  frequency [ (1, elements [ TestBigLock
                                        , TestCollectionLockA
                                        , TestCollectionLockB
                                        ])
                         , (2, TestLockA <$> choose (0, 2))
                         , (2, TestLockB <$> choose (0, 2))
                         ]

instance Lock TestLock where
  lockImplications (TestLockA _) = [TestCollectionLockA, TestBigLock]
  lockImplications (TestLockB _) = [TestCollectionLockB, TestBigLock]
  lockImplications TestBigLock = []
  lockImplications _ = [TestBigLock]

{-

All states of a  LockAllocation ever available outside the
Ganeti.Locking.Allocation module must be constructed by starting
with emptyAllocation and applying the exported functions.

-}

instance Arbitrary OwnerState where
  arbitrary = elements [OwnShared, OwnExclusive]

instance Arbitrary a => Arbitrary (LockRequest a) where
  arbitrary = LockRequest <$> arbitrary <*> genMaybe arbitrary

data UpdateRequest b a = UpdateRequest b [LockRequest a]
                       | IntersectRequest b [a]
                       | OpportunisticUnion b [(a, OwnerState)]
                       | FreeLockRequest b
                       deriving Show

instance (Arbitrary a, Arbitrary b) => Arbitrary (UpdateRequest a b) where
  arbitrary =
    frequency [ (4, UpdateRequest <$> arbitrary <*> (choose (1, 4) >>= vector))
              , (2, IntersectRequest <$> arbitrary
                                     <*> (choose (1, 4) >>= vector))
              , (2, OpportunisticUnion <$> arbitrary
                                       <*> (choose (1, 4) >>= vector))
              , (1, FreeLockRequest <$> arbitrary)
              ]

-- | Transform an UpdateRequest into the corresponding state transformer.
asAllocTrans :: (Lock a, Ord b, Show b)
              => LockAllocation a b -> UpdateRequest b a -> LockAllocation a b
asAllocTrans state (UpdateRequest owner updates) =
  fst $ updateLocks owner updates state
asAllocTrans state (IntersectRequest owner locks) =
  intersectLocks owner locks state
asAllocTrans state (OpportunisticUnion owner locks) =
  fst $ opportunisticLockUnion owner locks state
asAllocTrans state (FreeLockRequest owner) = freeLocks state owner

-- | Fold a sequence of requests to transform a lock allocation onto the empty
-- allocation. As we consider all exported LockAllocation transformers, any
-- LockAllocation definable is obtained in this way.
foldUpdates :: (Lock a, Ord b, Show b)
            => [UpdateRequest b a] -> LockAllocation a b
foldUpdates = foldl asAllocTrans emptyAllocation

instance (Arbitrary a, Lock a, Arbitrary b, Ord b, Show b)
          => Arbitrary (LockAllocation a b) where
  arbitrary = foldUpdates <$> (choose (0, 8) >>= vector)

-- | Basic property of locking: the exclusive locks of one user
-- are disjoint from any locks of any other user.
prop_LocksDisjoint :: Property
prop_LocksDisjoint =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary `suchThat` (/= a)) $ \b ->
  let aExclusive = M.keysSet . M.filter (== OwnExclusive) $ listLocks  a state
      bAll = M.keysSet $ listLocks b state
  in printTestCase
     (show a ++ "'s exclusive lock" ++ " is not respected by " ++ show b)
     (S.null $ S.intersection aExclusive bAll)

-- | Verify that the list of active locks indeed contains all locks that
-- are owned by someone.
prop_LockslistComplete :: Property
prop_LockslistComplete =
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll ((arbitrary :: Gen (LockAllocation TestLock TestOwner))
          `suchThat` (not . M.null . listLocks a)) $ \state ->
  printTestCase "All owned locks must be mentioned in the all-locks list" $
    let allLocks = listAllLocks state in
    all (`elem` allLocks) (M.keys $ listLocks a state)

-- | Verify that the list of all locks with states is contained in the list
-- of all locks.
prop_LocksAllOwnersSubsetLockslist :: Property
prop_LocksAllOwnersSubsetLockslist =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  printTestCase "The list of all active locks must contain all locks mentioned\
                \ in the locks state" $
  S.isSubsetOf (S.fromList . map fst $ listAllLocksOwners state)
      (S.fromList $ listAllLocks state)

-- | Verify that all locks of all owners are mentioned in the list of all locks'
-- owner's state.
prop_LocksAllOwnersComplete :: Property
prop_LocksAllOwnersComplete =
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll ((arbitrary :: Gen (LockAllocation TestLock TestOwner))
          `suchThat` (not . M.null . listLocks a)) $ \state ->
  printTestCase "Owned locks must be mentioned in list of all locks' state" $
   let allLocksState = listAllLocksOwners state
   in flip all (M.toList $ listLocks a state) $ \(lock, ownership) ->
     elem (a, ownership) . fromMaybe [] $ lookup lock allLocksState

-- | Verify that all lock owners mentioned in the list of all locks' owner's
-- state actually own their lock.
prop_LocksAllOwnersSound :: Property
prop_LocksAllOwnersSound =
  forAll ((arbitrary :: Gen (LockAllocation TestLock TestOwner))
          `suchThat` (not . null . listAllLocksOwners)) $ \state ->
  printTestCase "All locks mentioned in listAllLocksOwners must be owned by the\
                \ mentioned owner" .
  flip all (listAllLocksOwners state) $ \(lock, owners) ->
  flip all owners $ \(owner, ownership) -> holdsLock owner lock ownership state

-- | Verify that exclusive group locks are honored, i.e., verify that if someone
-- holds a lock, then no one else can hold a lock on an exclusive lock on an
-- implied lock.
prop_LockImplicationX :: Property
prop_LockImplicationX =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary `suchThat` (/= a)) $ \b ->
  let bExclusive = M.keysSet . M.filter (== OwnExclusive) $ listLocks  b state
  in printTestCase "Others cannot have an exclusive lock on an implied lock" .
     flip all (M.keys $ listLocks a state) $ \lock ->
     flip all (lockImplications lock) $ \impliedlock ->
     not $ S.member impliedlock bExclusive

-- | Verify that shared group locks are honored, i.e., verify that if someone
-- holds an exclusive lock, then no one else can hold any form on lock on an
-- implied lock.
prop_LockImplicationS :: Property
prop_LockImplicationS =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary `suchThat` (/= a)) $ \b ->
  let aExclusive = M.keys . M.filter (== OwnExclusive) $ listLocks  a state
      bAll = M.keysSet $ listLocks b state
  in printTestCase "Others cannot hold locks implied by an exclusive lock" .
     flip all aExclusive $ \lock ->
     flip all (lockImplications lock) $ \impliedlock ->
     not $ S.member impliedlock bAll

-- | Verify that locks can only be modified by updates of the owner.
prop_LocksStable :: Property
prop_LocksStable =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary `suchThat` (/= a)) $ \b ->
  forAll (arbitrary :: Gen [LockRequest TestLock]) $ \request ->
  let (state', _) = updateLocks b request state
  in (listLocks a state ==? listLocks a state')

-- | Verify that a given request is statisfied in list of owned locks
requestSucceeded :: Ord a => M.Map a  OwnerState -> LockRequest a -> Bool
requestSucceeded owned (LockRequest lock status) = M.lookup lock owned == status

-- | Verify that lock updates are atomic, i.e., either we get all the required
-- locks, or the state is completely unchanged.
prop_LockupdateAtomic :: Property
prop_LockupdateAtomic =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary :: Gen [LockRequest TestLock]) $ \request ->
  let (state', result) = updateLocks a request state
  in if result == Ok S.empty
       then printTestCase
            ("Update succeeded, but in final state " ++ show state'
              ++ "not all locks are as requested")
            $ let owned = listLocks a state'
              in all (requestSucceeded owned) request
       else printTestCase
            ("Update failed, but state changed to " ++ show state')
            (state == state')

-- | Verify that releasing a lock always succeeds.
prop_LockReleaseSucceeds :: Property
prop_LockReleaseSucceeds =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary :: Gen TestLock) $ \lock ->
  let (_, result) = updateLocks a [requestRelease lock] state
  in printTestCase
     ("Releasing a lock has to suceed uncondiationally, but got "
       ++ show result)
     (isOk result)

-- | Verify the property that only the blocking owners prevent
-- lock allocation. We deliberatly go for the expensive variant
-- restraining by suchThat, as otherwise the number of cases actually
-- covered is too small.
prop_BlockSufficient :: Property
prop_BlockSufficient =
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary :: Gen TestLock) $ \lock ->
  forAll (elements [ [requestShared lock]
                   , [requestExclusive lock]]) $ \request ->
  forAll ((arbitrary :: Gen (LockAllocation TestLock TestOwner))
           `suchThat` (genericResult (const False) (not . S.null)
                        . snd . updateLocks a request)) $ \state ->
  let (_, result) = updateLocks a request state
      blockedOn = genericResult (const S.empty) id result
  in  printTestCase "After all blockers release, a request must succeed"
      . isOk . snd . updateLocks a request $ F.foldl freeLocks state blockedOn

-- | Verify the property that every blocking owner is necessary, i.e., even
-- if we only keep the locks of one of the blocking owners, the request still
-- will be blocked. We deliberatly use the expensive variant of restraining
-- to ensure good coverage. To make sure the request can always be blocked
-- by two owners, for a shared request we request two different locks.
prop_BlockNecessary :: Property
prop_BlockNecessary =
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll (arbitrary :: Gen TestLock) $ \lock ->
  forAll (arbitrary `suchThat` (/= lock)) $ \lock' ->
  forAll (elements [ [requestShared lock, requestShared lock']
                   , [requestExclusive lock]]) $ \request ->
  forAll ((arbitrary :: Gen (LockAllocation TestLock TestOwner))
           `suchThat` (genericResult (const False) ((>= 2) . S.size)
                        . snd . updateLocks a request)) $ \state ->
  let (_, result) = updateLocks a request state
      blockers = genericResult (const S.empty) id result
  in  printTestCase "Each blocker alone must block the request"
      . flip all (S.elems blockers) $ \blocker ->
        (==) (Ok $ S.singleton blocker) . snd . updateLocks a request
        . F.foldl freeLocks state
        $ S.filter (/= blocker) blockers

-- | Verify that opportunistic union only increases the locks held.
prop_OpportunisticMonotone :: Property
prop_OpportunisticMonotone =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll ((choose (1,3) >>= vector) :: Gen [(TestLock, OwnerState)]) $ \req ->
  let (state', _) = opportunisticLockUnion a req state
      oldOwned = listLocks a state
      oldLocks = M.keys oldOwned
      newOwned = listLocks a state'
  in printTestCase "Opportunistic union may only increase the set of locks held"
     . flip all oldLocks $ \lock ->
       M.lookup lock newOwned >= M.lookup lock oldOwned

-- | Verify the result list of the opportunistic union: if a lock is not in
-- the result that, than its state has not changed, and if it is, it is as
-- requested. The latter property is tested in that liberal way, so that we
-- really can take arbitrary requests, including those that require both, shared
-- and exlusive state for the same lock.
prop_OpportunisticAnswer :: Property
prop_OpportunisticAnswer =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  forAll (arbitrary :: Gen TestOwner) $ \a ->
  forAll ((choose (1,3) >>= vector) :: Gen [(TestLock, OwnerState)]) $ \req ->
  let (state', result) = opportunisticLockUnion a req state
      oldOwned = listLocks a state
      newOwned = listLocks a state'
      involvedLocks = M.keys oldOwned ++ map fst req
  in conjoin [ printTestCase ("Locks not in the answer set " ++ show result
                                ++ " may not be changed, but found "
                                ++ show state')
               . flip all involvedLocks $ \lock ->
                 (lock `S.member` result)
                 || (M.lookup lock oldOwned == M.lookup lock newOwned)
             , printTestCase ("Locks not in the answer set " ++ show result
                               ++ " must be as requested, but found "
                               ++ show state')
               . flip all involvedLocks $ \lock ->
                 (lock `S.notMember` result)
                 || maybe False (flip elem req . (,) lock)
                      (M.lookup lock newOwned)
             ]

instance J.JSON TestOwner where
  showJSON (TestOwner x) = J.showJSON x
  readJSON = (>>= return . TestOwner) . J.readJSON

instance J.JSON TestLock where
  showJSON = J.showJSON . show
  readJSON = (>>= return . read) . J.readJSON

-- | Verify that for LockAllocation we have readJSON . showJSON = Ok.
prop_ReadShow :: Property
prop_ReadShow =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  J.readJSON (J.showJSON state) ==? J.Ok state

-- | Verify that the list of lock owners is complete.
prop_OwnerComplete :: Property
prop_OwnerComplete =
  forAll (arbitrary :: Gen (LockAllocation TestLock TestOwner)) $ \state ->
  foldl freeLocks state (lockOwners state) ==? emptyAllocation

-- | Verify that each owner actually owns a lock.
prop_OwnerSound :: Property
prop_OwnerSound =
  forAll ((arbitrary :: Gen (LockAllocation TestLock TestOwner))
          `suchThat` (not . null . lockOwners)) $ \state ->
  printTestCase "All subjects listed as owners must own at least one lock"
  . flip all (lockOwners state) $ \owner ->
  not . M.null $ listLocks owner state

testSuite "Locking/Allocation"
 [ 'prop_LocksDisjoint
 , 'prop_LockslistComplete
 , 'prop_LocksAllOwnersSubsetLockslist
 , 'prop_LocksAllOwnersComplete
 , 'prop_LocksAllOwnersSound
 , 'prop_LockImplicationX
 , 'prop_LockImplicationS
 , 'prop_LocksStable
 , 'prop_LockupdateAtomic
 , 'prop_LockReleaseSucceeds
 , 'prop_BlockSufficient
 , 'prop_BlockNecessary
 , 'prop_OpportunisticMonotone
 , 'prop_OpportunisticAnswer
 , 'prop_ReadShow
 , 'prop_OwnerComplete
 , 'prop_OwnerSound
 ]

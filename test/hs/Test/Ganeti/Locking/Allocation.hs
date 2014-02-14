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

module Test.Ganeti.Locking.Allocation (testLocking_Allocation) where

import Control.Applicative
import qualified Data.Map as M
import qualified Data.Set as S

import Test.QuickCheck

import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper

import Ganeti.BasicTypes
import Ganeti.Locking.Allocation

{-

Ganeti.Locking.Allocation is polymorphic in the types of locks
and lock owners. So we can use much simpler types here than Ganeti's
real locks and lock owners, knowning at polymorphic functions cannot
exploit the simplicity of the types they're deling with.

-}

data TestOwner = TestOwner Int deriving (Ord, Eq, Show)

instance Arbitrary TestOwner where
  arbitrary = TestOwner <$> choose (0, 7)

data TestLock = TestLock Int deriving (Ord, Eq, Show)

instance Arbitrary TestLock where
  arbitrary = TestLock <$> choose (0, 7)


{-

All states of a  LockAllocation can be obtained by starting from the
empty allocation, and sequentially requesting (successfully or not)
lock updates. So we first define what arbitrary updates sequences are.

-}

instance Arbitrary OwnerState where
  arbitrary = elements [OwnShared, OwnExclusive]

instance Arbitrary a => Arbitrary (LockRequest a) where
  arbitrary = LockRequest <$> arbitrary <*> genMaybe arbitrary

data UpdateRequest a b = UpdateRequest a [LockRequest b] deriving Show

instance (Arbitrary a, Arbitrary b) => Arbitrary (UpdateRequest a b) where
  arbitrary = UpdateRequest <$> arbitrary <*> arbitrary

-- | Fold a sequence of update requests; all allocationscan be obtained in
-- this way, starting from the empty allocation.
foldUpdates :: (Ord a, Ord b, Show b)
            => LockAllocation b a -> [UpdateRequest a b] -> LockAllocation b a
foldUpdates = foldl (\s (UpdateRequest owner updates) ->
                      fst $ updateLocks owner updates s)

instance (Arbitrary a, Arbitrary b, Ord a, Ord b, Show a, Show b)
          => Arbitrary (LockAllocation a b) where
  arbitrary = foldUpdates emptyAllocation <$> arbitrary

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
            ("Update suceeded, but in final state " ++ show state'
              ++ "not all locks are as requested")
            $ let owned = listLocks a state'
              in all (requestSucceeded owned) request
       else printTestCase
            ("Update failed, but state changed to " ++ show state')
            (state == state')

testSuite "Locking/Allocation"
 [ 'prop_LocksDisjoint
 , 'prop_LocksStable
 , 'prop_LockupdateAtomic
 ]

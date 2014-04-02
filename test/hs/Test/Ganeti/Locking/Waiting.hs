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

import Control.Applicative ((<$>), (<*>))
import qualified Data.Set as S

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.Locking.Allocation (TestLock, TestOwner)

import Ganeti.BasicTypes (isBad)
import Ganeti.Locking.Allocation (LockRequest)
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
                         deriving Show

instance (Arbitrary a, Arbitrary b, Arbitrary c)
         => Arbitrary (UpdateRequest a b c) where
  arbitrary =
    frequency [ (1, Update <$> arbitrary <*> (choose (1, 4) >>= vector))
              , (2, UpdateWaiting <$> arbitrary <*> arbitrary
                                  <*> (choose (1, 4) >>= vector))
              ]

-- | Transform an UpdateRequest into the corresponding state transformer.
asWaitingTrans :: (Lock a, Ord b, Ord c)
               => LockWaiting a b c -> UpdateRequest a b c -> LockWaiting a b c
asWaitingTrans state (Update owner req) = fst $ updateLocks owner req state
asWaitingTrans state (UpdateWaiting prio owner req) =
  fst $ updateLocksWaiting prio owner req state


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

testSuite "Locking/Waiting"
 [ 'prop_NoActionWithPendingRequests
 ]

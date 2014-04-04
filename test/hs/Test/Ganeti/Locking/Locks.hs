{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Tests for the lock data structure

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

module Test.Ganeti.Locking.Locks (testLocking_Locks) where

import Control.Applicative ((<$>), (<*>), liftA2)

import Test.QuickCheck
import Text.JSON

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Types ()

import Ganeti.Locking.Locks
import Ganeti.Locking.Types

instance Arbitrary GanetiLocks where
  arbitrary = oneof [ return BGL
                    , return ClusterLockSet
                    , return InstanceLockSet
                    , Instance <$> genUUID
                    , return NodeGroupLockSet
                    , NodeGroup <$> genUUID
                    , return NAL
                    , return NodeAllocLockSet
                    , return NodeResLockSet
                    , NodeRes <$> genUUID
                    , return NodeLockSet
                    , Node <$> genUUID
                    , return NetworkLockSet
                    , Network <$> genUUID
                    ]

-- | Verify that readJSON . showJSON = Ok
prop_ReadShow :: Property
prop_ReadShow = forAll (arbitrary :: Gen GanetiLocks) $ \a ->
  readJSON (showJSON a) ==? Ok a

-- | Verify the implied locks are earlier in the lock order.
prop_ImpliedOrder :: Property
prop_ImpliedOrder =
  forAll ((arbitrary :: Gen GanetiLocks)
          `suchThat` (not . null . lockImplications)) $ \b ->
  printTestCase "Implied locks must be earlier in the lock order"
  . flip all (lockImplications b) $ \a ->
  a < b

-- | Verify the intervall property of the locks.
prop_ImpliedIntervall :: Property
prop_ImpliedIntervall =
  forAll ((arbitrary :: Gen GanetiLocks)
          `suchThat` (not . null . lockImplications)) $ \b ->
  forAll (elements $ lockImplications b) $ \a ->
  forAll (arbitrary `suchThat` liftA2 (&&) (a <) (<= b)) $ \x ->
  printTestCase ("Locks between a group and a member of the group"
                 ++ " must also belong to the group")
  $ a `elem` lockImplications x

instance Arbitrary LockLevel where
  arbitrary = elements [LevelCluster ..]

-- | Verify that readJSON . showJSON = Ok for lock levels
prop_ReadShowLevel :: Property
prop_ReadShowLevel = forAll (arbitrary :: Gen LockLevel) $ \a ->
  readJSON (showJSON a) ==? Ok a

instance Arbitrary ClientType where
  arbitrary = oneof [ ClientOther <$> arbitrary
                    , ClientJob <$> arbitrary
                    ]

-- | Verify that readJSON . showJSON = Ok for ClientType
prop_ReadShow_ClientType :: Property
prop_ReadShow_ClientType = forAll (arbitrary :: Gen ClientType) $ \a ->
  readJSON (showJSON a) ==? Ok a

instance Arbitrary ClientId where
  arbitrary = ClientId <$> arbitrary <*> arbitrary

-- | Verify that readJSON . showJSON = Ok for ClientId
prop_ReadShow_ClientId :: Property
prop_ReadShow_ClientId = forAll (arbitrary :: Gen ClientId) $ \a ->
  readJSON (showJSON a) ==? Ok a

testSuite "Locking/Locks"
 [ 'prop_ReadShow
 , 'prop_ImpliedOrder
 , 'prop_ImpliedIntervall
 , 'prop_ReadShowLevel
 , 'prop_ReadShow_ClientType
 , 'prop_ReadShow_ClientId
 ]

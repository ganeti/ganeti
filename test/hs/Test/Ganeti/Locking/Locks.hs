{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Tests for the lock data structure

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

module Test.Ganeti.Locking.Locks (testLocking_Locks) where

import Control.Applicative ((<$>), (<*>), liftA2)
import Control.Monad (liftM)
import System.Posix.Types (CPid)

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
                    , Instance <$> genFQDN
                    , return NodeGroupLockSet
                    , NodeGroup <$> genUUID
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
  counterexample "Implied locks must be earlier in the lock order"
  . flip all (lockImplications b) $ \a ->
  a < b

-- | Verify the intervall property of the locks.
prop_ImpliedIntervall :: Property
prop_ImpliedIntervall =
  forAll ((arbitrary :: Gen GanetiLocks)
          `suchThat` (not . null . lockImplications)) $ \b ->
  forAll (elements $ lockImplications b) $ \a ->
  forAll (arbitrary `suchThat` liftA2 (&&) (a <) (<= b)) $ \x ->
  counterexample ("Locks between a group and a member of the group"
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

instance Arbitrary CPid where
  arbitrary = liftM fromIntegral (arbitrary :: Gen Integer)

instance Arbitrary ClientId where
  arbitrary = ClientId <$> arbitrary <*> arbitrary <*> arbitrary

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

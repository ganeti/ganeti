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

import Test.QuickCheck
import Text.JSON

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.Locking.Locks

instance Arbitrary GanetiLocks where
  arbitrary = elements [BGL]

-- | Verify that readJSON . showJSON = Ok
prop_ReadShow :: Property
prop_ReadShow = forAll (arbitrary :: Gen GanetiLocks) $ \a ->
  readJSON (showJSON a) ==? Ok a


testSuite "Locking/Locks"
 [ 'prop_ReadShow
 ]

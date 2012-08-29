{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Test.Ganeti.Objects (testObjects) where

import qualified Data.Map as Map
import Test.QuickCheck

import Test.Ganeti.TestHelper
import qualified Ganeti.Objects as Objects

-- | Tests that fillDict behaves correctly
prop_Objects_fillDict :: [(Int, Int)] -> [(Int, Int)] -> Property
prop_Objects_fillDict defaults custom =
  let d_map = Map.fromList defaults
      d_keys = map fst defaults
      c_map = Map.fromList custom
      c_keys = map fst custom
  in printTestCase "Empty custom filling"
      (Objects.fillDict d_map Map.empty [] == d_map) .&&.
     printTestCase "Empty defaults filling"
      (Objects.fillDict Map.empty c_map [] == c_map) .&&.
     printTestCase "Delete all keys"
      (Objects.fillDict d_map c_map (d_keys++c_keys) == Map.empty)

testSuite "Objects"
  [ 'prop_Objects_fillDict
  ]

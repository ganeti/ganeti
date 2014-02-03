{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for 'Ganeti.THH.Types'.

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

module Test.Ganeti.THH.Types
  ( testTHH_Types
  ) where

import Test.QuickCheck as QuickCheck hiding (Result)
import qualified Text.JSON as J

import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper

import Ganeti.THH.Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Instances

instance Arbitrary a => Arbitrary (OneTuple a) where
  arbitrary = fmap OneTuple arbitrary

-- * Properties

-- | Tests OneTuple serialisation.
prop_OneTuple_serialisation :: OneTuple String -> Property
prop_OneTuple_serialisation = testSerialisation

-- | Tests OneTuple doesn't deserialize wrong input.
prop_OneTuple_deserialisationFail :: Property
prop_OneTuple_deserialisationFail =
  conjoin . map (testDeserialisationFail (OneTuple "")) $
    [ J.JSArray []
    , J.JSArray [J.showJSON "a", J.showJSON "b"]
    , J.JSArray [J.showJSON (1 :: Int)]
    ]


-- * Test suite

testSuite "THH_Types"
  [ 'prop_OneTuple_serialisation
  , 'prop_OneTuple_deserialisationFail
  ]

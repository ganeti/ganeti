{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for our template-haskell generated code.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Test.Ganeti.THH
  ( testTHH
  ) where

import Test.QuickCheck

import Text.JSON

import Ganeti.THH
import Ganeti.JSON

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Custom types

-- | Type used to test optional field implementation. Equivalent to
-- @data TestObj = TestObj { tobjA :: Maybe Int, tobjB :: Maybe Int
-- }@.
$(buildObject "TestObj" "tobj"
  [ optionalField $ simpleField "a" [t| Int |]
  , optionalNullSerField $ simpleField "b" [t| Int |]
  ])

-- | Arbitrary instance for 'TestObj'.
$(genArbitrary ''TestObj)

-- | Tests that serialising an (arbitrary) 'TestObj' instance is
-- correct: fully optional fields are represented in the resulting
-- dictionary only when non-null, optional-but-required fields are
-- always represented (with either null or an actual value).
prop_OptFields :: TestObj -> Property
prop_OptFields to =
  let a_member = case tobjA to of
                   Nothing -> []
                   Just x -> [("a", showJSON x)]
      b_member = [("b", case tobjB to of
                          Nothing -> JSNull
                          Just x -> showJSON x)]
  in showJSON to ==? makeObj (a_member ++ b_member)


testSuite "THH"
            [ 'prop_OptFields
            ]

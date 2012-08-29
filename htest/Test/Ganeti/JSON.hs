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

module Test.Ganeti.JSON (testJSON) where

import Test.QuickCheck

import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.BasicTypes as BasicTypes
import qualified Ganeti.JSON as JSON

prop_JSON_toArray :: [Int] -> Property
prop_JSON_toArray intarr =
  let arr = map J.showJSON intarr in
  case JSON.toArray (J.JSArray arr) of
    BasicTypes.Ok arr' -> arr ==? arr'
    BasicTypes.Bad err -> failTest $ "Failed to parse array: " ++ err

prop_JSON_toArrayFail :: Int -> String -> Bool -> Property
prop_JSON_toArrayFail i s b =
  -- poor man's instance Arbitrary JSValue
  forAll (elements [J.showJSON i, J.showJSON s, J.showJSON b]) $ \item ->
  case JSON.toArray item of
    BasicTypes.Bad _ -> property True
    BasicTypes.Ok result -> failTest $ "Unexpected parse, got " ++ show result

testSuite "JSON"
          [ 'prop_JSON_toArray
          , 'prop_JSON_toArrayFail
          ]

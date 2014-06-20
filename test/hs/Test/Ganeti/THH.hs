{-# LANGUAGE TemplateHaskell, FunctionalDependencies #-}
{-# OPTIONS -fno-warn-unused-binds #-}

{-| Unittests for our template-haskell generated code.

-}

{-

Copyright (C) 2012 Google Inc.
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

module Test.Ganeti.THH
  ( testTHH
  ) where

import Test.QuickCheck

import Text.JSON

import Ganeti.THH
import Ganeti.PartialParams

import Test.Ganeti.PartialParams
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

-- | Test serialization of TestObj.
prop_TestObj_serialization :: TestObj -> Property
prop_TestObj_serialization = testArraySerialisation

-- | Test that all superfluous keys will fail to parse.
prop_TestObj_deserialisationFail :: Property
prop_TestObj_deserialisationFail =
  forAll ((arbitrary :: Gen [(String, Int)])
          `suchThat` any (flip notElem ["a", "b"] . fst))
  $ testDeserialisationFail (TestObj Nothing Nothing) . encJSDict

-- | A unit-like data type.
$(buildObject "UnitObj" "uobj" [])

$(genArbitrary ''UnitObj)

-- | Test serialization of UnitObj.
prop_UnitObj_serialization :: UnitObj -> Property
prop_UnitObj_serialization = testArraySerialisation

-- | Test that all superfluous keys will fail to parse.
prop_UnitObj_deserialisationFail :: Property
prop_UnitObj_deserialisationFail =
  forAll ((arbitrary :: Gen [(String, Int)]) `suchThat` (not . null))
  $ testDeserialisationFail UnitObj . encJSDict

$(buildParam "Test" "tparam"
  [ simpleField "c" [t| Int |]
  , simpleField "d" [t| String  |]
  ])

$(genArbitrary ''FilledTestParams)
$(genArbitrary ''PartialTestParams)

-- | Tests that filling partial parameters works as expected.
prop_fillWithPartialParams :: Property
prop_fillWithPartialParams =
  let partial = PartialTestParams (Just 4) Nothing
      filled = FilledTestParams 2 "42"
      expected = FilledTestParams 4 "42"
  in fillParams filled partial ==? expected

-- | Tests that filling partial parameters satisfies the law.
prop_fillPartialLaw1 :: FilledTestParams -> PartialTestParams -> Property
prop_fillPartialLaw1 = testFillParamsLaw1

-- | Tests that filling partial parameters works as expected.
prop_toParams :: Property
prop_toParams =
  let filled = FilledTestParams 2 "42"
      expected = FilledTestParams 4 "42"
  in toPartial (FilledTestParams 2 "42") ==?
     PartialTestParams (Just 2) (Just "42")

-- | Tests that filling partial parameters satisfies the law.
prop_fillPartialLaw2 :: FilledTestParams -> FilledTestParams -> Property
prop_fillPartialLaw2 = testToParamsLaw2

-- | Tests that filling partial parameters satisfies the law.
prop_fillPartialLaw3 :: FilledTestParams -> Property
prop_fillPartialLaw3 = testToFilledLaw3

-- | Tests that the monoid action laws are satisfied.
prop_fillPartialMonoidLaw1 :: FilledTestParams -> Property
prop_fillPartialMonoidLaw1 = testToFilledMonoidLaw1

-- | Tests that the monoid action laws are satisfied.
prop_fillPartialMonoidLaw2
  :: FilledTestParams -> PartialTestParams -> PartialTestParams -> Property
prop_fillPartialMonoidLaw2 = testToFilledMonoidLaw2

testSuite "THH"
            [ 'prop_OptFields
            , 'prop_TestObj_serialization
            , 'prop_TestObj_deserialisationFail
            , 'prop_UnitObj_serialization
            , 'prop_UnitObj_deserialisationFail
            , 'prop_fillWithPartialParams
            , 'prop_fillPartialLaw1
            , 'prop_toParams
            , 'prop_fillPartialLaw2
            , 'prop_fillPartialLaw3
            , 'prop_fillPartialMonoidLaw1
            , 'prop_fillPartialMonoidLaw2
            ]

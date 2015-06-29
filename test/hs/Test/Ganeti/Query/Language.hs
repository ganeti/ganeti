{-# LANGUAGE TemplateHaskell, FlexibleInstances #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

module Test.Ganeti.Query.Language
  ( testQuery_Language
  , genFilter
  , genJSValue
  ) where

import Test.HUnit (Assertion, assertEqual)
import Test.QuickCheck

import Control.Applicative
import Control.Arrow (second)
import Text.JSON

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.JSON
import Ganeti.Query.Language

{-# ANN module "HLint: ignore Use camelCase" #-}


instance Arbitrary (Filter FilterField) where
  arbitrary = genFilter

-- | Custom 'Filter' generator (top-level), which enforces a
-- (sane) limit on the depth of the generated filters.
genFilter :: Gen (Filter FilterField)
genFilter = choose (0, 10) >>= genFilter'

-- | Custom generator for filters that correctly halves the state of
-- the generators at each recursive step, per the QuickCheck
-- documentation, in order not to run out of memory.
genFilter' :: Int -> Gen (Filter FilterField)
genFilter' 0 =
  oneof [ pure EmptyFilter
        , TrueFilter     <$> genName
        , EQFilter       <$> genName <*> value
        , LTFilter       <$> genName <*> value
        , GTFilter       <$> genName <*> value
        , LEFilter       <$> genName <*> value
        , GEFilter       <$> genName <*> value
        , RegexpFilter   <$> genName <*> arbitrary
        , ContainsFilter <$> genName <*> value
        ]
    where value = oneof [ QuotedString <$> genName
                        , NumericValue <$> arbitrary
                        ]
genFilter' n =
  oneof [ AndFilter  <$> vectorOf n'' (genFilter' n')
        , OrFilter   <$> vectorOf n'' (genFilter' n')
        , NotFilter  <$> genFilter' n'
        ]
  where n' = n `div` 2 -- sub-filter generator size
        n'' = max n' 2 -- but we don't want empty or 1-element lists,
                       -- so use this for and/or filter list length

$(genArbitrary ''QueryTypeOp)

$(genArbitrary ''QueryTypeLuxi)

$(genArbitrary ''ItemType)

instance Arbitrary FilterRegex where
  arbitrary = genName >>= mkRegex -- a name should be a good regex

$(genArbitrary ''ResultStatus)

$(genArbitrary ''FieldType)

$(genArbitrary ''FieldDefinition)

-- | Generates an arbitrary JSValue. We do this via a function a not
-- via arbitrary instance since that would require us to define an
-- arbitrary for JSValue, which can be recursive, entering the usual
-- problems with that; so we only generate the base types, not the
-- recursive ones, and not 'JSNull', which we can't use in a
-- 'RSNormal' 'ResultEntry'.
genJSValue :: Gen JSValue
genJSValue =
  oneof [ JSBool <$> arbitrary
        , JSRational <$> pure False <*> arbitrary
        , JSString <$> (toJSString <$> arbitrary)
        , (JSArray . map showJSON) <$> (arbitrary::Gen [Int])
        , JSObject . toJSObject . map (second showJSON) <$>
          (arbitrary::Gen [(String, Int)])
        ]

-- | Generates a 'ResultEntry' value.
genResultEntry :: Gen ResultEntry
genResultEntry = do
  rs <- arbitrary
  rv <- case rs of
          RSNormal -> Just <$> genJSValue
          _ -> pure Nothing
  return $ ResultEntry rs rv

$(genArbitrary ''QueryFieldsResult)

-- | Tests that serialisation/deserialisation of filters is
-- idempotent.
prop_filter_serialisation :: Property
prop_filter_serialisation = forAll genFilter testSerialisation

-- | Tests that filter regexes are serialised correctly.
prop_filterregex_instances :: FilterRegex -> Property
prop_filterregex_instances rex =
  counterexample "failed JSON encoding" (testSerialisation rex)

-- | Tests 'ResultStatus' serialisation.
prop_resultstatus_serialisation :: ResultStatus -> Property
prop_resultstatus_serialisation = testSerialisation

-- | Tests 'FieldType' serialisation.
prop_fieldtype_serialisation :: FieldType -> Property
prop_fieldtype_serialisation = testSerialisation

-- | Tests 'FieldDef' serialisation.
prop_fielddef_serialisation :: FieldDefinition -> Property
prop_fielddef_serialisation = testSerialisation

-- | Tests 'ResultEntry' serialisation. Needed especially as this is
-- done manually, and not via buildObject (different serialisation
-- format).
prop_resultentry_serialisation :: Property
prop_resultentry_serialisation = forAll genResultEntry testSerialisation

-- | Tests 'FieldDef' serialisation. We use a made-up maximum limit of
-- 20 for the generator, since otherwise the lists become too long and
-- we don't care so much about list length but rather structure.
prop_fieldsresult_serialisation :: Property
prop_fieldsresult_serialisation =
  forAll (resize 20 arbitrary::Gen QueryFieldsResult) testSerialisation

-- | Tests 'ItemType' serialisation.
prop_itemtype_serialisation :: ItemType -> Property
prop_itemtype_serialisation = testSerialisation

-- | Tests basic cases of filter parsing, including legacy ones.
case_filterParsing :: Assertion
case_filterParsing = do
  let check :: String -> Filter String -> Assertion
      check str expected = do
        jsval <- fromJResult "could not parse filter" $ decode str
        assertEqual str expected jsval

      val = QuotedString "val"

  valRegex <- mkRegex "val"

  check "null" EmptyFilter
  check "[\"&\", null, null]"           $ AndFilter [EmptyFilter, EmptyFilter]
  check "[\"|\", null, null]"           $ OrFilter [EmptyFilter, EmptyFilter]
  check "[\"!\", null]"                 $ NotFilter EmptyFilter
  check "[\"?\",   \"field\"]"          $ TrueFilter "field"
  check "[\"==\",  \"field\", \"val\"]" $ EQFilter "field" val
  check "[\"<\",   \"field\", \"val\"]" $ LTFilter "field" val
  check "[\">\",   \"field\", \"val\"]" $ GTFilter "field" val
  check "[\"<=\",  \"field\", \"val\"]" $ LEFilter "field" val
  check "[\">=\",  \"field\", \"val\"]" $ GEFilter "field" val
  check "[\"=~\",  \"field\", \"val\"]" $ RegexpFilter "field" valRegex
  check "[\"=[]\", \"field\", \"val\"]" $ ContainsFilter "field" val
  -- Legacy filters
  check "[\"=\",   \"field\", \"val\"]" $ EQFilter "field" val
  check "[\"!=\",  \"field\", \"val\"]" $ NotFilter (EQFilter "field" val)

testSuite "Query/Language"
  [ 'prop_filter_serialisation
  , 'prop_filterregex_instances
  , 'prop_resultstatus_serialisation
  , 'prop_fieldtype_serialisation
  , 'prop_fielddef_serialisation
  , 'prop_resultentry_serialisation
  , 'prop_fieldsresult_serialisation
  , 'prop_itemtype_serialisation
  , 'case_filterParsing
  ]

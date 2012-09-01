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

module Test.Ganeti.Query.Language
  ( testQuery_Language
  , genFilter
  ) where

import Test.QuickCheck

import Control.Applicative
import Control.Arrow (second)
import Text.JSON

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.Query.Language

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
        , TrueFilter     <$> getName
        , EQFilter       <$> getName <*> value
        , LTFilter       <$> getName <*> value
        , GTFilter       <$> getName <*> value
        , LEFilter       <$> getName <*> value
        , GEFilter       <$> getName <*> value
        , RegexpFilter   <$> getName <*> arbitrary
        , ContainsFilter <$> getName <*> value
        ]
    where value = oneof [ QuotedString <$> getName
                        , NumericValue <$> arbitrary
                        ]
genFilter' n = do
  oneof [ AndFilter  <$> vectorOf n'' (genFilter' n')
        , OrFilter   <$> vectorOf n'' (genFilter' n')
        , NotFilter  <$> genFilter' n'
        ]
  where n' = n `div` 2 -- sub-filter generator size
        n'' = max n' 2 -- but we don't want empty or 1-element lists,
                       -- so use this for and/or filter list length

$(genArbitrary ''ItemType)

instance Arbitrary FilterRegex where
  arbitrary = getName >>= mkRegex -- a name should be a good regex

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
genJSValue = do
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
  printTestCase "failed JSON encoding" (testSerialisation rex) .&&.
  printTestCase "failed read/show instances" (read (show rex) ==? rex)

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

testSuite "Query/Language"
  [ 'prop_filter_serialisation
  , 'prop_filterregex_instances
  , 'prop_resultstatus_serialisation
  , 'prop_fieldtype_serialisation
  , 'prop_fielddef_serialisation
  , 'prop_resultentry_serialisation
  , 'prop_fieldsresult_serialisation
  ]

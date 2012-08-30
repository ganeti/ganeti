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

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.Query.Language as Qlang

-- | Custom 'Qlang.Filter' generator (top-level), which enforces a
-- (sane) limit on the depth of the generated filters.
genFilter :: Gen (Qlang.Filter Qlang.FilterField)
genFilter = choose (0, 10) >>= genFilter'

-- | Custom generator for filters that correctly halves the state of
-- the generators at each recursive step, per the QuickCheck
-- documentation, in order not to run out of memory.
genFilter' :: Int -> Gen (Qlang.Filter Qlang.FilterField)
genFilter' 0 =
  oneof [ return Qlang.EmptyFilter
        , Qlang.TrueFilter     <$> getName
        , Qlang.EQFilter       <$> getName <*> value
        , Qlang.LTFilter       <$> getName <*> value
        , Qlang.GTFilter       <$> getName <*> value
        , Qlang.LEFilter       <$> getName <*> value
        , Qlang.GEFilter       <$> getName <*> value
        , Qlang.RegexpFilter   <$> getName <*> arbitrary
        , Qlang.ContainsFilter <$> getName <*> value
        ]
    where value = oneof [ Qlang.QuotedString <$> getName
                        , Qlang.NumericValue <$> arbitrary
                        ]
genFilter' n = do
  oneof [ Qlang.AndFilter  <$> vectorOf n'' (genFilter' n')
        , Qlang.OrFilter   <$> vectorOf n'' (genFilter' n')
        , Qlang.NotFilter  <$> genFilter' n'
        ]
  where n' = n `div` 2 -- sub-filter generator size
        n'' = max n' 2 -- but we don't want empty or 1-element lists,
                       -- so use this for and/or filter list length

instance Arbitrary Qlang.ItemType where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Qlang.FilterRegex where
  arbitrary = getName >>= Qlang.mkRegex -- a name should be a good regex

-- | Tests that serialisation/deserialisation of filters is
-- idempotent.
prop_Serialisation :: Property
prop_Serialisation =
  forAll genFilter testSerialisation

prop_FilterRegex_instances :: Qlang.FilterRegex -> Property
prop_FilterRegex_instances rex =
  printTestCase "failed JSON encoding" (testSerialisation rex) .&&.
  printTestCase "failed read/show instances" (read (show rex) ==? rex)

testSuite "Query/Language"
  [ 'prop_Serialisation
  , 'prop_FilterRegex_instances
  ]

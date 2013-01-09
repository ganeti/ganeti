{-# LANGUAGE TemplateHaskell, CPP #-}
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

module Test.Ganeti.Utils (testUtils) where

import Test.QuickCheck hiding (Result)
import Test.HUnit

import Data.Char (isSpace)
import Data.List
import qualified Text.JSON as J
#ifndef NO_REGEX_PCRE
import Text.Regex.PCRE
#endif

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import qualified Ganeti.JSON as JSON
import Ganeti.Utils

-- | Helper to generate a small string that doesn't contain commas.
genNonCommaString :: Gen String
genNonCommaString = do
  size <- choose (0, 20) -- arbitrary max size
  vectorOf size (arbitrary `suchThat` (/=) ',')

-- | If the list is not just an empty element, and if the elements do
-- not contain commas, then join+split should be idempotent.
prop_commaJoinSplit :: Property
prop_commaJoinSplit =
  forAll (choose (0, 20)) $ \llen ->
  forAll (vectorOf llen genNonCommaString `suchThat` (/=) [""]) $ \lst ->
  sepSplit ',' (commaJoin lst) ==? lst

-- | Split and join should always be idempotent.
prop_commaSplitJoin :: String -> Property
prop_commaSplitJoin s =
  commaJoin (sepSplit ',' s) ==? s

-- | fromObjWithDefault, we test using the Maybe monad and an integer
-- value.
prop_fromObjWithDefault :: Integer -> String -> Bool
prop_fromObjWithDefault def_value random_key =
  -- a missing key will be returned with the default
  JSON.fromObjWithDefault [] random_key def_value == Just def_value &&
  -- a found key will be returned as is, not with default
  JSON.fromObjWithDefault [(random_key, J.showJSON def_value)]
       random_key (def_value+1) == Just def_value

-- | Test that functional if' behaves like the syntactic sugar if.
prop_if'if :: Bool -> Int -> Int -> Gen Prop
prop_if'if cnd a b =
  if' cnd a b ==? if cnd then a else b

-- | Test basic select functionality
prop_select :: Int      -- ^ Default result
            -> [Int]    -- ^ List of False values
            -> [Int]    -- ^ List of True values
            -> Gen Prop -- ^ Test result
prop_select def lst1 lst2 =
  select def (flist ++ tlist) ==? expectedresult
    where expectedresult = if' (null lst2) def (head lst2)
          flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2

-- | Test basic select functionality with undefined default
prop_select_undefd :: [Int]            -- ^ List of False values
                   -> NonEmptyList Int -- ^ List of True values
                   -> Gen Prop         -- ^ Test result
prop_select_undefd lst1 (NonEmpty lst2) =
  select undefined (flist ++ tlist) ==? head lst2
    where flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2

-- | Test basic select functionality with undefined list values
prop_select_undefv :: [Int]            -- ^ List of False values
                   -> NonEmptyList Int -- ^ List of True values
                   -> Gen Prop         -- ^ Test result
prop_select_undefv lst1 (NonEmpty lst2) =
  select undefined cndlist ==? head lst2
    where flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2
          cndlist = flist ++ tlist ++ [undefined]

prop_parseUnit :: NonNegative Int -> Property
prop_parseUnit (NonNegative n) =
  conjoin
  [ parseUnit (show n) ==? (Ok n::Result Int)
  , parseUnit (show n ++ "m") ==? (Ok n::Result Int)
  , parseUnit (show n ++ "M") ==? (Ok (truncate n_mb)::Result Int)
  , parseUnit (show n ++ "g") ==? (Ok (n*1024)::Result Int)
  , parseUnit (show n ++ "G") ==? (Ok (truncate n_gb)::Result Int)
  , parseUnit (show n ++ "t") ==? (Ok (n*1048576)::Result Int)
  , parseUnit (show n ++ "T") ==? (Ok (truncate n_tb)::Result Int)
  , printTestCase "Internal error/overflow?"
    (n_mb >=0 && n_gb >= 0 && n_tb >= 0)
  , property (isBad (parseUnit (show n ++ "x")::Result Int))
  ]
  where n_mb = (fromIntegral n::Rational) * 1000 * 1000 / 1024 / 1024
        n_gb = n_mb * 1000
        n_tb = n_gb * 1000

{-# ANN case_niceSort_static "HLint: ignore Use camelCase" #-}

case_niceSort_static :: Assertion
case_niceSort_static = do
  assertEqual "empty list" [] $ niceSort []
  assertEqual "punctuation" [",", "."] $ niceSort [",", "."]
  assertEqual "decimal numbers" ["0.1", "0.2"] $ niceSort ["0.1", "0.2"]
  assertEqual "various numbers" ["0,099", "0.1", "0.2", "0;099"] $
              niceSort ["0;099", "0,099", "0.1", "0.2"]

  assertEqual "simple concat" ["0000", "a0", "a1", "a2", "a20", "a99",
                               "b00", "b10", "b70"] $
    niceSort ["a0", "a1", "a99", "a20", "a2", "b10", "b70", "b00", "0000"]

  assertEqual "ranges" ["A", "Z", "a0-0", "a0-4", "a1-0", "a9-1", "a09-2",
                      "a20-3", "a99-3", "a99-10", "b"] $
    niceSort ["a0-0", "a1-0", "a99-10", "a20-3", "a0-4", "a99-3", "a09-2",
              "Z", "a9-1", "A", "b"]

  assertEqual "large"
    ["3jTwJPtrXOY22bwL2YoW", "Eegah9ei", "KOt7vn1dWXi",
     "KVQqLPDjcPjf8T3oyzjcOsfkb", "WvNJd91OoXvLzdEiEXa6",
     "Z8Ljf1Pf5eBfNg171wJR", "a07h8feON165N67PIE", "bH4Q7aCu3PUPjK3JtH",
     "cPRi0lM7HLnSuWA2G9", "guKJkXnkULealVC8CyF1xefym",
     "pqF8dkU5B1cMnyZuREaSOADYx", "uHXAyYYftCSG1o7qcCqe",
     "xij88brTulHYAv8IEOyU", "xpIUJeVT1Rp"] $
    niceSort ["Eegah9ei", "xij88brTulHYAv8IEOyU", "3jTwJPtrXOY22bwL2YoW",
             "Z8Ljf1Pf5eBfNg171wJR", "WvNJd91OoXvLzdEiEXa6",
             "uHXAyYYftCSG1o7qcCqe", "xpIUJeVT1Rp", "KOt7vn1dWXi",
             "a07h8feON165N67PIE", "bH4Q7aCu3PUPjK3JtH",
             "cPRi0lM7HLnSuWA2G9", "KVQqLPDjcPjf8T3oyzjcOsfkb",
             "guKJkXnkULealVC8CyF1xefym", "pqF8dkU5B1cMnyZuREaSOADYx"]

-- | Tests single-string behaviour of 'niceSort'. Last test is special
-- in the sense that /0/ is before any other non-empty string (except
-- itself, etc.).
prop_niceSort_single :: Property
prop_niceSort_single =
  forAll genName $ \name ->
  conjoin
  [ printTestCase "single string" $ [name] ==? niceSort [name]
  , printTestCase "single plus empty" $ ["", name] ==? niceSort [name, ""]
  , printTestCase "single plus 0-digit" $ ["0", name] ==? niceSort [name, "0"]
  ]

-- | Tests some generic 'niceSort' properties. Note that the last test
-- must add a non-digit prefix; a digit one might change ordering.
prop_niceSort_generic :: Property
prop_niceSort_generic =
  forAll (resize 20 arbitrary) $ \names ->
  let n_sorted = niceSort names in
  conjoin [ printTestCase "length" $ length names ==? length n_sorted
          , printTestCase "same strings" $ sort names ==? sort n_sorted
          , printTestCase "idempotence" $ n_sorted ==? niceSort n_sorted
          , printTestCase "static prefix" $ n_sorted ==?
              map tail (niceSort $ map (" "++) names)
          ]

-- | Tests that niceSorting numbers is identical to actual sorting
-- them (in numeric form).
prop_niceSort_numbers :: Property
prop_niceSort_numbers =
  forAll (listOf (arbitrary::Gen (NonNegative Int))) $ \numbers ->
  map show (sort numbers) ==? niceSort (map show numbers)

-- | Tests that 'niceSort' and 'niceSortKey' are equivalent.
prop_niceSortKey_equiv :: Property
prop_niceSortKey_equiv =
  forAll (resize 20 arbitrary) $ \names ->
  forAll (vectorOf (length names) (arbitrary::Gen Int)) $ \numbers ->
  let n_sorted = niceSort names in
  conjoin
  [ printTestCase "key id" $ n_sorted ==? niceSortKey id names
  , printTestCase "key rev" $ niceSort (map reverse names) ==?
                              map reverse (niceSortKey reverse names)
  , printTestCase "key snd" $ n_sorted ==? map snd (niceSortKey snd $
                                                    zip numbers names)
  ]

-- | Tests 'rStripSpace'.
prop_rStripSpace :: NonEmptyList Char -> Property
prop_rStripSpace (NonEmpty str) =
  forAll (resize 50 $ listOf1 (arbitrary `suchThat` isSpace)) $ \whitespace ->
  conjoin [ printTestCase "arb. string last char is not space" $
              case rStripSpace str of
                [] -> True
                xs -> not . isSpace $ last xs
          , printTestCase "whitespace suffix is stripped" $
              rStripSpace str ==? rStripSpace (str ++ whitespace)
          , printTestCase "whitespace reduced to null" $
              rStripSpace whitespace ==? ""
          , printTestCase "idempotent on empty strings" $
              rStripSpace "" ==? ""
          ]

#ifndef NO_REGEX_PCRE
{-# ANN case_new_uuid "HLint: ignore Use camelCase" #-}

-- | Tests that the newUUID function produces valid UUIDs.
case_new_uuid :: Assertion
case_new_uuid = do
  uuid <- newUUID
  assertBool "newUUID" $ uuid =~ C.uuidRegex
#endif

-- | Test list for the Utils module.
testSuite "Utils"
            [ 'prop_commaJoinSplit
            , 'prop_commaSplitJoin
            , 'prop_fromObjWithDefault
            , 'prop_if'if
            , 'prop_select
            , 'prop_select_undefd
            , 'prop_select_undefv
            , 'prop_parseUnit
            , 'case_niceSort_static
            , 'prop_niceSort_single
            , 'prop_niceSort_generic
            , 'prop_niceSort_numbers
            , 'prop_niceSortKey_equiv
            , 'prop_rStripSpace
#ifndef NO_REGEX_PCRE
            , 'case_new_uuid
#endif
            ]

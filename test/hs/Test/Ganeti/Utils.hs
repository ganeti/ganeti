{-# LANGUAGE TemplateHaskell, CPP, ScopedTypeVariables #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Test.Ganeti.Utils (testUtils) where

import Test.QuickCheck hiding (Result)
import Test.HUnit

import Control.Applicative ((<$>), (<*>))
import Data.Char (isSpace)
import qualified Data.Either as Either
import Data.List
import Data.Maybe (listToMaybe)
import qualified Data.Set as S
import System.Time
import qualified Text.JSON as J
#ifdef VERSION_regex_pcre
import Text.Regex.PCRE
#endif

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import qualified Ganeti.JSON as JSON
import Ganeti.Utils

{-# ANN module "HLint: ignore Use camelCase" #-}


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

-- | Test 'findFirst' on several possible inputs.
prop_findFirst :: Property
prop_findFirst =
  forAll (genSublist [0..5 :: Int]) $ \xs ->
  forAll (choose (-2, 7)) $ \base ->
  counterexample "findFirst utility function" $
  let r = findFirst base (S.fromList xs)
      (ss, es) = partition (< r) $ dropWhile (< base) xs
      -- the prefix must be a range of numbers
      -- and the suffix must not start with 'r'
   in conjoin [ and $ zipWith ((==) . (+ 1)) ss (drop 1 ss)
              , maybe True (> r) (listToMaybe es)
              ]


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
prop_if'if :: Bool -> Int -> Int -> Property
prop_if'if cnd a b =
  if' cnd a b ==? if cnd then a else b

-- | Test basic select functionality
prop_select :: Int      -- ^ Default result
            -> [Int]    -- ^ List of False values
            -> [Int]    -- ^ List of True values
            -> Property -- ^ Test result
prop_select def lst1 lst2 =
  select def (flist ++ tlist) ==? expectedresult
    where expectedresult = defaultHead def lst2
          flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2

{-# ANN prop_select_undefd "HLint: ignore Use alternative" #-}
-- | Test basic select functionality with undefined default
prop_select_undefd :: [Int]            -- ^ List of False values
                   -> NonEmptyList Int -- ^ List of True values
                   -> Property         -- ^ Test result
prop_select_undefd lst1 (NonEmpty lst2) =
  -- head is fine as NonEmpty "guarantees" a non-empty list, but not
  -- via types
  select undefined (flist ++ tlist) ==? head lst2
    where flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2

{-# ANN prop_select_undefv "HLint: ignore Use alternative" #-}
-- | Test basic select functionality with undefined list values
prop_select_undefv :: [Int]            -- ^ List of False values
                   -> NonEmptyList Int -- ^ List of True values
                   -> Property         -- ^ Test result
prop_select_undefv lst1 (NonEmpty lst2) =
  -- head is fine as NonEmpty "guarantees" a non-empty list, but not
  -- via types
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
  , counterexample "Internal error/overflow?"
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

  assertEqual "hostnames"
    ["host1.example.com", "host2.example.com", "host03.example.com",
     "host11.example.com", "host255.example.com"] $
    niceSort ["host2.example.com", "host11.example.com", "host03.example.com",
     "host1.example.com", "host255.example.com"]

-- | Tests single-string behaviour of 'niceSort'.
prop_niceSort_single :: Property
prop_niceSort_single =
  forAll genName $ \name ->
  conjoin
  [ counterexample "single string" $ [name] ==? niceSort [name]
  , counterexample "single plus empty" $ ["", name] ==? niceSort [name, ""]
  ]

-- | Tests some generic 'niceSort' properties. Note that the last test
-- must add a non-digit prefix; a digit one might change ordering.
prop_niceSort_generic :: Property
prop_niceSort_generic =
  forAll (resize 20 arbitrary) $ \names ->
  let n_sorted = niceSort names in
  conjoin [ counterexample "length" $ length names ==? length n_sorted
          , counterexample "same strings" $ sort names ==? sort n_sorted
          , counterexample "idempotence" $ n_sorted ==? niceSort n_sorted
          , counterexample "static prefix" $ n_sorted ==?
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
  [ counterexample "key id" $ n_sorted ==? niceSortKey id names
  , counterexample "key rev" $ niceSort (map reverse names) ==?
                               map reverse (niceSortKey reverse names)
  , counterexample "key snd" $ n_sorted ==? map snd (niceSortKey snd $
                                                     zip numbers names)
  ]

-- | Tests 'rStripSpace'.
prop_rStripSpace :: NonEmptyList Char -> Property
prop_rStripSpace (NonEmpty str) =
  forAll (resize 50 $ listOf1 (arbitrary `suchThat` isSpace)) $ \whitespace ->
  conjoin [ counterexample "arb. string last char is not space" $
              case rStripSpace str of
                [] -> True
                xs -> not . isSpace $ last xs
          , counterexample "whitespace suffix is stripped" $
              rStripSpace str ==? rStripSpace (str ++ whitespace)
          , counterexample "whitespace reduced to null" $
              rStripSpace whitespace ==? ""
          , counterexample "idempotent on empty strings" $
              rStripSpace "" ==? ""
          ]

-- | Tests that the newUUID function produces valid UUIDs.
case_new_uuid :: Assertion
case_new_uuid = do
  uuid <- newUUID
  assertBool "newUUID" $ isUUID uuid

#ifdef VERSION_regex_pcre
{-# ANN case_new_uuid_regex "HLint: ignore Use camelCase" #-}

-- | Tests that the newUUID function produces valid UUIDs.
case_new_uuid_regex :: Assertion
case_new_uuid_regex = do
  uuid <- newUUID
  assertBool "newUUID" $ uuid =~ C.uuidRegex
#endif

prop_clockTimeToString :: Integer -> Integer -> Property
prop_clockTimeToString ts pico =
  clockTimeToString (TOD ts pico) ==? show ts

instance Arbitrary ClockTime where
  arbitrary = TOD <$> choose (946681200, 2082754800) <*> choose (0, 99999999999)

-- | Verify our work-around for ghc bug #2519. Taking `diffClockTimes` form
-- `System.Time`, this test fails with an exception.
prop_timediffAdd :: ClockTime -> ClockTime -> ClockTime -> Property
prop_timediffAdd a b c =
  let fwd = Ganeti.Utils.diffClockTimes a b
      back = Ganeti.Utils.diffClockTimes b a
  in addToClockTime fwd (addToClockTime back c) ==? c

-- | Test normal operation for 'chompPrefix'.
--
-- Any random prefix of a string must be stripped correctly, including the empty
-- prefix, and the whole string.
prop_chompPrefix_normal :: String -> Property
prop_chompPrefix_normal str =
  forAll (choose (0, length str)) $ \size ->
  chompPrefix (take size str) str ==? (Just $ drop size str)

-- | Test that 'chompPrefix' correctly allows the last char (the separator) to
-- be absent if the string terminates there.
prop_chompPrefix_last :: Property
prop_chompPrefix_last =
  forAll (choose (1, 20)) $ \len ->
  forAll (vectorOf len arbitrary) $ \pfx ->
  chompPrefix pfx pfx ==? Just "" .&&.
  chompPrefix pfx (init pfx) ==? Just ""

-- | Test that chompPrefix on the empty string always returns Nothing for
-- prefixes of length 2 or more.
prop_chompPrefix_empty_string :: Property
prop_chompPrefix_empty_string =
  forAll (choose (2, 20)) $ \len ->
  forAll (vectorOf len arbitrary) $ \pfx ->
  chompPrefix pfx "" ==? Nothing

-- | Test 'chompPrefix' returns Nothing when the prefix doesn't match.
prop_chompPrefix_nothing :: Property
prop_chompPrefix_nothing =
  forAll (choose (1, 20)) $ \len ->
  forAll (vectorOf len arbitrary) $ \pfx ->
  forAll (arbitrary `suchThat`
          (\s -> not (pfx `isPrefixOf` s) && s /= init pfx)) $ \str ->
  chompPrefix pfx str ==? Nothing

-- | Tests 'trim'.
prop_trim :: NonEmptyList Char -> Property
prop_trim (NonEmpty str) =
  forAll (listOf1 $ elements " \t\n\r\f") $ \whitespace ->
  forAll (choose (0, length whitespace)) $ \n ->
  let (preWS, postWS) = splitAt n whitespace in
  conjoin [ counterexample "arb. string first and last char are not space" $
              case trim str of
                [] -> True
                xs -> (not . isSpace . head) xs && (not . isSpace . last) xs
          , counterexample "whitespace is striped" $
              trim str ==? trim (preWS ++ str ++ postWS)
          , counterexample "whitespace reduced to null" $
              trim whitespace ==? ""
          , counterexample "idempotent on empty strings" $
              trim "" ==? ""
          ]

-- | Tests 'splitEithers' and 'recombineEithers'.
prop_splitRecombineEithers :: [Either Int Int] -> Property
prop_splitRecombineEithers es =
  conjoin
  [ counterexample "only lefts are mapped correctly" $
    splitEithers (map Left lefts) ==? (reverse lefts, emptylist, falses)
  , counterexample "only rights are mapped correctly" $
    splitEithers (map Right rights) ==? (emptylist, reverse rights, trues)
  , counterexample "recombination is no-op" $
    recombineEithers splitleft splitright trail ==? Ok es
  , counterexample "fail on too long lefts" $
    isBad (recombineEithers (0:splitleft) splitright trail)
  , counterexample "fail on too long rights" $
    isBad (recombineEithers splitleft (0:splitright) trail)
  , counterexample "fail on too long trail" $
    isBad (recombineEithers splitleft splitright (True:trail))
  ]
  where (lefts, rights) = Either.partitionEithers es
        falses = map (const False) lefts
        trues = map (const True) rights
        (splitleft, splitright, trail) = splitEithers es
        emptylist = []::[Int]

-- | Tests 'isSubsequenceOf'.
prop_isSubsequenceOf :: Property
prop_isSubsequenceOf = do
  -- isSubsequenceOf only has access to Eq so restricting to a small
  -- set of numbers and short lists still covers everything it can do.
  let num = choose (0, 5)
  forAll (choose (0, 4)) $ \n1 ->
    forAll (choose (0, 4)) $ \n2 ->
      forAll (vectorOf n1 num) $ \(a :: [Int]) ->
        forAll (vectorOf n2 num) $ \b ->
          let subs = S.fromList $ subsequences b
          in a `isSubsequenceOf` b == a `S.member` subs

testSuite "Utils"
            [ 'prop_commaJoinSplit
            , 'prop_commaSplitJoin
            , 'prop_findFirst
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
            , 'prop_trim
            , 'case_new_uuid
#ifdef VERSION_regex_pcre
            , 'case_new_uuid_regex
#endif
            , 'prop_clockTimeToString
            , 'prop_timediffAdd
            , 'prop_chompPrefix_normal
            , 'prop_chompPrefix_last
            , 'prop_chompPrefix_empty_string
            , 'prop_chompPrefix_nothing
            , 'prop_splitRecombineEithers
            , 'prop_isSubsequenceOf
            ]

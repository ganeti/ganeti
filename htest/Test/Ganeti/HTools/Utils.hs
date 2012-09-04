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

module Test.Ganeti.HTools.Utils (testHTools_Utils) where

import Test.QuickCheck

import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.JSON as JSON
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Utils as Utils

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
  Utils.sepSplit ',' (Utils.commaJoin lst) ==? lst

-- | Split and join should always be idempotent.
prop_commaSplitJoin :: String -> Property
prop_commaSplitJoin s =
  Utils.commaJoin (Utils.sepSplit ',' s) ==? s

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
  Utils.if' cnd a b ==? if cnd then a else b

-- | Test basic select functionality
prop_select :: Int      -- ^ Default result
            -> [Int]    -- ^ List of False values
            -> [Int]    -- ^ List of True values
            -> Gen Prop -- ^ Test result
prop_select def lst1 lst2 =
  Utils.select def (flist ++ tlist) ==? expectedresult
    where expectedresult = Utils.if' (null lst2) def (head lst2)
          flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2

-- | Test basic select functionality with undefined default
prop_select_undefd :: [Int]            -- ^ List of False values
                   -> NonEmptyList Int -- ^ List of True values
                   -> Gen Prop         -- ^ Test result
prop_select_undefd lst1 (NonEmpty lst2) =
  Utils.select undefined (flist ++ tlist) ==? head lst2
    where flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2

-- | Test basic select functionality with undefined list values
prop_select_undefv :: [Int]            -- ^ List of False values
                   -> NonEmptyList Int -- ^ List of True values
                   -> Gen Prop         -- ^ Test result
prop_select_undefv lst1 (NonEmpty lst2) =
  Utils.select undefined cndlist ==? head lst2
    where flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2
          cndlist = flist ++ tlist ++ [undefined]

prop_parseUnit :: NonNegative Int -> Property
prop_parseUnit (NonNegative n) =
  Utils.parseUnit (show n) ==? Types.Ok n .&&.
  Utils.parseUnit (show n ++ "m") ==? Types.Ok n .&&.
  Utils.parseUnit (show n ++ "M") ==? Types.Ok (truncate n_mb::Int) .&&.
  Utils.parseUnit (show n ++ "g") ==? Types.Ok (n*1024) .&&.
  Utils.parseUnit (show n ++ "G") ==? Types.Ok (truncate n_gb::Int) .&&.
  Utils.parseUnit (show n ++ "t") ==? Types.Ok (n*1048576) .&&.
  Utils.parseUnit (show n ++ "T") ==? Types.Ok (truncate n_tb::Int) .&&.
  printTestCase "Internal error/overflow?"
    (n_mb >=0 && n_gb >= 0 && n_tb >= 0) .&&.
  property (Types.isBad (Utils.parseUnit (show n ++ "x")::Types.Result Int))
  where n_mb = (fromIntegral n::Rational) * 1000 * 1000 / 1024 / 1024
        n_gb = n_mb * 1000
        n_tb = n_gb * 1000

-- | Test list for the Utils module.
testSuite "HTools/Utils"
            [ 'prop_commaJoinSplit
            , 'prop_commaSplitJoin
            , 'prop_fromObjWithDefault
            , 'prop_if'if
            , 'prop_select
            , 'prop_select_undefd
            , 'prop_select_undefv
            , 'prop_parseUnit
            ]

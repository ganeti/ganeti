{-# LANGUAGE TemplateHaskell #-}
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

module Test.Ganeti.JSON (testJSON) where

import Control.Monad
import Data.List
import Test.HUnit
import Test.QuickCheck

import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Types ()

import qualified Ganeti.BasicTypes as BasicTypes
import Ganeti.JSON (nestedAccessByKey, nestedAccessByKeyDotted)
import qualified Ganeti.JSON as JSON

{-# ANN module "HLint: ignore Use camelCase" #-}

instance (Arbitrary a) => Arbitrary (JSON.MaybeForJSON a) where
  arbitrary = liftM JSON.MaybeForJSON arbitrary

instance Arbitrary JSON.TimeAsDoubleJSON where
  arbitrary = liftM JSON.TimeAsDoubleJSON arbitrary

prop_toArray :: [Int] -> Property
prop_toArray intarr =
  let arr = map J.showJSON intarr in
  case JSON.toArray (J.JSArray arr) of
    BasicTypes.Ok arr' -> arr ==? arr'
    BasicTypes.Bad err -> failTest $ "Failed to parse array: " ++ err

prop_toArrayFail :: Int -> String -> Bool -> Property
prop_toArrayFail i s b =
  -- poor man's instance Arbitrary JSValue
  forAll (elements [J.showJSON i, J.showJSON s, J.showJSON b]) $ \item ->
  case JSON.toArray item::BasicTypes.Result [J.JSValue] of
    BasicTypes.Bad _ -> passTest
    BasicTypes.Ok result -> failTest $ "Unexpected parse, got " ++ show result

arrayMaybeToJson :: (J.JSON a) => [Maybe a] -> String -> JSON.JSRecord
arrayMaybeToJson xs k = [(k, J.JSArray $ map sh xs)]
  where
    sh x = case x of
      Just v -> J.showJSON v
      Nothing -> J.JSNull

prop_arrayMaybeFromObj :: String -> [Maybe Int] -> String -> Property
prop_arrayMaybeFromObj t xs k =
  case JSON.tryArrayMaybeFromObj t (arrayMaybeToJson xs k) k of
    BasicTypes.Ok xs' -> xs' ==? xs
    BasicTypes.Bad e -> failTest $ "Parsing failing, got: " ++ show e

prop_arrayMaybeFromObjFail :: String -> String -> Property
prop_arrayMaybeFromObjFail t k =
  case JSON.tryArrayMaybeFromObj t [] k of
    BasicTypes.Ok r -> property
      (fail $ "Unexpected result, got: " ++ show (r::[Maybe Int])
         :: Gen Property)
    BasicTypes.Bad e -> conjoin [ Data.List.isInfixOf t e ==? True
                                , Data.List.isInfixOf k e ==? True
                                ]

prop_MaybeForJSON_serialisation :: JSON.MaybeForJSON String -> Property
prop_MaybeForJSON_serialisation = testSerialisation

prop_TimeAsDoubleJSON_serialisation :: JSON.TimeAsDoubleJSON -> Property
prop_TimeAsDoubleJSON_serialisation = testSerialisation

isJError :: J.Result a -> Bool
isJError (J.Error _) = True
isJError _           = False

case_nestedAccessByKey :: Assertion
case_nestedAccessByKey = do
  J.Ok v <- return $ J.decode "{\"key1\": {\"key2\": \"val\"}}"

  nestedAccessByKey [] v @?= J.Ok v

  nestedAccessByKey ["key1", "key2"] v
    @?= J.Ok (J.JSString $ J.toJSString "val")

  assertBool "access to nonexistent key should fail"
    . isJError $ nestedAccessByKey ["key1", "nonexistent"] v

case_nestedAccessByKeyDotted :: Assertion
case_nestedAccessByKeyDotted = do
  J.Ok v <- return $ J.decode "{\"key1\": {\"key2\": \"val\"}}"

  assertBool "access to empty key should fail"
    . isJError $ nestedAccessByKeyDotted "" v

  nestedAccessByKeyDotted "key1.key2" v
    @?= J.Ok (J.JSString $ J.toJSString "val")

  assertBool "access to nonexistent key should fail"
    . isJError $ nestedAccessByKeyDotted "key1.nonexistent" v

testSuite "JSON"
          [ 'prop_toArray
          , 'prop_toArrayFail
          , 'prop_arrayMaybeFromObj
          , 'prop_arrayMaybeFromObjFail
          , 'prop_MaybeForJSON_serialisation
          , 'prop_TimeAsDoubleJSON_serialisation
          , 'case_nestedAccessByKey
          , 'case_nestedAccessByKeyDotted
          ]

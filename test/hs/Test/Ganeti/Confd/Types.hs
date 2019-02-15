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

module Test.Ganeti.Confd.Types
  ( testConfd_Types
  , ConfdRequestType(..)
  , ConfdReqField(..)
  , ConfdReqQ(..)
  ) where

import Control.Applicative
import Test.QuickCheck
import Test.HUnit
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.Confd.Types as Confd

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitrary instances

$(genArbitrary ''ConfdRequestType)

$(genArbitrary ''ConfdReqField)

$(genArbitrary ''ConfdReqQ)

instance Arbitrary ConfdQuery where
  arbitrary = oneof [ pure EmptyQuery
                    , PlainQuery <$> genName
                    , DictQuery <$> arbitrary
                    ]

$(genArbitrary ''ConfdRequest)

$(genArbitrary ''ConfdReplyStatus)

instance Arbitrary ConfdReply where
  arbitrary = ConfdReply <$> arbitrary <*> arbitrary <*>
                pure J.JSNull <*> arbitrary

$(genArbitrary ''ConfdErrorType)

$(genArbitrary ''ConfdNodeRole)

-- * Test cases

-- | Test 'ConfdQuery' serialisation.
prop_ConfdQuery_serialisation :: ConfdQuery -> Property
prop_ConfdQuery_serialisation = testSerialisation

-- | Test bad types deserialisation for 'ConfdQuery'.
case_ConfdQuery_BadTypes :: Assertion
case_ConfdQuery_BadTypes = do
  let helper jsval = case J.readJSON jsval of
                       J.Error _ -> return ()
                       J.Ok cq -> assertFailure $ "Parsed " ++ show jsval
                                   ++ " as query " ++ show (cq::ConfdQuery)
  helper $ J.showJSON (1::Int)
  helper $ J.JSBool True
  helper $ J.JSBool False
  helper $ J.JSArray []


-- | Test 'ConfdReplyStatus' serialisation.
prop_ConfdReplyStatus_serialisation :: ConfdReplyStatus -> Property
prop_ConfdReplyStatus_serialisation = testSerialisation

-- | Test 'ConfdReply' serialisation.
prop_ConfdReply_serialisation :: ConfdReply -> Property
prop_ConfdReply_serialisation = testSerialisation

-- | Test 'ConfdErrorType' serialisation.
prop_ConfdErrorType_serialisation :: ConfdErrorType -> Property
prop_ConfdErrorType_serialisation = testSerialisation

-- | Test 'ConfdNodeRole' serialisation.
prop_ConfdNodeRole_serialisation :: ConfdNodeRole -> Property
prop_ConfdNodeRole_serialisation = testSerialisation

testSuite "Confd/Types"
  [ 'prop_ConfdQuery_serialisation
  , 'case_ConfdQuery_BadTypes
  , 'prop_ConfdReplyStatus_serialisation
  , 'prop_ConfdReply_serialisation
  , 'prop_ConfdErrorType_serialisation
  , 'prop_ConfdNodeRole_serialisation
  ]

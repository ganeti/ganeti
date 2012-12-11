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

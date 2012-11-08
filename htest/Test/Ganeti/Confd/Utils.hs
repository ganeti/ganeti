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

module Test.Ganeti.Confd.Utils (testConfd_Utils) where

import Control.Applicative
import Test.QuickCheck
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.BasicTypes as BasicTypes
import qualified Ganeti.Confd.Types as Confd
import qualified Ganeti.Confd.Utils as Confd.Utils
import qualified Ganeti.Constants as C
import qualified Ganeti.Hash as Hash

$(genArbitrary ''Confd.ConfdRequestType)

$(genArbitrary ''Confd.ConfdReqField)

$(genArbitrary ''Confd.ConfdReqQ)

instance Arbitrary Confd.ConfdQuery where
  arbitrary = oneof [ pure Confd.EmptyQuery
                    , Confd.PlainQuery <$> getName
                    , Confd.DictQuery <$> arbitrary
                    ]

$(genArbitrary ''Confd.ConfdRequest)

-- | Test that signing messages and checking signatures is correct. It
-- also tests, indirectly the serialisation of messages so we don't
-- need a separate test for that.
prop_req_sign :: Hash.HashKey        -- ^ The hash key
              -> NonNegative Integer -- ^ The base timestamp
              -> Positive Integer    -- ^ Delta for out of window
              -> Bool                -- ^ Whether delta should be + or -
              -> Confd.ConfdRequest
              -> Property
prop_req_sign key (NonNegative timestamp) (Positive bad_delta)
                         pm crq =
  forAll (choose (0, fromIntegral C.confdMaxClockSkew)) $ \ good_delta ->
  let encoded = J.encode crq
      salt = show timestamp
      signed = J.encode $ Confd.Utils.signMessage key salt encoded
      good_timestamp = timestamp + if pm then good_delta else (-good_delta)
      bad_delta' = fromIntegral C.confdMaxClockSkew + bad_delta
      bad_timestamp = timestamp + if pm then bad_delta' else (-bad_delta')
      ts_ok = Confd.Utils.parseMessage key signed good_timestamp
      ts_bad = Confd.Utils.parseMessage key signed bad_timestamp
  in printTestCase "Failed to parse good message"
       (ts_ok ==? BasicTypes.Ok (encoded, crq)) .&&.
     printTestCase ("Managed to deserialise message with bad\
                    \ timestamp, got " ++ show ts_bad)
       (ts_bad ==? BasicTypes.Bad "Too old/too new timestamp or clock skew")

-- | Tests that signing with a different key fails detects failure
-- correctly.
prop_bad_key :: String             -- ^ Salt
             -> Confd.ConfdRequest -- ^ Request
             -> Property
prop_bad_key salt crq =
  -- fixme: we hardcode here the expected length of a sha1 key, as
  -- otherwise we could have two short keys that differ only in the
  -- final zero elements count, and those will be expanded to be the
  -- same
  forAll (vector 20) $ \key_sign ->
  forAll (vector 20 `suchThat` (/= key_sign)) $ \key_verify ->
  let signed = Confd.Utils.signMessage key_sign salt (J.encode crq)
      encoded = J.encode signed
  in printTestCase ("Accepted message signed with different key" ++ encoded) $
     Confd.Utils.parseRequest key_verify encoded ==?
       BasicTypes.Bad "HMAC verification failed"

testSuite "Confd/Utils"
  [ 'prop_req_sign
  , 'prop_bad_key
  ]

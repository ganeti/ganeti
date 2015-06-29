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

module Test.Ganeti.Confd.Utils (testConfd_Utils) where

import Test.QuickCheck
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Confd.Types ()

import qualified Ganeti.BasicTypes as BasicTypes
import qualified Ganeti.Confd.Types as Confd
import qualified Ganeti.Confd.Utils as Confd.Utils
import qualified Ganeti.Constants as C
import qualified Ganeti.Hash as Hash

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
      ts_ok = Confd.Utils.parseRequest key signed good_timestamp
      ts_bad = Confd.Utils.parseRequest key signed bad_timestamp
  in counterexample "Failed to parse good message"
       (ts_ok ==? BasicTypes.Ok (encoded, crq)) .&&.
     counterexample ("Managed to deserialise message with bad\
                     \ timestamp, got " ++ show ts_bad)
       (ts_bad ==? BasicTypes.Bad "Too old/too new timestamp or clock skew")

-- | Tests that a ConfdReply can be properly encoded, signed and parsed using
-- the proper salt, but fails parsing with the wrong salt.
prop_rep_salt :: Hash.HashKey     -- ^ The hash key
              -> Confd.ConfdReply -- ^ A Confd reply
              -> Property
prop_rep_salt hmac reply =
  forAll arbitrary $ \salt1 ->
  forAll (arbitrary `suchThat` (/= salt1)) $ \salt2 ->
  let innerMsg = J.encode reply
      msg = J.encode $ Confd.Utils.signMessage hmac salt1 innerMsg
  in
    Confd.Utils.parseReply hmac msg salt1 ==? BasicTypes.Ok (innerMsg, reply)
      .&&. Confd.Utils.parseReply hmac msg salt2 ==?
           BasicTypes.Bad "The received salt differs from the expected salt"

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
  in counterexample ("Accepted message signed with different key" ++ encoded) $
     (Confd.Utils.parseSignedMessage key_verify encoded
      :: BasicTypes.Result (String, String, Confd.ConfdRequest)) ==?
       BasicTypes.Bad "HMAC verification failed"

testSuite "Confd/Utils"
  [ 'prop_req_sign
  , 'prop_rep_salt
  , 'prop_bad_key
  ]

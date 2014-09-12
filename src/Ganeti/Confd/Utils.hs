{-| Implementation of the Ganeti confd utilities.

This holds a few utility functions that could be useful in both
clients and servers.

-}

{-

Copyright (C) 2011, 2012 Google Inc.
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

module Ganeti.Confd.Utils
  ( getClusterHmac
  , parseSignedMessage
  , parseRequest
  , parseReply
  , signMessage
  , getCurrentTime
  ) where

import qualified Data.ByteString as B
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Confd.Types
import Ganeti.Hash
import qualified Ganeti.Constants as C
import qualified Ganeti.Path as Path
import Ganeti.JSON
import Ganeti.Utils

-- | Type-adjusted max clock skew constant.
maxClockSkew :: Integer
maxClockSkew = fromIntegral C.confdMaxClockSkew

-- | Returns the HMAC key.
getClusterHmac :: IO HashKey
getClusterHmac = Path.confdHmacKey >>= fmap B.unpack . B.readFile

-- | Parses a signed message.
parseSignedMessage :: (J.JSON a) => HashKey -> String
                   -> Result (String, String, a)
parseSignedMessage key str = do
  (SignedMessage hmac msg salt) <- fromJResult "parsing signed message"
    $ J.decode str
  parsedMsg <- if verifyMac key (Just salt) msg hmac
           then fromJResult "parsing message" $ J.decode msg
           else Bad "HMAC verification failed"
  return (salt, msg, parsedMsg)

-- | Message parsing. This can either result in a good, valid request
-- message, or fail in the Result monad.
parseRequest :: HashKey -> String -> Integer
             -> Result (String, ConfdRequest)
parseRequest hmac msg curtime = do
  (salt, origmsg, request) <- parseSignedMessage hmac msg
  ts <- tryRead "Parsing timestamp" salt::Result Integer
  if abs (ts - curtime) > maxClockSkew
    then fail "Too old/too new timestamp or clock skew"
    else return (origmsg, request)

-- | Message parsing. This can either result in a good, valid reply
-- message, or fail in the Result monad.
-- It also checks that the salt in the message corresponds to the one
-- that is expected
parseReply :: HashKey -> String -> String -> Result (String, ConfdReply)
parseReply hmac msg expSalt = do
  (salt, origmsg, reply) <- parseSignedMessage hmac msg
  if salt /= expSalt
    then fail "The received salt differs from the expected salt"
    else return (origmsg, reply)

-- | Signs a message with a given key and salt.
signMessage :: HashKey -> String -> String -> SignedMessage
signMessage key salt msg =
  SignedMessage { signedMsgMsg  = msg
                , signedMsgSalt = salt
                , signedMsgHmac = hmac
                }
    where hmac = computeMac key (Just salt) msg

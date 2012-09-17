{-| Implementation of the Ganeti confd utilities.

This holds a few utility functions that could be useful in both
clients and servers.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.Confd.Utils
  ( getClusterHmac
  , parseRequest
  , parseMessage
  , signMessage
  ) where

import qualified Data.ByteString as B
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Confd
import Ganeti.Hash
import qualified Ganeti.Constants as C
import qualified Ganeti.Path as Path
import Ganeti.JSON
import Ganeti.HTools.Utils

-- | Returns the HMAC key.
getClusterHmac :: IO HashKey
getClusterHmac = fmap B.unpack $ B.readFile Path.confdHmacKey

-- | Parses a signed request.
parseRequest :: HashKey -> String -> Result (String, String, ConfdRequest)
parseRequest key str = do
  (SignedMessage hmac msg salt) <- fromJResult "parsing request" $ J.decode str
  req <- if verifyMac key (Just salt) msg hmac
           then fromJResult "parsing message" $ J.decode msg
           else Bad "HMAC verification failed"
  return (salt, msg, req)

-- | Mesage parsing. This can either result in a good, valid message,
-- or fail in the Result monad.
parseMessage :: HashKey -> String -> Integer
             -> Result (String, ConfdRequest)
parseMessage hmac msg curtime = do
  (salt, origmsg, request) <- parseRequest hmac msg
  ts <- tryRead "Parsing timestamp" salt::Result Integer
  if abs (ts - curtime) > fromIntegral C.confdMaxClockSkew
    then fail "Too old/too new timestamp or clock skew"
    else return (origmsg, request)

-- | Signs a message with a given key and salt.
signMessage :: HashKey -> String -> String -> SignedMessage
signMessage key salt msg =
  SignedMessage { signedMsgMsg  = msg
                , signedMsgSalt = salt
                , signedMsgHmac = hmac
                }
    where hmac = computeMac key (Just salt) msg

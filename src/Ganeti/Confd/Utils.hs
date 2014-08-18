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
  , parseSignedMessage
  , parseRequest
  , parseReply
  , signMessage
  , getCurrentTime
  , extractJSONPath
  ) where

import qualified Data.Attoparsec.Text as P

import Control.Applicative ((*>))
import qualified Data.ByteString as B
import Data.Text (pack)
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

data Pointer = Pointer [String]
  deriving (Show, Eq)

-- | Parse a fixed size Int.
readInteger :: String -> J.Result Int
readInteger = either J.Error J.Ok . P.parseOnly P.decimal . pack

-- | Parse a path for a JSON structure.
pointerFromString :: String -> J.Result Pointer
pointerFromString s =
  either J.Error J.Ok . P.parseOnly parser $ pack s
  where
    parser = do
      _ <- P.char '/'
      tokens <- token `P.sepBy1` P.char '/'
      return $ Pointer tokens
    token =
      P.choice [P.many1 (P.choice [ escaped
                        , P.satisfy $ P.notInClass "~/"])
               , P.endOfInput *> return ""]
    escaped = P.choice [escapedSlash, escapedTilde]
    escapedSlash = P.string (pack "~1") *> return '/'
    escapedTilde = P.string (pack "~0") *> return '~'


-- | Use a Pointer to access any value nested in a JSON object.
extractValue :: J.JSON a => Pointer -> a -> J.Result J.JSValue
extractValue (Pointer l) json =
  getJSValue l $ J.showJSON json
  where
    indexWithString x (J.JSObject object) = J.valFromObj x object
    indexWithString x (J.JSArray list) = do
      i <- readInteger x
      if 0 <= i && i < length list
        then return $ list !! i
        else J.Error ("list index " ++ show i ++ " out of bounds")
    indexWithString _ _ = J.Error "Atomic value was indexed"
    getJSValue :: [String] -> J.JSValue -> J.Result J.JSValue
    getJSValue [] js = J.Ok js
    getJSValue (x:xs) js = do
      value <- indexWithString x js
      getJSValue xs value

-- | Extract a JSValue from an object at the position defined by the path.
--
-- The path syntax follows RCF6901. Error is returned if the path doesn't
-- exist, Ok if the path leads to an valid value.
--
-- JSON pointer syntax according to RFC6901:
-- "/path/0/x" => Pointer ["path", "0", "x"]
-- This accesses 1 in the following JSON:
-- { "path": { "0": { "x": 1 } } }
--
-- or the following:
--
-- { "path": [{"x": 1}] }
extractJSONPath :: J.JSON a => String -> a -> J.Result J.JSValue
extractJSONPath path obj = do
  pointer <- pointerFromString path
  extractValue pointer obj

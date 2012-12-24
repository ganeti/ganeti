{-| Crypto-related helper functions.

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

module Ganeti.Hash
  ( computeMac
  , verifyMac
  , HashKey
  ) where

import qualified Data.ByteString as B
import Data.Char
import Data.HMAC (hmac_sha1)
import qualified Data.Text as T
import Data.Text.Encoding (encodeUtf8)
import Data.Word
import Text.Printf (printf)

-- | Type alias for the hash key. This depends on the library being
-- used.
type HashKey = [Word8]

-- | Converts a string to a list of bytes.
stringToWord8 :: String -> HashKey
stringToWord8 = B.unpack . encodeUtf8 . T.pack

-- | Converts a list of bytes to a string.
word8ToString :: HashKey -> String
word8ToString = concatMap (printf "%02x")

-- | Computes the HMAC for a given key/test and salt.
computeMac :: HashKey -> Maybe String -> String -> String
computeMac key salt text =
  word8ToString . hmac_sha1 key . stringToWord8 $ maybe text (++ text) salt

-- | Verifies the HMAC for a given message.
verifyMac :: HashKey -> Maybe String -> String -> String -> Bool
verifyMac key salt text digest =
  map toLower digest == computeMac key salt text

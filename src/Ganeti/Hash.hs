{-| Crypto-related helper functions.

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

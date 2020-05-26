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
import qualified Data.ByteString.UTF8 as BU
import Crypto.Hash.Algorithms
import Crypto.MAC.HMAC
import Data.Char
import Data.Word

-- | Type alias for the hash key. This depends on the library being
-- used.
type HashKey = [Word8]

-- | Computes the HMAC for a given key/test and salt.
computeMac :: HashKey -> Maybe String -> String -> String
computeMac key salt text =
  let hashable = maybe text (++ text) salt
  in show . hmacGetDigest $
    (hmac (B.pack key) (BU.fromString hashable) :: HMAC SHA1)

-- | Verifies the HMAC for a given message.
verifyMac :: HashKey -> Maybe String -> String -> String -> Bool
verifyMac key salt text digest =
  map toLower digest == computeMac key salt text

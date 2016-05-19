{-| Provides interface to the 'zlib' library.

-}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.Codec
  ( compressZlib
  , decompressZlib
  ) where

import Codec.Compression.Zlib
import qualified Codec.Compression.Zlib.Internal as I
import Control.Monad.Error
import qualified Data.ByteString.Lazy as BL
import qualified Data.ByteString.Lazy.Internal as BL
import Data.Monoid (mempty)


-- | Compresses a lazy bytestring.
compressZlib :: BL.ByteString -> BL.ByteString
compressZlib = compressWith $
  defaultCompressParams { compressLevel = CompressionLevel 3 }

-- | Decompresses a lazy bytestring, throwing decoding errors using
-- 'throwError'.
decompressZlib :: (MonadError e m, Error e) => BL.ByteString -> m BL.ByteString
decompressZlib = I.foldDecompressStream
                     (liftM . BL.chunk)
                     (return mempty)
                     (const $ throwError . strMsg . ("Zlib: " ++))
                 . I.decompressWithErrors
                     I.zlibFormat
                     I.defaultDecompressParams

{-| Provides interface to the 'zlib' library.

-}

{-

Copyright (C) 2014 Google Inc.

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

module Ganeti.Codec
  ( compressZlib
  , decompressZlib
  ) where

import Codec.Compression.Zlib (compress)
import qualified Codec.Compression.Zlib.Internal as I
import Control.Monad.Error
import qualified Data.ByteString.Lazy as BL
import qualified Data.ByteString.Lazy.Internal as BL
import Data.Monoid (mempty)

-- | Compresses a lazy bytestring.
compressZlib :: BL.ByteString -> BL.ByteString
compressZlib = compress

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

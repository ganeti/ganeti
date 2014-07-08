{-# LANGUAGE ForeignFunctionInterface #-}

{-| Necessary foreign function calls

...with foreign functions declared in unistd.h

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

module Ganeti.Utils.UniStd
  ( hCloseAndFsync
  ) where

import Foreign.C
import System.IO
import System.IO.Error
import System.Posix.IO
import System.Posix.Types

foreign import ccall "fsync" fsync :: CInt -> IO CInt


-- | Flush, close and fsync(2) a file handle.
hCloseAndFsync :: Handle -> IO ()
hCloseAndFsync handle = do
  Fd fd <- handleToFd handle -- side effect of closing the handle and flushing
                             -- its write buffer, if necessary.
  _ <- fsync fd
  _ <- tryIOError $ closeFd (Fd fd)
  return ()

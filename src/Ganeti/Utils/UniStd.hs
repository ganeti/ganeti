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
  ( fsyncFile
  ) where

import Control.Exception (bracket)
import Foreign.C
import System.Posix.IO
import System.Posix.Types

import Ganeti.BasicTypes

foreign import ccall "fsync" fsync :: CInt -> IO CInt

-- Opens a file and calls fsync(2) on the file descriptor.
--
-- Because of a bug in GHC 7.6.3 (at least), calling 'hIsClosed' on a handle
-- to get the file descriptor leaks memory. Therefore we open a given file
-- just to sync it and close it again.
fsyncFile :: (Error e) => FilePath -> ResultT e IO ()
fsyncFile path = liftIO
  $ bracket (openFd path ReadOnly Nothing defaultFileFlags) closeFd callfsync
  where
    callfsync (Fd fd) = throwErrnoPathIfMinus1_ "fsyncFile" path $ fsync fd

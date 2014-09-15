{-# LANGUAGE ForeignFunctionInterface #-}

{-| Necessary foreign function calls

...with foreign functions declared in unistd.h

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

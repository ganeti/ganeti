{-# LANGUAGE CPP #-}

{- | Compatibility helper module.

This module holds definitions that help with supporting multiple
library versions or transitions between versions.

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

module Ganeti.Compat
  ( atomicModifyIORef'
  , filePath'
  , maybeFilePath'
  , toInotifyPath
  ) where

import qualified Data.IORef
import qualified Data.ByteString.UTF8 as UTF8
import System.FilePath (FilePath)
import System.Posix.ByteString.FilePath (RawFilePath)
import qualified System.INotify

-- FIXME: remove this when dropping support for GHC 7.4.
atomicModifyIORef' :: Data.IORef.IORef a -> (a -> (a, b)) -> IO b
#if MIN_VERSION_base(4,6,0)
atomicModifyIORef' = Data.IORef.atomicModifyIORef'
#else
atomicModifyIORef' ref f = do
    b <- Data.IORef.atomicModifyIORef ref $ \a ->
            case f a of
                v@(a',_) -> a' `seq` v
    b `seq` return b
#endif

-- | Wrappers converting ByteString filepaths to Strings and vice versa
--
-- hinotify 0.3.10 switched to using RawFilePaths instead of FilePaths, the
-- former being Data.ByteString and the latter String.
#if MIN_VERSION_hinotify(0,3,10)
filePath' :: System.INotify.Event -> FilePath
filePath' = UTF8.toString . System.INotify.filePath

maybeFilePath' :: System.INotify.Event -> Maybe FilePath
maybeFilePath' ev = UTF8.toString <$> System.INotify.maybeFilePath ev

toInotifyPath :: FilePath -> RawFilePath
toInotifyPath = UTF8.fromString
#else
filePath' :: System.INotify.Event -> FilePath
filePath' = System.INotify.filePath

maybeFilePath' :: System.INotify.Event -> Maybe FilePath
maybeFilePath' = System.INotify.maybeFilePath

toInotifyPath :: FilePath -> FilePath
toInotifyPath = id
#endif

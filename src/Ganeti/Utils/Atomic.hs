{-# LANGUAGE FlexibleContexts #-}

{-| Utility functions for atomic file access. -}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Ganeti.Utils.Atomic
  ( atomicWriteFile
  , atomicUpdateFile
  , withLockedFile
  , atomicUpdateLockedFile
  , atomicUpdateLockedFile_
  ) where

import qualified Control.Exception.Lifted as L
import Control.Monad
import Control.Monad.Base (MonadBase(..))
import Control.Monad.Error
import Control.Monad.Trans.Control
import System.FilePath.Posix (takeDirectory, takeBaseName)
import System.IO
import System.Directory (renameFile)
import System.Posix.IO
import System.Posix.Types

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Logging (logAlert)
import Ganeti.Utils
import Ganeti.Utils.UniStd (fsyncFile)

-- | Atomically write a file, by first writing the contents into a temporary
-- file and then renaming it to the old position.
atomicWriteFile :: FilePath -> String -> IO ()
atomicWriteFile path contents = atomicUpdateFile path
                                  (\_ fh -> hPutStr fh contents)

-- | Calls fsync(2) on a given file.
-- If the operation fails, issue an alert log message and continue.
-- Doesn't throw an exception.
fsyncFileChecked :: FilePath -> IO ()
fsyncFileChecked path =
    runResultT (fsyncFile path) >>= genericResult logMsg return
  where
    logMsg e = logAlert $ "Can't fsync file '" ++ path ++ "': " ++ e

-- | Atomically update a file, by first creating a temporary file, running the
-- given action on it, and then renaming it to the old position.
-- Usually the action will write to the file and update its permissions.
-- The action is allowed to close the file descriptor, but isn't required to do
-- so.
atomicUpdateFile :: (MonadBaseControl IO m)
                 => FilePath -> (FilePath -> Handle -> m a) -> m a
atomicUpdateFile path action = do
  -- Put a separator on the filename pattern to produce temporary filenames
  -- such as job-1234-NNNNNN.tmp instead of job-1234NNNNNN. The latter can cause
  -- problems (as well as user confusion) because temporary filenames have the
  -- same format as real filenames, and anything that scans a directory won't be
  -- able to tell them apart.
  let filenameTemplate = takeBaseName path ++ "-.tmp"
  (tmppath, tmphandle) <- liftBase $ openBinaryTempFile (takeDirectory path)
                                                        filenameTemplate
  r <- L.finally (action tmppath tmphandle)
                 (liftBase (hClose tmphandle >> fsyncFileChecked tmppath))
  -- if all went well, rename the file
  liftBase $ renameFile tmppath path
  return r

-- | Opens a file in a R/W mode, locks it (blocking if needed) and runs
-- a given action while the file is locked. Releases the lock and
-- closes the file afterwards.
withLockedFile :: (MonadError e m, Error e, MonadBaseControl IO m)
               => FilePath -> (Fd -> m a) -> m a
withLockedFile path =
    L.bracket (openAndLock path) (liftBase . closeFd)
  where
    openAndLock :: (MonadError e m, Error e, MonadBaseControl IO m)
                => FilePath -> m Fd
    openAndLock p = liftBase $ do
      fd <- openFd p ReadWrite Nothing defaultFileFlags
      waitToSetLock fd (WriteLock, AbsoluteSeek, 0, 0)
      return fd

-- | Just as 'atomicUpdateFile', but in addition locks the file during the
-- operation using 'withLockedFile' and checks if the file has been modified.
-- The action is only run if it hasn't, otherwise an error is thrown.
-- The file must exist.
-- Returns the new file status after the operation is finished.
atomicUpdateLockedFile :: FilePath
                       -> FStat
                       -> (FilePath -> Handle -> IO a)
                       -> ResultG (FStat, a)
atomicUpdateLockedFile path fstat action =
    toErrorBase . withErrorT (LockError . (show :: IOError -> String))
    $ withLockedFile path checkStatAndRun
  where
    checkStatAndRun _ = do
      newstat <- liftIO $ getFStat path
      unless (fstat == newstat)
             (failError $ "Cannot overwrite file " ++ path ++
                          ": it has been modified since last written" ++
                          " (" ++ show fstat ++ " != " ++ show newstat ++ ")")
      liftIO $ atomicUpdateFile path actionAndStat
    actionAndStat tmppath tmphandle = do
      r <- action tmppath tmphandle
      hClose tmphandle -- close the handle so that we get meaningful stats
      finalstat <- liftIO $ getFStat tmppath
      return (finalstat, r)

-- | Just as 'atomicUpdateLockedFile', but discards the action result.
atomicUpdateLockedFile_ :: FilePath
                        -> FStat
                        -> (FilePath -> Handle -> IO a)
                        -> ResultG FStat
atomicUpdateLockedFile_ path oldstat
  = liftM fst . atomicUpdateLockedFile path oldstat

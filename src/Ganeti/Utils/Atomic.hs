{-# LANGUAGE FlexibleContexts #-}

{-| Utility functions for atomic file access. -}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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
import Ganeti.Utils

-- | Atomically write a file, by first writing the contents into a temporary
-- file and then renaming it to the old position.
atomicWriteFile :: FilePath -> String -> IO ()
atomicWriteFile path contents = atomicUpdateFile path
                                  (\_ fh -> hPutStr fh contents)

-- | Atomically update a file, by first creating a temporary file, running the
-- given action on it, and then renaming it to the old position.
-- Usually the action will write to the file and update its permissions.
-- The action is allowed to close the file descriptor, but isn't required to do
-- so.
atomicUpdateFile :: (MonadBaseControl IO m)
                 => FilePath -> (FilePath -> Handle -> m a) -> m a
atomicUpdateFile path action = do
  (tmppath, tmphandle) <- liftBase $ openTempFile (takeDirectory path)
                                                  (takeBaseName path)
  r <- L.finally (action tmppath tmphandle) (liftBase $ hClose tmphandle)
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

{-| Utilities related to livelocks and death detection

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

module Ganeti.Utils.Livelock
  ( Livelock
  , mkLivelockFile
  , isDead
  ) where

import qualified Control.Exception as E
import Control.Monad
import Control.Monad.Error
import System.Directory (doesFileExist)
import System.IO
import System.Posix.IO
import System.Posix.Types (Fd)
import System.Time (ClockTime(..), getClockTime)

import Ganeti.BasicTypes
import Ganeti.Logging
import Ganeti.Path (livelockFile)
import Ganeti.Utils (lockFile)

type Livelock = FilePath

-- | Appends the current time to the given prefix, creates
-- the lockfile in the appropriate directory, and locks it.
-- Returns its full path and the file's file descriptor.
mkLivelockFile :: (Error e, MonadError e m, MonadIO m)
               => FilePath -> m (Fd, Livelock)
mkLivelockFile prefix = do
  (TOD secs _) <- liftIO getClockTime
  lockfile <- liftIO . livelockFile $ prefix ++ "_" ++ show secs
  fd <- liftIO (lockFile lockfile) >>= \r -> case r of
          Bad msg   -> failError $ "Locking the livelock file " ++ lockfile
                                   ++ ": " ++ msg
          Ok fd     -> return fd
  return (fd, lockfile)

-- | Detect whether a the process identified by the given path
-- does not exist any more. This function never fails and only
-- returns True if it has positive knowledge that the process
-- does not exist any more (i.e., if it managed successfully
-- obtain a shared lock on the file).
isDead :: Livelock -> IO Bool
isDead fpath = fmap (isOk :: Result () -> Bool) . runResultT . liftIO $ do
  filepresent <- doesFileExist fpath
  when filepresent
    . E.bracket (openFd fpath ReadOnly Nothing defaultFileFlags) closeFd
                $ \fd -> do
                    logDebug $ "Attempting to get a lock of " ++ fpath
                    setLock fd (ReadLock, AbsoluteSeek, 0, 0)
                    logDebug "Got the lock, the process is dead"

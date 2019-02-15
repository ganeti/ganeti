{-| Utilities related to livelocks and death detection

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

module Ganeti.Utils.Livelock
  ( Livelock
  , mkLivelockFile
  , listLiveLocks
  , isDead
  ) where

import qualified Control.Exception as E
import Control.Monad
import Control.Monad.Error
import System.Directory (doesFileExist, getDirectoryContents)
import System.FilePath.Posix ((</>))
import System.IO
import System.Posix.IO
import System.Posix.Types (Fd)
import System.Time (ClockTime(..), getClockTime)

import Ganeti.BasicTypes
import Ganeti.Logging
import Ganeti.Path (livelockFile, livelockDir)
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

-- | List currently existing livelocks. Underapproximate if
-- some error occurs.
listLiveLocks :: IO [FilePath]
listLiveLocks =
  fmap (genericResult (const [] :: IOError -> [FilePath]) id)
  . runResultT . liftIO $ do
    dir <- livelockDir
    entries <- getDirectoryContents dir
    filterM doesFileExist $ map (dir </>) entries

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

{-| Utility function for detecting the death of a job holding resources

To clean up resources owned by jobs that die for some reason, we need
to detect whether a job is still alive. As we have no control over PID
reuse, our approach is that each requester for a resource has to provide
a file where it owns an exclusive lock on. The kernel will make sure the
lock is removed if the process dies. We can probe for such a lock by
requesting a shared lock on the file.

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

module Ganeti.WConfd.DeathDetection
  ( isDead
  ) where

import Control.Exception (bracket)
import Control.Monad
import System.Directory
import System.IO
import System.Posix.IO

import Ganeti.BasicTypes

-- | Detect whether a the process identified by the given path
-- does not exist any more. This function never fails and only
-- returns True if it has positive knowledge that the process
-- does not exist any more (i.e., if it managed successfully
-- obtain a shared lock on the file).
isDead :: FilePath -> IO Bool
isDead fpath = fmap (isOk :: Result () -> Bool) . runResultT . liftIO $ do
  filepresent <- doesFileExist fpath
  when filepresent
    $ bracket (openFd fpath ReadOnly Nothing defaultFileFlags) closeFd
              (`setLock` (ReadLock, AbsoluteSeek, 0, 0))

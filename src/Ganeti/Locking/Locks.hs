{-| Ganeti lock structure

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

module Ganeti.Locking.Locks
  ( GanetiLocks(..)
  , GanetiLockAllocation
  , loadLockAllocation
  ) where

import Control.Monad (liftM, (>=>))
import qualified Text.JSON as J


import Ganeti.BasicTypes
import Ganeti.Errors (ResultG)
import Ganeti.JSON (asJSObject, fromObj, fromJResultE)
import Ganeti.Locking.Allocation
import Ganeti.Locking.Types
import Ganeti.Types

-- | The type of Locks available in Ganeti. The order of this type
-- is the lock oder.
data GanetiLocks = BGL deriving (Ord, Eq, Show)
-- TODO: add the remaining locks

-- | Describe the parts the pieces of information that are needed to
-- describe the lock.
lockData :: GanetiLocks -> [(String, J.JSValue)]
lockData BGL = [("type", J.showJSON "BGL")]

-- | Read a lock form its JSON representation.
readLock :: J.JSValue -> J.Result GanetiLocks
readLock v =  do
  fields <- liftM J.fromJSObject $ asJSObject v
  tp <- fromObj fields "type"
  case tp of
    "BGL" -> return BGL
    _ -> fail $ "Unknown lock type " ++ tp

instance J.JSON GanetiLocks where
  showJSON = J.JSObject . J.toJSObject . lockData
  readJSON = readLock


instance Lock GanetiLocks where
  lockImplications BGL = []

-- | The type of lock Allocations in Ganeti. In Ganeti, the owner of
-- locks are jobs.
type GanetiLockAllocation = LockAllocation GanetiLocks JobId

-- | Load a lock allocation from disk.
loadLockAllocation :: FilePath -> ResultG GanetiLockAllocation
loadLockAllocation =
  liftIO . readFile
  >=> fromJResultE "parsing lock allocation" . J.decodeStrict

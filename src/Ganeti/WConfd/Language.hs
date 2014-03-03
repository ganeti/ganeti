{-| Function related to serialisation of WConfD requests

-}

{-

Copyright (C) 2013 Google Inc.

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

module Ganeti.WConfd.Language
  ( LockRequestType(..)
  , GanetiLockRequest
  , fromGanetiLockRequest
  ) where

import qualified Text.JSON as J

import Ganeti.Locking.Allocation
import Ganeti.Locking.Locks (GanetiLocks)

-- * Serialisation related to locking

-- | Operation to be carried out on a lock (request exclusive/shared ownership,
-- or release).
data LockRequestType = ReqExclusive | ReqShared | ReqRelease deriving (Eq, Show)

instance J.JSON LockRequestType where
  showJSON ReqExclusive = J.showJSON "exclusive"
  showJSON ReqShared = J.showJSON "shared"
  showJSON ReqRelease = J.showJSON "release"
  readJSON (J.JSString x) = let s = J.fromJSString x
                            in case s of
                              "exclusive" -> J.Ok ReqExclusive
                              "shared" -> J.Ok ReqShared
                              "release" -> J.Ok ReqRelease
                              _ -> J.Error $ "Unknown lock update request " ++ s
  readJSON _ = J.Error "Update requests need to be strings"

-- | The type describing how lock update requests are passed over the wire.
type GanetiLockRequest = [(GanetiLocks, LockRequestType)]

-- | Transform a Lock LockReqeustType pair into a LockRequest.
toLockRequest :: (GanetiLocks, LockRequestType) -> LockRequest GanetiLocks
toLockRequest (a, ReqExclusive) = requestExclusive a
toLockRequest (a, ReqShared) = requestShared a
toLockRequest (a, ReqRelease) = requestRelease a

-- | From a GanetiLockRequest obtain a list of
-- Ganeti.Lock.Allocation.LockRequest, suitable to updateLocks.
fromGanetiLockRequest :: GanetiLockRequest -> [LockRequest GanetiLocks]
fromGanetiLockRequest = map toLockRequest

{-| Function related to serialisation of WConfD requests

-}

{-

Copyright (C) 2013 Google Inc.
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

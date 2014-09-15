{-| Implementation of Ganeti Lock field queries

The actual computation of the field values is done by forwarding
the request; so only have a minimal field definition here.

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

module Ganeti.Query.Locks
  ( fieldsMap
  , RuntimeData
  ) where

import qualified Text.JSON as J

import Control.Arrow (first)
import Data.Tuple (swap)

import Ganeti.Locking.Allocation (OwnerState(..))
import Ganeti.Locking.Locks (ClientId, ciIdentifier)
import Ganeti.Query.Common
import Ganeti.Query.Language
import Ganeti.Query.Types

-- | The runtime information for locks. As all information about locks
-- is handled by WConfD, the actual information is obtained as live data.
-- The type represents the information for a single lock, even though all
-- locks are queried simultaneously, ahead of time.
type RuntimeData = ( [(ClientId, OwnerState)] -- current state
                   , [(ClientId, OwnerState)] -- pending requests
                   )

-- | Obtain the owners of a lock from the runtime data.
getOwners :: RuntimeData -> a -> ResultEntry
getOwners (ownerinfo, _) _ =
  rsNormal . map (J.encode . ciIdentifier . fst)
    $ ownerinfo

-- | Obtain the mode of a lock from the runtime data.
getMode :: RuntimeData -> a -> ResultEntry
getMode (ownerinfo, _) _
  | null ownerinfo = rsNormal J.JSNull
  | any ((==) OwnExclusive . snd) ownerinfo = rsNormal "exclusive"
  | otherwise = rsNormal "shared"

-- | Obtain the pending requests from the runtime data.
getPending :: RuntimeData -> a -> ResultEntry
getPending (_, pending) _ =
  rsNormal . map (swap . first ((:[]) . J.encode . ciIdentifier)) $ pending

-- | List of all lock fields.
lockFields :: FieldList String RuntimeData
lockFields =
  [ (FieldDefinition "name" "Name" QFTOther "Lock name",
     FieldSimple rsNormal, QffNormal)
  , (FieldDefinition "mode" "Mode" QFTOther "Mode in which the lock is\
                                             \ currently acquired\
                                             \ (exclusive or shared)",
     FieldRuntime getMode, QffNormal)
  , (FieldDefinition "owner" "Owner" QFTOther "Current lock owner(s)",
     FieldRuntime getOwners, QffNormal)
  , (FieldDefinition "pending" "Pending" QFTOther "Jobs waiting for the lock",
     FieldRuntime getPending, QffNormal)
  ]

-- | The lock fields map.
fieldsMap :: FieldMap String RuntimeData
fieldsMap = fieldListToFieldMap lockFields

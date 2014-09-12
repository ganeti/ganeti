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
  ) where

import qualified Data.Map as Map

import Ganeti.Query.Common
import Ganeti.Query.Language
import Ganeti.Query.Types

-- | List of all lock fields.
lockFields :: FieldList String ()
lockFields =
  [ (FieldDefinition "name" "Name" QFTOther "Lock name",
     FieldSimple rsNormal, QffNormal)
  , (FieldDefinition "mode" "Mode" QFTOther "Mode in which the lock is\
                                             \ currently acquired\
                                             \ (exclusive or shared)",
     FieldSimple rsNormal, QffNormal)
  , (FieldDefinition "owner" "Owner" QFTOther "Current lock owner(s)",
     FieldSimple rsNormal, QffNormal)
  , (FieldDefinition "pending" "Pending" QFTOther "Jobs waiting for the lock",
     FieldSimple rsNormal, QffNormal)
  ]

-- | The lock fields map.
fieldsMap :: FieldMap String ()
fieldsMap =
  Map.fromList $ map (\v@(f, _, _) -> (fdefName f, v)) lockFields

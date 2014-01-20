{-| Implementation of Ganeti Lock field queries

The actual computation of the field values is done by forwarding
the request; so only have a minimal field definition here.

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

{-| Implementation of the Ganeti Query2 basic types.

These are types internal to the library, and for example clients that
use the library should not need to import it.

 -}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.Query.Types
  ( FieldGetter(..)
  , QffMode(..)
  , FieldData
  , FieldList
  , FieldMap
  , isRuntimeField
  ) where

import qualified Data.Map as Map

import Ganeti.Query.Language
import Ganeti.Objects

-- | The type of field getters. The \"a\" type represents the type
-- we're querying, whereas the \"b\" type represents the \'runtime\'
-- data for that type (if any). Note that we don't support multiple
-- runtime sources, and we always consider the entire configuration as
-- a given (so no equivalent for Python's /*_CONFIG/ and /*_GROUP/;
-- configuration accesses are cheap for us).
data FieldGetter a b = FieldSimple  (a -> ResultEntry)
                     | FieldRuntime (b -> a -> ResultEntry)
                     | FieldConfig  (ConfigData -> a -> ResultEntry)
                     | FieldUnknown

-- | Type defining how the value of a field is used in filtering. This
-- implements the equivalent to Python's QFF_ flags, except that we
-- don't use OR-able values.
data QffMode = QffNormal     -- ^ Value is used as-is in filters
             | QffTimestamp  -- ^ Value is a timestamp tuple, convert to float
               deriving (Show, Eq)


-- | Alias for a field data (definition and getter).
type FieldData a b = (FieldDefinition, FieldGetter a b, QffMode)

-- | Alias for a field data list.
type FieldList a b = [FieldData a b]

-- | Alias for field maps.
type FieldMap a b = Map.Map String (FieldData a b)

-- | Helper function to check if a getter is a runtime one.
isRuntimeField :: FieldGetter a b -> Bool
isRuntimeField (FieldRuntime _) = True
isRuntimeField _                = False

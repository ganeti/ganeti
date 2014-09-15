{-| Implementation of the Ganeti Query2 basic types.

These are types internal to the library, and for example clients that
use the library should not need to import it.

 -}

{-

Copyright (C) 2012, 2013 Google Inc.
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

module Ganeti.Query.Types
  ( FieldGetter(..)
  , QffMode(..)
  , FieldData
  , FieldList
  , FieldMap
  , isRuntimeField
  , fieldListToFieldMap
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
data FieldGetter a b = FieldSimple        (a -> ResultEntry)
                     | FieldRuntime       (b -> a -> ResultEntry)
                     | FieldConfig        (ConfigData -> a -> ResultEntry)
                     | FieldConfigRuntime (ConfigData -> b -> a -> ResultEntry)
                     | FieldUnknown

-- | Type defining how the value of a field is used in filtering. This
-- implements the equivalent to Python's QFF_ flags, except that we
-- don't use OR-able values.
data QffMode = QffNormal     -- ^ Value is used as-is in filters
             | QffTimestamp  -- ^ Value is a timestamp tuple, convert to float
             | QffHostname   -- ^ Value is a hostname, compare it smartly
               deriving (Show, Eq)


-- | Alias for a field data (definition and getter).
type FieldData a b = (FieldDefinition, FieldGetter a b, QffMode)

-- | Alias for a field data list.
type FieldList a b = [FieldData a b]

-- | Alias for field maps.
type FieldMap a b = Map.Map String (FieldData a b)

-- | Helper function to check if a getter is a runtime one.
isRuntimeField :: FieldGetter a b -> Bool
isRuntimeField FieldRuntime {}       = True
isRuntimeField FieldConfigRuntime {} = True
isRuntimeField _                     = False

-- | Helper function to obtain a FieldMap from the corresponding FieldList.
fieldListToFieldMap :: FieldList a b -> FieldMap a b
fieldListToFieldMap = Map.fromList . map (\v@(f, _, _) -> (fdefName f, v))

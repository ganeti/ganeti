{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti Query2 language.

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

module Ganeti.Query2
    ( Filter
    ) where


import Text.JSON.Types
import Text.JSON

import qualified Ganeti.Constants as C
import Ganeti.HTools.JSON
import Ganeti.THH

-- * THH declarations, that require ordering.

-- | Status of a query field.
$(declareIADT "ResultStatus"
  [ ("RSNormal",  'C.rsNormal )
  , ("RSUnknown", 'C.rsUnknown )
  , ("RSNoData",  'C.rsNodata )
  , ("RSUnavail", 'C.rsUnavail )
  , ("RSOffline", 'C.rsOffline )
  ])
$(makeJSONInstance ''ResultStatus)

-- | Type of a query field.
$(declareSADT "FieldType"
  [ ("QFTUnknown",   'C.qftUnknown )
  , ("QFTText",      'C.qftText )
  , ("QFTBool",      'C.qftBool )
  , ("QFTNumber",    'C.qftNumber )
  , ("QFTUnit",      'C.qftUnit )
  , ("QFTTimestamp", 'C.qftTimestamp )
  , ("QFTOther",     'C.qftOther )
  ])
$(makeJSONInstance ''FieldType)

-- | Supported items on which Query2 works.
$(declareSADT "ItemType"
  [ ("QRCluster",  'C.qrCluster )
  , ("QRInstance", 'C.qrInstance )
  , ("QRNode",     'C.qrNode )
  , ("QRLock",     'C.qrLock )
  , ("QRGroup",    'C.qrGroup )
  , ("QROs",       'C.qrOs )
  , ("QRJob",      'C.qrJob )
  , ("QRExport",   'C.qrExport )
  ])
$(makeJSONInstance ''ItemType)

-- * Main Query2 queries and responses.

-- | Query2 query.
data Query = Query ItemType Fields (Maybe Filter)

-- | Query2 result.
data QueryResult = QueryResult [ FieldDefinition ] [ ResultEntry ]

-- | Query2 Fields query.
-- (to get supported fields names, descriptions, and types)
data QueryFields = QueryFields ItemType Fields

-- | Query2 Fields result.
data QueryFieldsResult = QueryFieldsResult [ FieldDefinition ]

-- * Sub data types for query2 queries and responses.

-- | List of requested fields.
type Fields = [ String ]

-- | Query2 filter expression.
data Filter
    = AndFilter [ Filter ] -- ^ & [<expression>, ...]
    | OrFilter [ Filter ] -- ^ | [<expression>, ...]
    | NotFilter Filter -- ^ ! <expression>
    | TrueFilter FilterField -- ^ ? <field>
    | EqualFilter FilterField FilterValue -- ^ (=|!=) <field> <value>
    | LessThanFilter FilterField FilterValue -- ^ < <field> <value>
    | GreaterThanFilter FilterField FilterValue -- ^ > <field> <value>
    | LEThanFilter FilterField FilterValue -- ^ <= <field> <value>
    | GEThanFilter FilterField FilterValue -- ^ >= <field> <value>
    | RegexpFilter FilterField FilterRegexp -- ^ =~ <field> <regexp>
    | ContainsFilter FilterField FilterValue -- ^ =[] <list-field> <value>

-- | Field name to filter on.
type FilterField = String

-- | Value to compare the field value to, for filtering purposes.
type FilterValue = String

-- | Regexp to apply to the filter value, for filteriong purposes.
type FilterRegexp = String

-- | Definition of a field.
data FieldDefinition = FieldDefinition FieldName FieldTitle FieldType FieldDoc

-- | Name of a field.
type FieldName = String
-- | Title of a field, when represented in tabular format.
type FieldTitle = String
-- | Human redable description of a field.
type FieldDoc = String

--- | Single field entry result.
data ResultEntry = ResultEntry ResultStatus (Maybe ResultValue)

-- | Value of a field, in json encoding.
-- (its type will be depending on ResultStatus and FieldType)
type ResultValue = JSValue

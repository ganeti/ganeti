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

module Ganeti.Qlang
    ( Filter(..)
    , FilterValue(..)
    , Query(..)
    , QueryResult(..)
    , QueryFields(..)
    , QueryFieldsResult(..)
    , FieldDefinition(..)
    , ResultEntry(..)
    , ItemType(..)
    ) where

import Control.Applicative
import Data.Ratio (numerator, denominator)
import Text.JSON.Pretty (pp_value)
import Text.JSON.Types
import Text.JSON

import qualified Ganeti.Constants as C
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

-- | Supported items on which Qlang works.
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

-- * Main Qlang queries and responses.

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
    = EmptyFilter                             -- ^ No filter at all
    | AndFilter      [ Filter ]               -- ^ & [<expression>, ...]
    | OrFilter       [ Filter ]               -- ^ | [<expression>, ...]
    | NotFilter      Filter                   -- ^ ! <expression>
    | TrueFilter     FilterField              -- ^ ? <field>
    | EQFilter       FilterField FilterValue  -- ^ (=|!=) <field> <value>
    | LTFilter       FilterField FilterValue  -- ^ < <field> <value>
    | GTFilter       FilterField FilterValue  -- ^ > <field> <value>
    | LEFilter       FilterField FilterValue  -- ^ <= <field> <value>
    | GEFilter       FilterField FilterValue  -- ^ >= <field> <value>
    | RegexpFilter   FilterField FilterRegexp -- ^ =~ <field> <regexp>
    | ContainsFilter FilterField FilterValue  -- ^ =[] <list-field> <value>
      deriving (Show, Read, Eq)

-- | Serialiser for the 'Filter' data type.
showFilter :: Filter -> JSValue
showFilter (EmptyFilter)          = JSNull
showFilter (AndFilter exprs)      =
  JSArray $ (showJSON C.qlangOpAnd):(map showJSON exprs)
showFilter (OrFilter  exprs)      =
  JSArray $ (showJSON C.qlangOpOr):(map showJSON exprs)
showFilter (NotFilter flt)        =
  JSArray [showJSON C.qlangOpNot, showJSON flt]
showFilter (TrueFilter field)     =
  JSArray [showJSON C.qlangOpTrue, showJSON field]
showFilter (EQFilter field value) =
  JSArray [showJSON C.qlangOpEqual, showJSON field, showJSON value]
showFilter (LTFilter field value) =
  JSArray [showJSON C.qlangOpLt, showJSON field, showJSON value]
showFilter (GTFilter field value) =
  JSArray [showJSON C.qlangOpGt, showJSON field, showJSON value]
showFilter (LEFilter field value) =
  JSArray [showJSON C.qlangOpLe, showJSON field, showJSON value]
showFilter (GEFilter field value) =
  JSArray [showJSON C.qlangOpGe, showJSON field, showJSON value]
showFilter (RegexpFilter field regexp) =
  JSArray [showJSON C.qlangOpRegexp, showJSON field, showJSON regexp]
showFilter (ContainsFilter field value) =
  JSArray [showJSON C.qlangOpContains, showJSON field, showJSON value]

-- | Deserializer for the 'Filter' data type.
readFilter :: JSValue -> Result Filter
readFilter JSNull = Ok EmptyFilter
readFilter (JSArray (JSString op:args)) =
  readFilterArray (fromJSString op) args
readFilter v =
  Error $ "Cannot deserialise filter: expected array [string, args], got " ++
        show (pp_value v)

-- | Helper to deserialise an array corresponding to a single filter
-- and return the built filter. Note this looks generic but is (at
-- least currently) only used for the NotFilter.
readFilterArg :: (Filter -> Filter) -- ^ Constructor
              -> [JSValue]          -- ^ Single argument
              -> Result Filter
readFilterArg constr [flt] = constr <$> readJSON flt
readFilterArg _ v = Error $ "Cannot deserialise field, expected [filter]\
                            \ but got " ++ show (pp_value (showJSON v))

-- | Helper to deserialise an array corresponding to a single field
-- and return the built filter.
readFilterField :: (FilterField -> Filter) -- ^ Constructor
                -> [JSValue]               -- ^ Single argument
                -> Result Filter
readFilterField constr [field] = constr <$> readJSON field
readFilterField _ v = Error $ "Cannot deserialise field, expected [fieldname]\
                              \ but got " ++ show (pp_value (showJSON v))

-- | Helper to deserialise an array corresponding to a field and
-- value, returning the built filter.
readFilterFieldValue :: (JSON a) =>
                        (FilterField -> a -> Filter) -- ^ Constructor
                     -> [JSValue] -- ^ Arguments array
                     -> Result Filter
readFilterFieldValue constr [field, value] =
  constr <$> readJSON field <*> readJSON value
readFilterFieldValue _ v =
  Error $ "Cannot deserialise field/value pair, expected [fieldname, value]\
          \ but got " ++ show (pp_value (showJSON v))

-- | Inner deserialiser for 'Filter'.
readFilterArray :: String -> [JSValue] -> Result Filter
readFilterArray op args
  | op == C.qlangOpAnd      = AndFilter <$> mapM readJSON args
  | op == C.qlangOpOr       = OrFilter  <$> mapM readJSON args
  | op == C.qlangOpNot      = readFilterArg        NotFilter args
  | op == C.qlangOpTrue     = readFilterField      TrueFilter args
  | op == C.qlangOpEqual    = readFilterFieldValue EQFilter args
  | op == C.qlangOpLt       = readFilterFieldValue LTFilter args
  | op == C.qlangOpGt       = readFilterFieldValue GTFilter args
  | op == C.qlangOpLe       = readFilterFieldValue LEFilter args
  | op == C.qlangOpGe       = readFilterFieldValue GEFilter args
  | op == C.qlangOpRegexp   = readFilterFieldValue RegexpFilter args
  | op == C.qlangOpContains = readFilterFieldValue ContainsFilter args
  | otherwise = Error $ "Unknown filter operand '" ++ op ++ "'"

instance JSON Filter where
  showJSON = showFilter
  readJSON = readFilter

-- | Field name to filter on.
type FilterField = String

-- | Value to compare the field value to, for filtering purposes.
data FilterValue = QuotedString String
                 | NumericValue Integer
                   deriving (Read, Show, Eq)

-- | Serialiser for 'FilterValue'. The Python code just sends this to
-- JSON as-is, so we'll do the same.
showFilterValue :: FilterValue -> JSValue
showFilterValue (QuotedString str) = showJSON str
showFilterValue (NumericValue val) = showJSON val

-- | Decoder for 'FilterValue'. We have to see what it contains, since
-- the context doesn't give us hints on what to expect.
readFilterValue :: JSValue -> Result FilterValue
readFilterValue (JSString a) = Ok . QuotedString $ fromJSString a
readFilterValue (JSRational _ x) =
  if denominator x /= 1
    then Error $ "Cannot deserialise numeric filter value,\
                 \ expecting integral but\
                 \ got a fractional value: " ++ show x
    else Ok . NumericValue $ numerator x
readFilterValue v = Error $ "Cannot deserialise filter value, expecting\
                            \ string or integer, got " ++ show (pp_value v)

instance JSON FilterValue where
  showJSON = showFilterValue
  readJSON = readFilterValue

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

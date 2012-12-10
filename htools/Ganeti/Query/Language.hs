{-# LANGUAGE TemplateHaskell, CPP #-}

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

module Ganeti.Query.Language
    ( Filter(..)
    , FilterField
    , FilterValue(..)
    , FilterRegex -- note: we don't export the constructor, must use helpers
    , mkRegex
    , stringRegex
    , compiledRegex
    , Fields
    , Query(..)
    , QueryResult(..)
    , QueryFields(..)
    , QueryFieldsResult(..)
    , FieldName
    , FieldTitle
    , FieldType(..)
    , FieldDoc
    , FieldDefinition(..)
    , ResultEntry(..)
    , ResultStatus(..)
    , ResultValue
    , ItemType(..)
    , QueryTypeOp(..)
    , queryTypeOpToRaw
    , QueryTypeLuxi(..)
    , checkRS
    ) where

import Control.Applicative
import Data.Foldable
import Data.Traversable (Traversable, traverse, fmapDefault, foldMapDefault)
import Data.Ratio (numerator, denominator)
import Text.JSON.Pretty (pp_value)
import Text.JSON.Types
import Text.JSON
#ifndef NO_REGEX_PCRE
import qualified Text.Regex.PCRE as PCRE
#endif

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

-- | Check that ResultStatus is success or fail with descriptive
-- message.
checkRS :: (Monad m) => ResultStatus -> a -> m a
checkRS RSNormal val = return val
checkRS RSUnknown  _ = fail "Unknown field"
checkRS RSNoData   _ = fail "No data for a field"
checkRS RSUnavail  _ = fail "Ganeti reports unavailable data"
checkRS RSOffline  _ = fail "Ganeti reports resource as offline"

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
$(declareSADT "QueryTypeOp"
  [ ("QRCluster",  'C.qrCluster )
  , ("QRInstance", 'C.qrInstance )
  , ("QRNode",     'C.qrNode )
  , ("QRGroup",    'C.qrGroup )
  , ("QROs",       'C.qrOs )
  , ("QRExport",   'C.qrExport )
  ])
$(makeJSONInstance ''QueryTypeOp)

-- | Supported items on which Qlang works.
$(declareSADT "QueryTypeLuxi"
  [ ("QRLock",     'C.qrLock )
  , ("QRJob",      'C.qrJob )
  ])
$(makeJSONInstance ''QueryTypeLuxi)

-- | Overall query type.
data ItemType = ItemTypeLuxi QueryTypeLuxi
              | ItemTypeOpCode QueryTypeOp
                deriving (Show, Eq)

-- | Custom JSON decoder for 'ItemType'.
decodeItemType :: (Monad m) => JSValue -> m ItemType
decodeItemType (JSString s) =
  case queryTypeOpFromRaw s' of
    Just v -> return $ ItemTypeOpCode v
    Nothing ->
      case queryTypeLuxiFromRaw s' of
        Just v -> return $ ItemTypeLuxi v
        Nothing ->
          fail $ "Can't parse value '" ++ s' ++ "' as neither"
                 ++ "QueryTypeLuxi nor QueryTypeOp"
  where s' = fromJSString s
decodeItemType v = fail $ "Invalid value '" ++ show (pp_value v) ++
                   "for query type"

-- | Custom JSON instance for 'ItemType' since its encoding is not
-- consistent with the data type itself.
instance JSON ItemType where
  showJSON (ItemTypeLuxi x)  = showJSON x
  showJSON (ItemTypeOpCode y) = showJSON y
  readJSON = decodeItemType

-- * Sub data types for query2 queries and responses.

-- | Internal type of a regex expression (not exported).
#ifndef NO_REGEX_PCRE
type RegexType = PCRE.Regex
#else
type RegexType = ()
#endif

-- | List of requested fields.
type Fields = [ String ]

-- | Query2 filter expression. It's a parameteric type since we can
-- filter different \"things\"; e.g. field names, or actual field
-- getters, etc.
data Filter a
    = EmptyFilter                   -- ^ No filter at all
    | AndFilter      [ Filter a ]   -- ^ @&@ [/expression/, ...]
    | OrFilter       [ Filter a ]   -- ^ @|@ [/expression/, ...]
    | NotFilter      (Filter a)     -- ^ @!@ /expression/
    | TrueFilter     a              -- ^ @?@ /field/
    | EQFilter       a FilterValue  -- ^ @(=|!=)@ /field/ /value/
    | LTFilter       a FilterValue  -- ^ @<@ /field/ /value/
    | GTFilter       a FilterValue  -- ^ @>@ /field/ /value/
    | LEFilter       a FilterValue  -- ^ @<=@ /field/ /value/
    | GEFilter       a FilterValue  -- ^ @>=@ /field/ /value/
    | RegexpFilter   a FilterRegex  -- ^ @=~@ /field/ /regexp/
    | ContainsFilter a FilterValue  -- ^ @=[]@ /list-field/ /value/
      deriving (Show, Eq)

-- | Serialiser for the 'Filter' data type.
showFilter :: (JSON a) => Filter a -> JSValue
showFilter (EmptyFilter)          = JSNull
showFilter (AndFilter exprs)      =
  JSArray $ showJSON C.qlangOpAnd : map showJSON exprs
showFilter (OrFilter  exprs)      =
  JSArray $ showJSON C.qlangOpOr : map showJSON exprs
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
readFilter :: (JSON a) => JSValue -> Result (Filter a)
readFilter JSNull = Ok EmptyFilter
readFilter (JSArray (JSString op:args)) =
  readFilterArray (fromJSString op) args
readFilter v =
  Error $ "Cannot deserialise filter: expected array [string, args], got " ++
        show (pp_value v)

-- | Helper to deserialise an array corresponding to a single filter
-- and return the built filter. Note this looks generic but is (at
-- least currently) only used for the NotFilter.
readFilterArg :: (JSON a) =>
                 (Filter a -> Filter a) -- ^ Constructor
              -> [JSValue]              -- ^ Single argument
              -> Result (Filter a)
readFilterArg constr [flt] = constr <$> readJSON flt
readFilterArg _ v = Error $ "Cannot deserialise field, expected [filter]" ++
                            " but got " ++ show (pp_value (showJSON v))

-- | Helper to deserialise an array corresponding to a single field
-- and return the built filter.
readFilterField :: (JSON a) =>
                   (a -> Filter a)   -- ^ Constructor
                -> [JSValue]         -- ^ Single argument
                -> Result (Filter a)
readFilterField constr [field] = constr <$> readJSON field
readFilterField _ v = Error $ "Cannot deserialise field, expected" ++
                              " [fieldname] but got " ++
                              show (pp_value (showJSON v))

-- | Helper to deserialise an array corresponding to a field and
-- value, returning the built filter.
readFilterFieldValue :: (JSON a, JSON b) =>
                        (a -> b -> Filter a) -- ^ Constructor
                     -> [JSValue]            -- ^ Arguments array
                     -> Result (Filter a)
readFilterFieldValue constr [field, value] =
  constr <$> readJSON field <*> readJSON value
readFilterFieldValue _ v =
  Error $ "Cannot deserialise field/value pair, expected [fieldname, value]" ++
          " but got " ++ show (pp_value (showJSON v))

-- | Inner deserialiser for 'Filter'.
readFilterArray :: (JSON a) => String -> [JSValue] -> Result (Filter a)
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

instance (JSON a) => JSON (Filter a) where
  showJSON = showFilter
  readJSON = readFilter

-- Traversable implementation for 'Filter'.
traverseFlt :: (Applicative f) => (a -> f b) -> Filter a -> f (Filter b)
traverseFlt _ EmptyFilter       = pure EmptyFilter
traverseFlt f (AndFilter flts)  = AndFilter <$> traverse (traverseFlt f) flts
traverseFlt f (OrFilter  flts)  = OrFilter  <$> traverse (traverseFlt f) flts
traverseFlt f (NotFilter flt)   = NotFilter <$> traverseFlt f flt
traverseFlt f (TrueFilter a)    = TrueFilter <$> f a
traverseFlt f (EQFilter a fval) = EQFilter <$> f a <*> pure fval
traverseFlt f (LTFilter a fval) = LTFilter <$> f a <*> pure fval
traverseFlt f (GTFilter a fval) = GTFilter <$> f a <*> pure fval
traverseFlt f (LEFilter a fval) = LEFilter <$> f a <*> pure fval
traverseFlt f (GEFilter a fval) = GEFilter <$> f a <*> pure fval
traverseFlt f (RegexpFilter a re)     = RegexpFilter <$> f a <*> pure re
traverseFlt f (ContainsFilter a fval) = ContainsFilter <$> f a <*> pure fval

instance Traversable Filter where
  traverse = traverseFlt

instance Functor Filter where
  fmap = fmapDefault

instance Foldable Filter where
  foldMap = foldMapDefault

-- | Field name to filter on.
type FilterField = String

-- | Value to compare the field value to, for filtering purposes.
data FilterValue = QuotedString String
                 | NumericValue Integer
                   deriving (Show, Eq)

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
    then Error $ "Cannot deserialise numeric filter value," ++
                 " expecting integral but got a fractional value: " ++
                 show x
    else Ok . NumericValue $ numerator x
readFilterValue v = Error $ "Cannot deserialise filter value, expecting" ++
                            " string or integer, got " ++ show (pp_value v)

instance JSON FilterValue where
  showJSON = showFilterValue
  readJSON = readFilterValue

-- | Regexp to apply to the filter value, for filtering purposes. It
-- holds both the string format, and the \"compiled\" format, so that
-- we don't re-compile the regex at each match attempt.
data FilterRegex = FilterRegex
  { stringRegex   :: String      -- ^ The string version of the regex
  , compiledRegex :: RegexType   -- ^ The compiled regex
  }

-- | Builder for 'FilterRegex'. We always attempt to compile the
-- regular expression on the initialisation of the data structure;
-- this might fail, if the RE is not well-formed.
mkRegex :: (Monad m) => String -> m FilterRegex
#ifndef NO_REGEX_PCRE
mkRegex str = do
  compiled <- case PCRE.getVersion of
                Nothing -> fail $ "regex-pcre library compiled without" ++
                                  " libpcre, regex functionality not available"
                _ -> PCRE.makeRegexM str
  return $ FilterRegex str compiled
#else
mkRegex _ =
  fail $ "regex-pcre not found at compile time," ++
         " regex functionality not available"
#endif

-- | 'Show' instance: we show the constructor plus the string version
-- of the regex.
instance Show FilterRegex where
  show (FilterRegex re _) = "mkRegex " ++ show re

-- | 'Eq' instance: we only compare the string versions of the regexes.
instance Eq FilterRegex where
  (FilterRegex re1 _) == (FilterRegex re2 _) = re1 == re2

-- | 'JSON' instance: like for show and read instances, we work only
-- with the string component.
instance JSON FilterRegex where
  showJSON (FilterRegex re _) = showJSON re
  readJSON s = readJSON s >>= mkRegex

-- | Name of a field.
type FieldName = String
-- | Title of a field, when represented in tabular format.
type FieldTitle = String
-- | Human redable description of a field.
type FieldDoc = String

-- | Definition of a field.
$(buildObject "FieldDefinition" "fdef"
  [ simpleField "name"  [t| FieldName  |] -- FIXME: the name has restrictions
  , simpleField "title" [t| FieldTitle |]
  , simpleField "kind"  [t| FieldType  |]
  , simpleField "doc"   [t| FieldDoc   |]
  ])

--- | Single field entry result.
data ResultEntry = ResultEntry
  { rentryStatus :: ResultStatus      -- ^ The result status
  , rentryValue  :: Maybe ResultValue -- ^ The (optional) result value
  } deriving (Show, Eq)

instance JSON ResultEntry where
  showJSON (ResultEntry rs rv) =
    showJSON (showJSON rs, maybe JSNull showJSON rv)
  readJSON v = do
    (rs, rv) <- readJSON v
    rv' <- case rv of
             JSNull -> return Nothing
             x -> Just <$> readJSON x
    return $ ResultEntry rs rv'

-- | The type of one result row.
type ResultRow = [ ResultEntry ]

-- | Value of a field, in json encoding.
-- (its type will be depending on ResultStatus and FieldType)
type ResultValue = JSValue

-- * Main Qlang queries and responses.

-- | Query2 query.
data Query = Query ItemType Fields (Filter FilterField)

-- | Query2 result.
$(buildObject "QueryResult" "qres"
  [ simpleField "fields" [t| [ FieldDefinition ] |]
  , simpleField "data"   [t| [ ResultRow       ] |]
  ])

-- | Query2 Fields query.
-- (to get supported fields names, descriptions, and types)
data QueryFields = QueryFields ItemType Fields

-- | Query2 Fields result.
$(buildObject "QueryFieldsResult" "qfieldres"
  [ simpleField "fields" [t| [FieldDefinition ] |]
  ])

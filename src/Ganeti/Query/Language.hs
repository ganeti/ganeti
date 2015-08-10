{-# LANGUAGE TemplateHaskell, CPP, DeriveFunctor, DeriveFoldable,
             DeriveTraversable #-}

{-| Implementation of the Ganeti Query2 language.

 -}

{-

Copyright (C) 2012 Google Inc.
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

module Ganeti.Query.Language
    ( Filter(..)
    , filterArguments
    , FilterField
    , FilterValue(..)
    , FilterRegex -- note: we don't export the constructor, must use helpers
    , mkRegex
    , stringRegex
    , compiledRegex
    , showFilterValue
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
import Control.DeepSeq
import Data.Foldable
import Data.Traversable (Traversable)
import Data.Ratio (numerator, denominator)
import Text.JSON.Pretty (pp_value)
import Text.JSON.Types
import Text.JSON
#ifdef VERSION_regex_pcre
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

-- | No-op 'NFData' instance for 'ResultStatus', since it's a single
-- constructor data-type.
instance NFData ResultStatus

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
  , ("QFTNumberFloat", 'C.qftNumberFloat )
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
  , ("QRNetwork",  'C.qrNetwork )
  ])
$(makeJSONInstance ''QueryTypeOp)

-- | Supported items on which Qlang works.
$(declareSADT "QueryTypeLuxi"
  [ ("QRLock",     'C.qrLock )
  , ("QRJob",      'C.qrJob )
  , ("QRFilter",   'C.qrFilter )
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
#ifdef VERSION_regex_pcre
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
      deriving (Show, Eq, Ord, Functor, Foldable, Traversable)

-- | Get the \"things\" a filter talks about. This is useful, e.g.,
-- to decide which additional fields to fetch in a query depending
-- on live data.
filterArguments :: Filter a -> [a]
filterArguments = toList

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
  -- Legacy filters:
  -- - "=" is a legacy short-cut for "==".
  -- - "!=" is a legacy short-cut for "not (... == ..)".
  | op == C.qlangOpEqualLegacy = readFilterFieldValue EQFilter args
  | op == C.qlangOpNotEqual    = readFilterFieldValue
                                   (\f v -> NotFilter $ EQFilter f v) args
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

-- | Field name to filter on.
type FilterField = String

-- | Value to compare the field value to, for filtering purposes.
data FilterValue = QuotedString String
                 | NumericValue Integer
                   deriving (Show, Eq, Ord)

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
#ifdef VERSION_regex_pcre
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

-- | 'Ord' instance: we only compare the string versions of the regexes.
instance Ord FilterRegex where
  (FilterRegex re1 _) `compare` (FilterRegex re2 _) = re1 `compare` re2

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

instance NFData ResultEntry where
  rnf (ResultEntry rs rv) = rnf rs `seq` rnf rv

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

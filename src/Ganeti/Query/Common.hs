{-| Implementation of the Ganeti Query2 common objects.

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

module Ganeti.Query.Common
  ( rsNoData
  , rsUnavail
  , rsNormal
  , rsMaybe
  , rsUnknown
  , missingRuntime
  , rpcErrorToStatus
  , timeStampFields
  , uuidFields
  , serialFields
  , tagsFields
  , dictFieldGetter
  , buildQFTLookup
  , buildNdParamField
  ) where

import qualified Data.Map as Map
import Data.Maybe (fromMaybe)
import Text.JSON (JSON, showJSON)

import qualified Ganeti.Constants as C
import Ganeti.Config
import Ganeti.Objects
import Ganeti.Rpc
import Ganeti.Query.Language
import Ganeti.Query.Types

-- * Generic functions

-- | Conversion from 'VType' to 'FieldType'.
vTypeToQFT :: VType -> FieldType
vTypeToQFT VTypeString      = QFTOther
vTypeToQFT VTypeMaybeString = QFTOther
vTypeToQFT VTypeBool        = QFTBool
vTypeToQFT VTypeSize        = QFTUnit
vTypeToQFT VTypeInt         = QFTNumber

-- * Result helpers

-- | Helper for a result with no data.
rsNoData :: ResultEntry
rsNoData = ResultEntry RSNoData Nothing

-- | Helper for result for an entity which supports no such field.
rsUnavail :: ResultEntry
rsUnavail = ResultEntry RSUnavail Nothing

-- | Helper to declare a normal result.
rsNormal :: (JSON a) => a -> ResultEntry
rsNormal a = ResultEntry RSNormal $ Just (showJSON a)

-- | Helper to declare a result from a 'Maybe' (the item might be
-- missing, in which case we return no data). Note that there's some
-- ambiguity here: in some cases, we mean 'RSNoData', but in other
-- 'RSUnavail'; this is easy to solve in simple cases, but not in
-- nested dicts.
rsMaybe :: (JSON a) => Maybe a -> ResultEntry
rsMaybe = maybe rsNoData rsNormal

-- | Helper for unknown field result.
rsUnknown :: ResultEntry
rsUnknown = ResultEntry RSUnknown Nothing

-- | Helper for a missing runtime parameter.
missingRuntime :: FieldGetter a b
missingRuntime = FieldRuntime (\_ _ -> ResultEntry RSNoData Nothing)

-- * Error conversion

-- | Convert RpcError to ResultStatus
rpcErrorToStatus :: RpcError -> ResultStatus
rpcErrorToStatus (OfflineNodeError _) = RSOffline
rpcErrorToStatus _ = RSNoData

-- * Common fields

-- | The list of timestamp fields.
timeStampFields :: (TimeStampObject a) => FieldList a b
timeStampFields =
  [ (FieldDefinition "ctime" "CTime" QFTTimestamp "Creation timestamp",
     FieldSimple (rsNormal . cTimeOf), QffNormal)
  , (FieldDefinition "mtime" "MTime" QFTTimestamp "Modification timestamp",
     FieldSimple (rsNormal . mTimeOf), QffNormal)
  ]

-- | The list of UUID fields.
uuidFields :: (UuidObject a) => String -> FieldList a b
uuidFields name =
  [ (FieldDefinition "uuid" "UUID" QFTText  (name ++ " UUID"),
     FieldSimple (rsNormal . uuidOf), QffNormal) ]

-- | The list of serial number fields.
serialFields :: (SerialNoObject a) => String -> FieldList a b
serialFields name =
  [ (FieldDefinition "serial_no" "SerialNo" QFTNumber
     (name ++ " object serial number, incremented on each modification"),
     FieldSimple (rsNormal . serialOf), QffNormal) ]

-- | The list of tag fields.
tagsFields :: (TagsObject a) => FieldList a b
tagsFields =
  [ (FieldDefinition "tags" "Tags" QFTOther "Tags",
     FieldSimple (rsNormal . tagsOf), QffNormal) ]

-- * Generic parameter functions

-- | Returns a field from a (possibly missing) 'DictObject'. This is
-- used by parameter dictionaries, usually. Note that we have two
-- levels of maybe: the top level dict might be missing, or one key in
-- the dictionary might be.
dictFieldGetter :: (DictObject a) => String -> Maybe a -> ResultEntry
dictFieldGetter k = maybe rsNoData (rsMaybe . lookup k . toDict)

-- | Build an optimised lookup map from a Python _PARAMETER_TYPES
-- association list.
buildQFTLookup :: [(String, String)] -> Map.Map String FieldType
buildQFTLookup =
  Map.fromList .
  map (\(k, v) -> (k, maybe QFTOther vTypeToQFT (vTypeFromRaw v)))

-- | Ndparams optimised lookup map.
ndParamTypes :: Map.Map String FieldType
ndParamTypes = buildQFTLookup C.ndsParameterTypes

-- | Ndparams title map.
ndParamTitles :: Map.Map String FieldTitle
ndParamTitles = Map.fromList C.ndsParameterTitles

-- | Ndparam getter builder: given a field, it returns a FieldConfig
-- getter, that is a function that takes the config and the object and
-- returns the Ndparam field specified when the getter was built.
ndParamGetter :: (NdParamObject a) =>
                 String -- ^ The field we're building the getter for
              -> ConfigData -> a -> ResultEntry
ndParamGetter field config =
  dictFieldGetter field . getNdParamsOf config

-- | Builds the ndparam fields for an object.
buildNdParamField :: (NdParamObject a) => String -> FieldData a b
buildNdParamField field =
  let full_name = "ndp/" ++ field
      title = fromMaybe field $ field `Map.lookup` ndParamTitles
      qft = fromMaybe QFTOther $ field `Map.lookup` ndParamTypes
      desc = "The \"" ++ field ++ "\" node parameter"
  in (FieldDefinition full_name title qft desc,
      FieldConfig (ndParamGetter field), QffNormal)

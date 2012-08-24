{-| Implementation of the Ganeti Query2 functionality.

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

module Ganeti.Query.Query
    ( query
    , queryFields
    ) where

import Data.Maybe (fromMaybe)
import qualified Data.Map as Map

import Ganeti.BasicTypes
import Ganeti.HTools.JSON
import Ganeti.Qlang
import Ganeti.Query.Common
import Ganeti.Query.Types
import Ganeti.Query.Node
import Ganeti.Objects

-- * Helper functions

-- | Builds an unknown field definition.
mkUnknownFDef :: String -> FieldData a b
mkUnknownFDef name =
  ( FieldDefinition name name QFTUnknown ("Unknown field '" ++ name ++ "'")
  , FieldUnknown )

-- | Runs a field getter on the existing contexts.
execGetter :: ConfigData -> b -> a -> FieldGetter a b -> ResultEntry
execGetter _   _ item (FieldSimple getter)  = getter item
execGetter cfg _ item (FieldConfig getter)  = getter cfg item
execGetter _  rt item (FieldRuntime getter) = getter rt item
execGetter _   _ _    FieldUnknown          = rsUnknown

-- * Main query execution

-- | Helper to build the list of requested fields. This transforms the
-- list of string fields to a list of field defs and getters, with
-- some of them possibly being unknown fields.
getSelectedFields :: FieldMap a b  -- ^ Defined fields
                  -> [String]      -- ^ Requested fields
                  -> FieldList a b -- ^ Selected fields
getSelectedFields defined =
  map (\name -> fromMaybe (mkUnknownFDef name) $ name `Map.lookup` defined)

-- | Main query execution function.
query :: ConfigData   -- ^ The current configuration
      -> Query        -- ^ The query (item, fields, filter)
      -> IO (Result QueryResult) -- ^ Result

query cfg (Query QRNode fields _) = return $ do
  let selected = getSelectedFields nodeFieldsMap fields
      (fdefs, fgetters) = unzip selected
      nodes = Map.elems . fromContainer $ configNodes cfg
      fdata = map (\node -> map (execGetter cfg NodeRuntime node) fgetters)
              nodes
  return QueryResult { qresFields = fdefs, qresData = fdata }

query _ (Query qkind _ _) =
  return . Bad $ "Query '" ++ show qkind ++ "' not supported"

-- | Query fields call.
queryFields :: QueryFields -> Result QueryFieldsResult
queryFields (QueryFields QRNode fields) =
  let selected = if null fields
                   then map snd $ Map.toAscList nodeFieldsMap
                   else getSelectedFields nodeFieldsMap fields
  in Ok $ QueryFieldsResult (map fst selected)

queryFields (QueryFields qkind _) =
  Bad $ "QueryFields '" ++ show qkind ++ "' not supported"

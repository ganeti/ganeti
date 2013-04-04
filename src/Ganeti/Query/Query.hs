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

{-

TODO: problems with the current model:

1. There's nothing preventing a result such as ResultEntry RSNormal
Nothing, or ResultEntry RSNoData (Just ...); ideally, we would
separate the the RSNormal and other types; we would need a new data
type for this, though, with JSON encoding/decoding

2. We don't have a way to 'bind' a FieldDefinition's field type
(e.q. QFTBool) with the actual value that is returned from a
FieldGetter. This means that the various getter functions can return
divergent types for the same field when evaluated against multiple
items. This is bad; it only works today because we 'hide' everything
behind JSValue, but is not nice at all. We should probably remove the
separation between FieldDefinition and the FieldGetter, and introduce
a new abstract data type, similar to QFT*, that contains the values
too.

-}

module Ganeti.Query.Query
    ( query
    , queryFields
    , queryCompat
    , getRequestedNames
    , nameField
    ) where

import Control.DeepSeq
import Control.Monad (filterM, foldM)
import Control.Monad.Trans (lift)
import Data.List (intercalate)
import Data.Maybe (fromMaybe)
import qualified Data.Map as Map
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Config
import Ganeti.Errors
import Ganeti.JQueue
import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Query.Common
import Ganeti.Query.Filter
import qualified Ganeti.Query.Job as Query.Job
import Ganeti.Query.Group
import Ganeti.Query.Language
import Ganeti.Query.Node
import Ganeti.Query.Types
import Ganeti.Path
import Ganeti.Types
import Ganeti.Utils

-- * Helper functions

-- | Builds an unknown field definition.
mkUnknownFDef :: String -> FieldData a b
mkUnknownFDef name =
  ( FieldDefinition name name QFTUnknown ("Unknown field '" ++ name ++ "'")
  , FieldUnknown
  , QffNormal )

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

-- | Check whether list of queried fields contains live fields.
needsLiveData :: [FieldGetter a b] -> Bool
needsLiveData = any isRuntimeField

-- | Checks whether we have requested exactly some names. This is a
-- simple wrapper over 'requestedNames' and 'nameField'.
needsNames :: Query -> Maybe [FilterValue]
needsNames (Query kind _ qfilter) = requestedNames (nameField kind) qfilter

-- | Computes the name field for different query types.
nameField :: ItemType -> FilterField
nameField (ItemTypeLuxi QRJob) = "id"
nameField _ = "name"

-- | Extracts all quoted strings from a list, ignoring the
-- 'NumericValue' entries.
getAllQuotedStrings :: [FilterValue] -> [String]
getAllQuotedStrings =
  concatMap extractor
    where extractor (NumericValue _)   = []
          extractor (QuotedString val) = [val]

-- | Checks that we have either requested a valid set of names, or we
-- have a more complex filter.
getRequestedNames :: Query -> [String]
getRequestedNames qry =
  case needsNames qry of
    Just names -> getAllQuotedStrings names
    Nothing    -> []

-- | Compute the requested job IDs. This is custom since we need to
-- handle both strings and integers.
getRequestedJobIDs :: Filter FilterField -> Result [JobId]
getRequestedJobIDs qfilter =
  case requestedNames (nameField (ItemTypeLuxi QRJob)) qfilter of
    Nothing -> Ok []
    Just [] -> Ok []
    Just vals ->
      mapM (\e -> case e of
                    QuotedString s -> makeJobIdS s
                    NumericValue i -> makeJobId $ fromIntegral i
           ) vals

-- | Main query execution function.
query :: ConfigData   -- ^ The current configuration
      -> Bool         -- ^ Whether to collect live data
      -> Query        -- ^ The query (item, fields, filter)
      -> IO (ErrorResult QueryResult) -- ^ Result
query cfg live (Query (ItemTypeLuxi QRJob) fields qfilter) =
  queryJobs cfg live fields qfilter
query cfg live qry = queryInner cfg live qry $ getRequestedNames qry

-- | Inner query execution function.
queryInner :: ConfigData   -- ^ The current configuration
           -> Bool         -- ^ Whether to collect live data
           -> Query        -- ^ The query (item, fields, filter)
           -> [String]     -- ^ Requested names
           -> IO (ErrorResult QueryResult) -- ^ Result

queryInner cfg live (Query (ItemTypeOpCode QRNode) fields qfilter) wanted =
  runResultT $ do
  cfilter <- resultT $ compileFilter nodeFieldsMap qfilter
  let selected = getSelectedFields nodeFieldsMap fields
      (fdefs, fgetters, _) = unzip3 selected
      live' = live && needsLiveData fgetters
  nodes <- resultT $ case wanted of
             [] -> Ok . niceSortKey nodeName .
                   Map.elems . fromContainer $ configNodes cfg
             _  -> mapM (getNode cfg) wanted
  -- runs first pass of the filter, without a runtime context; this
  -- will limit the nodes that we'll contact for runtime data
  fnodes <- resultT $ filterM (\n -> evaluateFilter cfg Nothing n cfilter)
                      nodes
  -- here we would run the runtime data gathering, then filter again
  -- the nodes, based on existing runtime data
  nruntimes <- lift $ maybeCollectLiveData live' cfg fnodes
  let fdata = map (\(node, nrt) -> map (execGetter cfg nrt node) fgetters)
              nruntimes
  return QueryResult { qresFields = fdefs, qresData = fdata }

queryInner cfg _ (Query (ItemTypeOpCode QRGroup) fields qfilter) wanted =
  return $ do
  cfilter <- compileFilter groupFieldsMap qfilter
  let selected = getSelectedFields groupFieldsMap fields
      (fdefs, fgetters, _) = unzip3 selected
  groups <- case wanted of
              [] -> Ok . niceSortKey groupName .
                    Map.elems . fromContainer $ configNodegroups cfg
              _  -> mapM (getGroup cfg) wanted
  -- there is no live data for groups, so filtering is much simpler
  fgroups <- filterM (\n -> evaluateFilter cfg Nothing n cfilter) groups
  let fdata = map (\node ->
                       map (execGetter cfg GroupRuntime node) fgetters) fgroups
  return QueryResult {qresFields = fdefs, qresData = fdata }

queryInner _ _ (Query qkind _ _) _ =
  return . Bad . GenericError $ "Query '" ++ show qkind ++ "' not supported"

-- | Query jobs specific query function, needed as we need to accept
-- both 'QuotedString' and 'NumericValue' as wanted names.
queryJobs :: ConfigData                   -- ^ The current configuration
          -> Bool                         -- ^ Whether to collect live data
          -> [FilterField]                -- ^ Item
          -> Filter FilterField           -- ^ Filter
          -> IO (ErrorResult QueryResult) -- ^ Result
queryJobs cfg live fields qfilter =
  runResultT $ do
  rootdir <- lift queueDir
  let wanted_names = getRequestedJobIDs qfilter
      want_arch = Query.Job.wantArchived fields
  rjids <- case wanted_names of
             Bad msg -> resultT . Bad $ GenericError msg
             Ok [] -> if live
                        -- we can check the filesystem for actual jobs
                        then do
                          maybeJobIDs <-
                            lift (determineJobDirectories rootdir want_arch
                              >>= getJobIDs)
                          case maybeJobIDs of
                            Left e -> (resultT . Bad) . BlockDeviceError $
                              "Unable to fetch the job list: " ++ show e
                            Right jobIDs -> resultT . Ok $ sortJobIDs jobIDs
                        -- else we shouldn't look at the filesystem...
                        else return []
             Ok v -> resultT $ Ok v
  cfilter <- resultT $ compileFilter Query.Job.fieldsMap qfilter
  let selected = getSelectedFields Query.Job.fieldsMap fields
      (fdefs, fgetters, _) = unzip3 selected
      live' = live && needsLiveData fgetters
      disabled_data = Bad "live data disabled"
  -- runs first pass of the filter, without a runtime context; this
  -- will limit the jobs that we'll load from disk
  jids <- resultT $
          filterM (\jid -> evaluateFilter cfg Nothing jid cfilter) rjids
  -- here we run the runtime data gathering, filtering and evaluation,
  -- all in the same step, so that we don't keep jobs in memory longer
  -- than we need; we can't be fully lazy due to the multiple monad
  -- wrapping across different steps
  qdir <- lift queueDir
  fdata <- foldM
           -- big lambda, but we use many variables from outside it...
           (\lst jid -> do
              job <- lift $ if live'
                              then loadJobFromDisk qdir True jid
                              else return disabled_data
              pass <- resultT $ evaluateFilter cfg (Just job) jid cfilter
              let nlst = if pass
                           then let row = map (execGetter cfg job jid) fgetters
                                in rnf row `seq` row:lst
                           else lst
              -- evaluate nlst (to WHNF), otherwise we're too lazy
              return $! nlst
           ) [] jids
  return QueryResult { qresFields = fdefs, qresData = reverse fdata }

-- | Helper for 'queryFields'.
fieldsExtractor :: FieldMap a b -> [FilterField] -> QueryFieldsResult
fieldsExtractor fieldsMap fields =
  let selected = if null fields
                   then map snd $ Map.toAscList fieldsMap
                   else getSelectedFields fieldsMap fields
  in QueryFieldsResult (map (\(defs, _, _) -> defs) selected)

-- | Query fields call.
queryFields :: QueryFields -> ErrorResult QueryFieldsResult
queryFields (QueryFields (ItemTypeOpCode QRNode) fields) =
  Ok $ fieldsExtractor nodeFieldsMap fields

queryFields (QueryFields (ItemTypeOpCode QRGroup) fields) =
  Ok $ fieldsExtractor groupFieldsMap fields

queryFields (QueryFields (ItemTypeLuxi QRJob) fields) =
  Ok $ fieldsExtractor Query.Job.fieldsMap fields

queryFields (QueryFields qkind _) =
  Bad . GenericError $ "QueryFields '" ++ show qkind ++ "' not supported"

-- | Classic query converter. It gets a standard query result on input
-- and computes the classic style results.
queryCompat :: QueryResult -> ErrorResult [[J.JSValue]]
queryCompat (QueryResult fields qrdata) =
  case map fdefName $ filter ((== QFTUnknown) . fdefKind) fields of
    [] -> Ok $ map (map (maybe J.JSNull J.showJSON . rentryValue)) qrdata
    unknown -> Bad $ OpPrereqError ("Unknown output fields selected: " ++
                                    intercalate ", " unknown) ECodeInval

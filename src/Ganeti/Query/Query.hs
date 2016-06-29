{-# LANGUAGE TupleSections #-}

{-| Implementation of the Ganeti Query2 functionality.

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
    , NoDataRuntime
    , uuidField
    ) where

import Control.Arrow ((&&&))
import Control.DeepSeq
import Control.Monad (filterM, foldM, liftM, unless)
import Control.Monad.IO.Class
import Control.Monad.Trans (lift)
import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.Foldable as Foldable
import Data.List (intercalate, nub, find)
import Data.Maybe (fromMaybe)
import qualified Data.Map as Map
import qualified Data.Set as Set
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Config
import Ganeti.Errors
import Ganeti.JQueue
import Ganeti.JSON (Container, GenericContainer(..))
import Ganeti.Locking.Allocation (OwnerState, LockRequest(..), OwnerState(..))
import Ganeti.Locking.Locks (GanetiLocks, ClientId, lockName)
import Ganeti.Logging
import Ganeti.Objects
import Ganeti.Query.Common
import qualified Ganeti.Query.Export as Export
import qualified Ganeti.Query.FilterRules as FilterRules
import Ganeti.Query.Filter
import qualified Ganeti.Query.Instance as Instance
import qualified Ganeti.Query.Job as Query.Job
import qualified Ganeti.Query.Group as Group
import Ganeti.Query.Language
import qualified Ganeti.Query.Locks as Locks
import qualified Ganeti.Query.Network as Network
import qualified Ganeti.Query.Node as Node
import Ganeti.Query.Types
import Ganeti.Path
import Ganeti.THH.HsRPC (runRpcClient)
import Ganeti.Types
import Ganeti.Utils
import Ganeti.WConfd.Client (getWConfdClient, listLocksWaitingStatus)

-- | Collector type
data CollectorType a b
  = CollectorSimple     (Bool -> ConfigData -> [a] -> IO [(a, b)])
  | CollectorFieldAware (Bool -> ConfigData -> [String] -> [a] -> IO [(a, b)])

-- * Helper functions

-- | Builds an unknown field definition.
mkUnknownFDef :: String -> FieldData a b
mkUnknownFDef name =
  ( FieldDefinition name name QFTUnknown ("Unknown field '" ++ name ++ "'")
  , FieldUnknown
  , QffNormal )

-- | Runs a field getter on the existing contexts.
execGetter :: ConfigData -> b -> a -> FieldGetter a b -> ResultEntry
execGetter _   _  item (FieldSimple getter)        = getter item
execGetter cfg _  item (FieldConfig getter)        = getter cfg item
execGetter _   rt item (FieldRuntime getter)       = getter rt item
execGetter cfg rt item (FieldConfigRuntime getter) = getter cfg rt item
execGetter _   _  _    FieldUnknown                = rsUnknown

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
nameField (ItemTypeOpCode QRExport) = "node"
nameField _ = "name"

-- | Computes the uuid field, or the best possible substitute, for different
-- query types.
uuidField :: ItemType -> FilterField
uuidField (ItemTypeLuxi QRJob) = nameField (ItemTypeLuxi QRJob)
uuidField (ItemTypeOpCode QRExport) = nameField (ItemTypeOpCode QRExport)
uuidField _ = "uuid"

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
      liftM nub $
      mapM (\e -> case e of
                    QuotedString s -> makeJobIdS s
                    NumericValue i -> makeJobId $ fromIntegral i
           ) vals

-- | Generic query implementation for resources that are backed by
-- some configuration objects.
--
-- Different query types use the same 'genericQuery' function by providing
-- a collector function and a field map. The collector function retrieves
-- live data, and the field map provides both the requirements and the logic
-- necessary to retrieve the data needed for the field.
--
-- The 'b' type in the specification is the runtime. Every query can gather
-- additional live data related to the configuration object using the collector
-- to perform RPC calls.
--
-- The gathered data, or the failure to get it, is expressed through a runtime
-- object. The type of a runtime object is determined by every query type for
-- itself, and used exclusively by that query.
genericQuery :: FieldMap a b       -- ^ Maps field names to field definitions
             -> CollectorType a b  -- ^ Collector of live data
             -> (a -> String)      -- ^ Object to name function
             -> (ConfigData -> Container a) -- ^ Get all objects from config
             -> (ConfigData -> String -> ErrorResult a) -- ^ Lookup object
             -> ConfigData         -- ^ The config to run the query against
             -> Bool               -- ^ Whether the query should be run live
             -> [String]           -- ^ List of requested fields
             -> Filter FilterField -- ^ Filter field
             -> [String]           -- ^ List of requested names
             -> IO (ErrorResult QueryResult)
genericQuery fieldsMap collector nameFn configFn getFn cfg
             live fields qfilter wanted =
  runResultT $ do
  cfilter <- toError $ compileFilter fieldsMap qfilter
  let allfields = (++) fields . filter (not . (`elem` fields))
                  . ordNub $ filterArguments qfilter
      count = length fields
      selected = getSelectedFields fieldsMap allfields
      (fdefs, fgetters, _) = unzip3 selected
      live' = live && needsLiveData fgetters
  objects <- toError $ case wanted of
             [] -> Ok . niceSortKey nameFn .
                   Foldable.toList $ configFn cfg
             _  -> mapM (getFn cfg) wanted
  -- Run the first pass of the filter, without a runtime context; this will
  -- limit the objects that we'll contact for exports
  fobjects <- toError $
    filterM (\n -> evaluateQueryFilter cfg Nothing n cfilter) objects
  -- Gather the runtime data and filter the results again,
  -- based on the gathered data
  runtimes <- (case collector of
    CollectorSimple     collFn -> lift $ collFn live' cfg fobjects
    CollectorFieldAware collFn -> lift $ collFn live' cfg allfields fobjects)
    >>= (toError . filterM (\(obj, runtime) ->
      evaluateQueryFilter cfg (Just runtime) obj cfilter))
  let fdata = map (\(obj, runtime) ->
                     map (execGetter cfg runtime obj) fgetters)
              runtimes
  return QueryResult { qresFields = take count fdefs
                     , qresData = map (take count) fdata }

-- | Dummy recollection of the data for a lock from the prefected
-- data for all locks.
recollectLocksData :: ( [(GanetiLocks, [(ClientId, OwnerState)])]
                      , [(Integer, ClientId, [LockRequest GanetiLocks])]
                      )
                   -> Bool -> ConfigData -> [String]
                   -> IO [(String, Locks.RuntimeData)]
recollectLocksData (allLocks, pending) _ _  =
  let getPending lock = pending >>= \(_, cid, req) ->
        let req' = filter ((==) lock . lockName . lockAffected) req
        in case () of
          _ | any ((==) (Just OwnExclusive) . lockRequestType) req'
              -> [(cid, OwnExclusive)]
          _ | any ((==) (Just OwnShared) . lockRequestType) req'
              -> [(cid, OwnShared)]
          _ -> []
      lookuplock lock =  (,) lock
                          . maybe ([], getPending lock)
                                  (\(_, c) ->  (c, getPending lock))
                          . find ((==) lock . lockName . fst)
                          $ allLocks
  in return . map lookuplock

-- | Main query execution function.
query :: ConfigData   -- ^ The current configuration
      -> Bool         -- ^ Whether to collect live data
      -> Query        -- ^ The query (item, fields, filter)
      -> IO (ErrorResult QueryResult) -- ^ Result
query cfg live (Query (ItemTypeLuxi QRJob) fields qfilter) =
  queryJobs cfg live fields qfilter
query cfg live (Query (ItemTypeLuxi QRLock) fields qfilter) = runResultT $ do
  unless live (failError "Locks can only be queried live")
  cl <- liftIO $ do
     socketpath <- defaultWConfdSocket
     getWConfdClient socketpath
  livedata <- runRpcClient listLocksWaitingStatus cl
  logDebug $ "Live state of all locks is " ++ show livedata
  let allLocks = Set.toList . Set.unions
                 $ (Set.fromList . map fst $ fst livedata)
                   : map (\(_, _, req) -> Set.fromList $ map lockAffected req)
                      (snd livedata)
  answer <- liftIO $ genericQuery
             Locks.fieldsMap
             (CollectorSimple $ recollectLocksData livedata)
             id
             (const . GenericContainer . Map.fromList
              . map ((UTF8.fromString &&& id) . lockName) $ allLocks)
             (const Ok)
             cfg live fields qfilter []
  toError answer

query cfg live qry = queryInner cfg live qry $ getRequestedNames qry


-- | Dummy data collection fuction
dummyCollectLiveData :: Bool -> ConfigData -> [a] -> IO [(a, NoDataRuntime)]
dummyCollectLiveData _ _ = return . map (, NoDataRuntime)

-- | Inner query execution function.
queryInner :: ConfigData   -- ^ The current configuration
           -> Bool         -- ^ Whether to collect live data
           -> Query        -- ^ The query (item, fields, filter)
           -> [String]     -- ^ Requested names
           -> IO (ErrorResult QueryResult) -- ^ Result

queryInner cfg live (Query (ItemTypeOpCode QRNode) fields qfilter) wanted =
  genericQuery Node.fieldsMap (CollectorFieldAware Node.collectLiveData)
               nodeName configNodes getNode cfg live fields qfilter wanted

queryInner cfg live (Query (ItemTypeOpCode QRInstance) fields qfilter) wanted =
  genericQuery Instance.fieldsMap (CollectorFieldAware Instance.collectLiveData)
               (fromMaybe "" . instName) configInstances getInstance cfg live
               fields qfilter
               wanted

queryInner cfg live (Query (ItemTypeOpCode QRGroup) fields qfilter) wanted =
  genericQuery Group.fieldsMap (CollectorSimple dummyCollectLiveData) groupName
               configNodegroups getGroup cfg live fields qfilter wanted

queryInner cfg live (Query (ItemTypeOpCode QRNetwork) fields qfilter) wanted =
  genericQuery Network.fieldsMap (CollectorSimple dummyCollectLiveData)
               (fromNonEmpty . networkName)
               configNetworks getNetwork cfg live fields qfilter wanted

queryInner cfg live (Query (ItemTypeOpCode QRExport) fields qfilter) wanted =
  genericQuery Export.fieldsMap (CollectorSimple Export.collectLiveData)
               nodeName configNodes getNode cfg live fields qfilter wanted

queryInner cfg live (Query (ItemTypeLuxi QRFilter) fields qfilter) wanted =
  genericQuery FilterRules.fieldsMap (CollectorSimple dummyCollectLiveData)
               uuidOf configFilters getFilterRule cfg live fields qfilter wanted

queryInner _ _ (Query qkind _ _) _ =
  return . Bad . GenericError $ "Query '" ++ show qkind ++ "' not supported"

-- | Query jobs specific query function, needed as we need to accept
-- both 'QuotedString' and 'NumericValue' as wanted names.
queryJobs :: ConfigData                   -- ^ The current configuration
          -> Bool                         -- ^ Whether to collect live data
          -> [FilterField]                -- ^ Item
          -> Filter FilterField           -- ^ Filter
          -> IO (ErrorResult QueryResult) -- ^ Result
queryJobs cfg live fields qfilter = runResultT $ do
  rootdir <- lift queueDir
  wanted_names <- toErrorStr $ getRequestedJobIDs qfilter
  rjids <- case wanted_names of
       [] | live -> do -- we can check the filesystem for actual jobs
              let want_arch = Query.Job.wantArchived fields
              jobIDs <-
                withErrorT (BlockDeviceError .
                            (++) "Unable to fetch the job list: " . show) $
                  liftIO (determineJobDirectories rootdir want_arch)
                  >>= ResultT . getJobIDs
              return $ sortJobIDs jobIDs
              -- else we shouldn't look at the filesystem...
       v -> return v
  cfilter <- toError $ compileFilter Query.Job.fieldsMap qfilter
  let selected = getSelectedFields Query.Job.fieldsMap fields
      (fdefs, fgetters, _) = unzip3 selected
      (_, filtergetters, _) = unzip3 . getSelectedFields Query.Job.fieldsMap
                                $ Foldable.toList qfilter
      live' = live && needsLiveData (fgetters ++ filtergetters)
      disabled_data = Bad "live data disabled"
  -- runs first pass of the filter, without a runtime context; this
  -- will limit the jobs that we'll load from disk
  jids <- toError $
    filterM (\jid -> evaluateQueryFilter cfg Nothing jid cfilter) rjids
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
              pass <- toError $ evaluateQueryFilter cfg (Just job) jid cfilter
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
                   then map snd . niceSortKey fst $ Map.toList fieldsMap
                   else getSelectedFields fieldsMap fields
  in QueryFieldsResult (map (\(defs, _, _) -> defs) selected)

-- | Query fields call.
queryFields :: QueryFields -> ErrorResult QueryFieldsResult
queryFields (QueryFields (ItemTypeOpCode QRNode) fields) =
  Ok $ fieldsExtractor Node.fieldsMap fields

queryFields (QueryFields (ItemTypeOpCode QRGroup) fields) =
  Ok $ fieldsExtractor Group.fieldsMap fields

queryFields (QueryFields (ItemTypeOpCode QRNetwork) fields) =
  Ok $ fieldsExtractor Network.fieldsMap fields

queryFields (QueryFields (ItemTypeLuxi QRJob) fields) =
  Ok $ fieldsExtractor Query.Job.fieldsMap fields

queryFields (QueryFields (ItemTypeOpCode QRExport) fields) =
  Ok $ fieldsExtractor Export.fieldsMap fields

queryFields (QueryFields (ItemTypeOpCode QRInstance) fields) =
  Ok $ fieldsExtractor Instance.fieldsMap fields

queryFields (QueryFields (ItemTypeLuxi QRLock) fields) =
  Ok $ fieldsExtractor Locks.fieldsMap fields

queryFields (QueryFields (ItemTypeLuxi QRFilter) fields) =
  Ok $ fieldsExtractor FilterRules.fieldsMap fields

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

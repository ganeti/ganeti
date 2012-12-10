{-| Implementation of the Ganeti Query2 job queries.

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

module Ganeti.Query.Job
  ( RuntimeData
  , fieldsMap
  , loadRuntimeData
  , wantArchived
  ) where

import qualified Data.Map as Map
import qualified Text.JSON as J

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.JQueue
import Ganeti.OpCodes (opSummary, metaOpCode)
import Ganeti.Path
import Ganeti.Query.Common
import Ganeti.Query.Language
import Ganeti.Query.Types
import Ganeti.Types

-- | The runtime data for a job.
type RuntimeData = Result (QueuedJob, Bool)

-- | Job priority explanation.
jobPrioDoc :: String
jobPrioDoc = "Current job priority (" ++ show C.opPrioLowest ++ " to " ++
             show C.opPrioHighest ++ ")"

-- | Timestamp doc.
tsDoc :: String -> String
tsDoc = (++ " (tuple containing seconds and microseconds)")

-- | Wrapper for unavailable job.
maybeJob :: (J.JSON a) =>
            (QueuedJob -> a) -> RuntimeData -> JobId -> ResultEntry
maybeJob _ (Bad _) _      = rsUnavail
maybeJob f (Ok (v, _))  _ = rsNormal $ f v

-- | Simple helper for a job getter.
jobGetter :: (J.JSON a) => (QueuedJob -> a) -> FieldGetter JobId RuntimeData
jobGetter = FieldRuntime . maybeJob

-- | Simple helper for a per-opcode getter.
opsGetter :: (J.JSON a) => (QueuedOpCode -> a) -> FieldGetter JobId RuntimeData
opsGetter f = FieldRuntime $ maybeJob (map f . qjOps)

-- | Archived field name.
archivedField :: String
archivedField = "archived"

-- | Check whether we should look at archived jobs as well.
wantArchived :: [FilterField] -> Bool
wantArchived = (archivedField `elem`)

-- | List of all node fields. FIXME: QFF_JOB_ID on the id field.
jobFields :: FieldList JobId RuntimeData
jobFields =
  [ (FieldDefinition "id" "ID" QFTNumber "Job ID", FieldSimple rsNormal,
     QffNormal)
  , (FieldDefinition "status" "Status" QFTText "Job status",
     jobGetter calcJobStatus, QffNormal)
  , (FieldDefinition "priority" "Priority" QFTNumber jobPrioDoc,
     jobGetter calcJobPriority, QffNormal)
  , (FieldDefinition archivedField "Archived" QFTBool
       "Whether job is archived",
     FieldRuntime (\jinfo _ -> case jinfo of
                                 Ok (_, archive) -> rsNormal archive
                                 _ -> rsUnavail), QffNormal)
  , (FieldDefinition "ops" "OpCodes" QFTOther "List of all opcodes",
     opsGetter qoInput, QffNormal)
  , (FieldDefinition "opresult" "OpCode_result" QFTOther
       "List of opcodes results", opsGetter qoResult, QffNormal)
  , (FieldDefinition "opstatus" "OpCode_status" QFTOther
       "List of opcodes status", opsGetter qoStatus, QffNormal)
  , (FieldDefinition "oplog" "OpCode_log" QFTOther
       "List of opcode output logs", opsGetter qoLog, QffNormal)
  , (FieldDefinition "opstart" "OpCode_start" QFTOther
       "List of opcode start timestamps (before acquiring locks)",
     opsGetter qoStartTimestamp, QffNormal)
  , (FieldDefinition "opexec" "OpCode_exec" QFTOther
       "List of opcode execution start timestamps (after acquiring locks)",
     opsGetter qoExecTimestamp, QffNormal)
  , (FieldDefinition "opend" "OpCode_end" QFTOther
       "List of opcode execution end timestamps",
     opsGetter qoEndTimestamp, QffNormal)
  , (FieldDefinition "oppriority" "OpCode_prio" QFTOther
       "List of opcode priorities", opsGetter qoPriority, QffNormal)
  , (FieldDefinition "summary" "Summary" QFTOther
       "List of per-opcode summaries",
     opsGetter (opSummary . metaOpCode . qoInput), QffNormal)
  , (FieldDefinition "received_ts" "Received" QFTOther
       (tsDoc "Timestamp of when job was received"),
     jobGetter qjReceivedTimestamp, QffTimestamp)
  , (FieldDefinition "start_ts" "Start" QFTOther
       (tsDoc "Timestamp of job start"),
     jobGetter qjStartTimestamp, QffTimestamp)
  , (FieldDefinition "end_ts" "End" QFTOther
       (tsDoc "Timestamp of job end"),
     jobGetter qjEndTimestamp, QffTimestamp)
  ]

-- | The node fields map.
fieldsMap :: FieldMap JobId RuntimeData
fieldsMap =
  Map.fromList $ map (\v@(f, _, _) -> (fdefName f, v)) jobFields

-- | Load the given jobs from disk.
loadRuntimeData :: [JobId] -> Bool -> IO [RuntimeData]
loadRuntimeData ids archived = do
  qdir <- queueDir
  mapM (loadJobFromDisk qdir archived) ids

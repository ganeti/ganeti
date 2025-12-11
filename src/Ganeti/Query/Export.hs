{-| Implementation of the Ganeti Query2 export queries.

 -}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.Query.Export
  ( Runtime
  , fieldsMap
  , collectLiveData
  ) where

import Control.Monad (liftM)

import Ganeti.Objects
import Ganeti.Rpc
import Ganeti.Query.Language
import Ganeti.Query.Common
import Ganeti.Query.Types

-- | The parsed result of the ExportList. We keep the runtime as a tuple
-- of the exported name (as a 'ResultEntry'), the 'export_path' and an optional
-- 'export_du' (in mebibytes). This preserves the previous behaviour
type Runtime = (ResultEntry, String, Maybe Int)

-- | Fields that require disk usage calculation.
exportDuFields :: [String]
exportDuFields = ["export_du"]

-- | Small helper for rpc to rs.
rpcErrToRs :: RpcError -> ResultEntry
rpcErrToRs err = ResultEntry (rpcErrorToStatus err) Nothing

-- | Helper for extracting fields from RPC result.
rpcExtractor :: Node -> Either RpcError RpcResultExportList
             -> [(Node, Runtime)]
rpcExtractor node (Right res) =
  [ (node, ( rsNormal (exportInfoName e)
           , exportInfoExportPath e
           , exportInfoExportDu e))
    | e <- rpcResExportListExports res ]
rpcExtractor node (Left err)  = [(node, (rpcErrToRs err, "", Nothing))]

-- | List of all export fields.
exportFields :: FieldList Node Runtime
exportFields =
  [ (FieldDefinition "node" "Node" QFTText
     "Node name",
     FieldRuntime (\_ n -> rsNormal $ nodeName n), QffHostname)
  , (FieldDefinition "export" "Export" QFTText
     "Export name",
     FieldRuntime (\(rt, _, _) _ -> rt), QffNormal)
  , (FieldDefinition "export_path" "ExpPath" QFTText
     "Export path on disk",
     FieldRuntime exportPathFieldExtract, QffNormal)
  , (FieldDefinition "export_du" "ExpDUsage" QFTUnit
     "Used size on disk for the export",
     FieldRuntime exportDuFieldExtract, QffNormal)
  ]

-- | Extract the export path from runtime data.
exportPathFieldExtract :: Runtime -> Node -> ResultEntry
exportPathFieldExtract (rt, path, _) _ =
  case rentryStatus rt of
    RSNormal -> rsNormal path
    _        -> rsUnavail

-- | Extract the export disk usage from runtime data.
exportDuFieldExtract :: Runtime -> Node -> ResultEntry
exportDuFieldExtract (rt, _, du) _ =
  case (rentryStatus rt, du) of
    (RSNormal, Just d) -> rsNormal d
    _                  -> rsUnavail

-- | The node fields map.
fieldsMap :: FieldMap Node Runtime
fieldsMap = fieldListToFieldMap exportFields

-- | Collect live data from RPC query if enabled.
--
-- Note that this function is \"funny\": the returned rows will not be
-- 1:1 with the input, as nodes without exports will be pruned,
-- whereas nodes with multiple exports will be listed multiple times.
collectLiveData:: Bool -> ConfigData -> [String] -> [Node]
              -> IO [(Node, Runtime)]
collectLiveData False _ _ nodes =
  return [(n, (rpcErrToRs $ RpcResultError "Live data disabled", "", Nothing))
          | n <- nodes]
collectLiveData True _ fields nodes = do
  let calc_du = any (`elem` fields) exportDuFields
  concatMap (uncurry rpcExtractor) `liftM`
    executeRpcCall nodes (RpcCallExportList calc_du)

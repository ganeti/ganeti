{-| Implementation of the Ganeti Query2 export queries.

 -}

{-

Copyright (C) 2013 Google Inc.

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

module Ganeti.Query.Export
  ( Runtime
  , fieldsMap
  , collectLiveData
  ) where

import Control.Monad (liftM)
import qualified Data.Map as Map

import Ganeti.Objects
import Ganeti.Rpc
import Ganeti.Query.Language
import Ganeti.Query.Common
import Ganeti.Query.Types

-- | The parsed result of the ExportList. This is a bit tricky, in
-- that we already do parsing of the results in the RPC calls, so the
-- runtime type is a plain 'ResultEntry', as we have just one type.
type Runtime = ResultEntry

-- | Small helper for rpc to rs.
rpcErrToRs :: RpcError -> ResultEntry
rpcErrToRs err = ResultEntry (rpcErrorToStatus err) Nothing

-- | Helper for extracting fields from RPC result.
rpcExtractor :: Node -> Either RpcError RpcResultExportList
             -> [(Node, ResultEntry)]
rpcExtractor node (Right res) =
  [(node, rsNormal path) | path <- rpcResExportListExports res]
rpcExtractor node (Left err)  = [(node, rpcErrToRs err)]

-- | List of all node fields.
exportFields :: FieldList Node Runtime
exportFields =
  [ (FieldDefinition "node" "Node" QFTText "Node name",
     FieldRuntime (\_ n -> rsNormal $ nodeName n), QffHostname)
  , (FieldDefinition "export" "Export" QFTText "Export name",
     FieldRuntime (curry fst), QffNormal)
  ]

-- | The node fields map.
fieldsMap :: FieldMap Node Runtime
fieldsMap =
  Map.fromList $ map (\v@(f, _, _) -> (fdefName f, v)) exportFields

-- | Collect live data from RPC query if enabled.
--
-- Note that this function is \"funny\": the returned rows will not be
-- 1:1 with the input, as nodes without exports will be pruned,
-- whereas nodes with multiple exports will be listed multiple times.
collectLiveData:: Bool -> ConfigData -> [Node] -> IO [(Node, Runtime)]
collectLiveData False _ nodes =
  return [(n, rpcErrToRs $ RpcResultError "Live data disabled") | n <- nodes]
collectLiveData True _ nodes =
  concatMap (uncurry rpcExtractor) `liftM`
    executeRpcCall nodes RpcCallExportList

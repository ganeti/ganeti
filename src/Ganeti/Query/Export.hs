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

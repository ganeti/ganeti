{-| Implementation of the LUXI loader.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Ganeti.HTools.Backend.Luxi
  ( loadData
  , parseData
  ) where

import qualified Control.Exception as E
import Control.Monad (liftM)
import Control.Monad.Fail (MonadFail)
import Text.JSON.Types
import qualified Text.JSON

import Ganeti.BasicTypes
import Ganeti.Errors
import qualified Ganeti.Luxi as L
import qualified Ganeti.Query.Language as Qlang
import Ganeti.Types (Hypervisor(..))
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.JSON (fromObj, fromJVal, tryFromObj, arrayMaybeFromJVal)

{-# ANN module "HLint: ignore Eta reduce" #-}

-- * Utility functions

-- | Get values behind \"data\" part of the result.
getData :: (MonadFail m) => JSValue -> m JSValue
getData (JSObject o) = fromObj (fromJSObject o) "data"
getData x = fail $ "Invalid input, expected dict entry but got " ++ show x

-- | Converts a (status, value) into m value, if possible.
parseQueryField :: (MonadFail m) => JSValue -> m (JSValue, JSValue)
parseQueryField (JSArray [status, result]) = return (status, result)
parseQueryField o =
  fail $ "Invalid query field, expected (status, value) but got " ++ show o

-- | Parse a result row.
parseQueryRow :: (MonadFail m) => JSValue -> m [(JSValue, JSValue)]
parseQueryRow (JSArray arr) = mapM parseQueryField arr
parseQueryRow o =
  fail $ "Invalid query row result, expected array but got " ++ show o

-- | Parse an overall query result and get the [(status, value)] list
-- for each element queried.
parseQueryResult :: (MonadFail m) => JSValue -> m [[(JSValue, JSValue)]]
parseQueryResult (JSArray arr) = mapM parseQueryRow arr
parseQueryResult o =
  fail $ "Invalid query result, expected array but got " ++ show o

-- | Prepare resulting output as parsers expect it.
extractArray :: (MonadFail m) => JSValue -> m [[(JSValue, JSValue)]]
extractArray v =
  getData v >>= parseQueryResult

-- | Testing result status for more verbose error message.
fromJValWithStatus :: (Text.JSON.JSON a, MonadFail m) =>
  (JSValue, JSValue) -> m a
fromJValWithStatus (st, v) = do
  st' <- fromJVal st
  Qlang.checkRS st' v >>= fromJVal

annotateConvert :: String -> String -> String -> Result a -> Result a
annotateConvert otype oname oattr =
  annotateResult $ otype ++ " '" ++ oname ++
    "', error while reading attribute '" ++ oattr ++ "'"

-- | Annotate errors when converting values with owner/attribute for
-- better debugging.
genericConvert :: (Text.JSON.JSON a) =>
                  String             -- ^ The object type
               -> String             -- ^ The object name
               -> String             -- ^ The attribute we're trying to convert
               -> (JSValue, JSValue) -- ^ The value we're trying to convert
               -> Result a           -- ^ The annotated result
genericConvert otype oname oattr =
  annotateConvert otype oname oattr . fromJValWithStatus

convertArrayMaybe :: (Text.JSON.JSON a) =>
                  String             -- ^ The object type
               -> String             -- ^ The object name
               -> String             -- ^ The attribute we're trying to convert
               -> (JSValue, JSValue) -- ^ The value we're trying to convert
               -> Result [Maybe a]   -- ^ The annotated result
convertArrayMaybe otype oname oattr (st, v) = do
  st' <- fromJVal st
  Qlang.checkRS st' v >>=
    annotateConvert otype oname oattr . arrayMaybeFromJVal

-- * Data querying functionality

-- | The input data for node query.
queryNodesMsg :: L.LuxiOp
queryNodesMsg =
  L.Query (Qlang.ItemTypeOpCode Qlang.QRNode)
     ["name", "mtotal", "mnode", "mfree", "dtotal", "dfree",
      "ctotal", "cnos", "offline", "drained", "vm_capable",
      "ndp/spindle_count", "group.uuid", "tags",
      "ndp/exclusive_storage", "sptotal", "spfree", "ndp/cpu_speed"]
     Qlang.EmptyFilter

-- | The input data for instance query.
queryInstancesMsg :: L.LuxiOp
queryInstancesMsg =
  L.Query (Qlang.ItemTypeOpCode Qlang.QRInstance)
     ["name", "disk_usage", "be/memory", "be/vcpus",
      "status", "pnode", "snodes", "tags",
      "be/auto_balance", "disk_template",
      "be/spindle_use", "disk.sizes", "disk.spindles",
      "forthcoming"] Qlang.EmptyFilter

-- | The input data for cluster query.
queryClusterInfoMsg :: L.LuxiOp
queryClusterInfoMsg = L.QueryClusterInfo

-- | The input data for node group query.
queryGroupsMsg :: L.LuxiOp
queryGroupsMsg =
  L.Query (Qlang.ItemTypeOpCode Qlang.QRGroup)
     ["uuid", "name", "alloc_policy", "ipolicy", "tags"]
     Qlang.EmptyFilter

-- | Wraper over 'callMethod' doing node query.
queryNodes :: L.Client -> IO (Result JSValue)
queryNodes = liftM errToResult . L.callMethod queryNodesMsg

-- | Wraper over 'callMethod' doing instance query.
queryInstances :: L.Client -> IO (Result JSValue)
queryInstances = liftM errToResult . L.callMethod queryInstancesMsg

-- | Wrapper over 'callMethod' doing cluster information query.
queryClusterInfo :: L.Client -> IO (Result JSValue)
queryClusterInfo = liftM errToResult . L.callMethod queryClusterInfoMsg

-- | Wrapper over callMethod doing group query.
queryGroups :: L.Client -> IO (Result JSValue)
queryGroups = liftM errToResult . L.callMethod queryGroupsMsg

-- | Parse a instance list in JSON format.
getInstances :: NameAssoc
             -> JSValue
             -> Result [(String, Instance.Instance)]
getInstances ktn arr = extractArray arr >>= mapM (parseInstance ktn)

-- | Construct an instance from a JSON object.
parseInstance :: NameAssoc
              -> [(JSValue, JSValue)]
              -> Result (String, Instance.Instance)
parseInstance ktn [ name, disk, mem, vcpus
                  , status, pnode, snodes, tags
                  , auto_balance, disk_template, su
                  , dsizes, dspindles, forthcoming ] = do
  xname <- annotateResult "Parsing new instance" (fromJValWithStatus name)
  let convert a = genericConvert "Instance" xname a
  xdisk <- convert "disk_usage" disk
  xmem <- convert "be/memory" mem
  xvcpus <- convert "be/vcpus" vcpus
  xpnode <- convert "pnode" pnode >>= lookupNode ktn xname
  xsnodes <- convert "snodes" snodes::Result [String]
  snode <- case xsnodes of
             [] -> return Node.noSecondary
             x:_ -> lookupNode ktn xname x
  xrunning <- convert "status" status
  xtags <- convert "tags" tags
  xauto_balance <- convert "auto_balance" auto_balance
  xdt <- convert "disk_template" disk_template
  xsu <- convert "be/spindle_use" su
  xdsizes <- convert "disk.sizes" dsizes
  xdspindles <- convertArrayMaybe "Instance" xname "disk.spindles" dspindles
  xforthcoming <- convert "forthcoming" forthcoming
  let disks = zipWith Instance.Disk xdsizes xdspindles
      inst = Instance.create xname xmem xdisk disks
             xvcpus xrunning xtags xauto_balance xpnode snode xdt xsu []
             xforthcoming
  return (xname, inst)

parseInstance _ v = fail ("Invalid instance query result: " ++ show v)

-- | Parse a node list in JSON format.
getNodes :: NameAssoc -> JSValue -> Result [(String, Node.Node)]
getNodes ktg arr = extractArray arr >>= mapM (parseNode ktg)

-- | Construct a node from a JSON object.
parseNode :: NameAssoc -> [(JSValue, JSValue)] -> Result (String, Node.Node)
parseNode ktg [ name, mtotal, mnode, mfree, dtotal, dfree
              , ctotal, cnos, offline, drained, vm_capable, spindles, g_uuid
              , tags, excl_stor, sptotal, spfree, cpu_speed ]
    = do
  xname <- annotateResult "Parsing new node" (fromJValWithStatus name)
  let convert a = genericConvert "Node" xname a
  xoffline <- convert "offline" offline
  xdrained <- convert "drained" drained
  xvm_capable <- convert "vm_capable" vm_capable
  xgdx   <- convert "group.uuid" g_uuid >>= lookupGroup ktg xname
  xtags <- convert "tags" tags
  xexcl_stor <- convert "exclusive_storage" excl_stor
  xcpu_speed <- convert "cpu_speed" cpu_speed
  let live = not xoffline && xvm_capable
      lvconvert def n d = eitherLive live def $ convert n d
  xsptotal <- if xexcl_stor
              then lvconvert 0 "sptotal" sptotal
              else convert "spindles" spindles
  let xspfree = genericResult (const (0 :: Int)) id
                  $ lvconvert 0 "spfree" spfree
                  -- "spfree" might be missing, if sharedfile is the only
                  -- supported disk template
  xmtotal <- lvconvert 0.0 "mtotal" mtotal
  xmnode <- lvconvert 0 "mnode" mnode
  xmfree <- lvconvert 0 "mfree" mfree
  let xdtotal = genericResult (const 0.0) id
                  $ lvconvert 0.0 "dtotal" dtotal
      xdfree = genericResult (const 0) id
                 $ lvconvert 0 "dfree" dfree
      -- "dtotal" and "dfree" might be missing, e.g., if sharedfile
      -- is the only supported disk template
  xctotal <- lvconvert 0.0 "ctotal" ctotal
  xcnos <- lvconvert 0 "cnos" cnos
  let node = flip Node.setCpuSpeed xcpu_speed .
             flip Node.setNodeTags xtags $
             Node.create xname xmtotal xmnode xmfree xdtotal xdfree
             xctotal xcnos (not live || xdrained) xsptotal xspfree
             xgdx xexcl_stor
  return (xname, node)

parseNode _ v = fail ("Invalid node query result: " ++ show v)

-- | Parses the cluster tags.
getClusterData :: JSValue -> Result ([String], IPolicy, String, Hypervisor)
getClusterData (JSObject obj) = do
  let errmsg = "Parsing cluster info"
      obj' = fromJSObject obj
  ctags <- tryFromObj errmsg obj' "tags"
  cpol <- tryFromObj errmsg obj' "ipolicy"
  master <- tryFromObj errmsg obj' "master"
  hypervisor <- tryFromObj errmsg obj' "default_hypervisor"
  return (ctags, cpol, master, hypervisor)

getClusterData _ = Bad "Cannot parse cluster info, not a JSON record"

-- | Parses the cluster groups.
getGroups :: JSValue -> Result [(String, Group.Group)]
getGroups jsv = extractArray jsv >>= mapM parseGroup

-- | Parses a given group information.
parseGroup :: [(JSValue, JSValue)] -> Result (String, Group.Group)
parseGroup [uuid, name, apol, ipol, tags] = do
  xname <- annotateResult "Parsing new group" (fromJValWithStatus name)
  let convert a = genericConvert "Group" xname a
  xuuid <- convert "uuid" uuid
  xapol <- convert "alloc_policy" apol
  xipol <- convert "ipolicy" ipol
  xtags <- convert "tags" tags
  -- TODO: parse networks to which this group is connected
  return (xuuid, Group.create xname xuuid xapol [] xipol xtags)

parseGroup v = fail ("Invalid group query result: " ++ show v)

-- * Main loader functionality

-- | Builds the cluster data by querying a given socket name.
readData :: String -- ^ Unix socket to use as source
         -> IO (Result JSValue, Result JSValue, Result JSValue, Result JSValue)
readData master =
  E.bracket
       (L.getLuxiClient master)
       L.closeClient
       (\s -> do
          nodes <- queryNodes s
          instances <- queryInstances s
          cinfo <- queryClusterInfo s
          groups <- queryGroups s
          return (groups, nodes, instances, cinfo)
       )

-- | Converts the output of 'readData' into the internal cluster
-- representation.
parseData :: (Result JSValue, Result JSValue, Result JSValue, Result JSValue)
          -> Result ClusterData
parseData (groups, nodes, instances, cinfo) = do
  group_data <- groups >>= getGroups
  let (group_names, group_idx) = assignIndices group_data
  node_data <- nodes >>= getNodes group_names
  let (node_names, node_idx) = assignIndices node_data
  inst_data <- instances >>= getInstances node_names
  let (_, inst_idx) = assignIndices inst_data
  (ctags, cpol, master, hypervisor) <- cinfo >>= getClusterData
  node_idx' <- setMaster node_names node_idx master
  let node_idx'' = Container.map (`Node.setHypervisor` hypervisor) node_idx'
  return (ClusterData group_idx node_idx'' inst_idx ctags cpol)

-- | Top level function for data loading.
loadData :: String -- ^ Unix socket to use as source
         -> IO (Result ClusterData)
loadData = fmap parseData . readData

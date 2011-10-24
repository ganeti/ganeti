{-| Implementation of the LUXI loader.

-}

{-

Copyright (C) 2009, 2010, 2011 Google Inc.

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

module Ganeti.HTools.Luxi
    (
      loadData
    , parseData
    ) where

import qualified Control.Exception as E
import Text.JSON.Types
import qualified Text.JSON

import qualified Ganeti.Luxi as L
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Utils (fromJVal, annotateResult, tryFromObj, asJSObject,
                            fromObj)

-- * Utility functions

-- | Get values behind \"data\" part of the result.
getData :: (Monad m) => JSValue -> m JSValue
getData (JSObject o) = fromObj (fromJSObject o) "data"
getData x = fail $ "Invalid input, expected dict entry but got " ++ show x

-- | Converts a (status, value) into m value, if possible.
parseQueryField :: (Monad m) => JSValue -> m (JSValue, JSValue)
parseQueryField (JSArray [status, result]) = return (status, result)
parseQueryField o =
    fail $ "Invalid query field, expected (status, value) but got " ++ show o

-- | Parse a result row.
parseQueryRow :: (Monad m) => JSValue -> m [(JSValue, JSValue)]
parseQueryRow (JSArray arr) = mapM parseQueryField arr
parseQueryRow o =
    fail $ "Invalid query row result, expected array but got " ++ show o

-- | Parse an overall query result and get the [(status, value)] list
-- for each element queried.
parseQueryResult :: (Monad m) => JSValue -> m [[(JSValue, JSValue)]]
parseQueryResult (JSArray arr) = mapM parseQueryRow arr
parseQueryResult o =
    fail $ "Invalid query result, expected array but got " ++ show o

-- | Prepare resulting output as parsers expect it.
extractArray :: (Monad m) => JSValue -> m [[(JSValue, JSValue)]]
extractArray v =
  getData v >>= parseQueryResult

-- | Testing result status for more verbose error message.
fromJValWithStatus :: (Text.JSON.JSON a, Monad m) => (JSValue, JSValue) -> m a
fromJValWithStatus (st, v) = do
    st' <- fromJVal st
    L.checkRS st' v >>= fromJVal

-- | Annotate errors when converting values with owner/attribute for
-- better debugging.
genericConvert :: (Text.JSON.JSON a) =>
                  String             -- ^ The object type
               -> String             -- ^ The object name
               -> String             -- ^ The attribute we're trying to convert
               -> (JSValue, JSValue) -- ^ The value we're trying to convert
               -> Result a           -- ^ The annotated result
genericConvert otype oname oattr =
    annotateResult (otype ++ " '" ++ oname ++
                    "', error while reading attribute '" ++
                    oattr ++ "'") . fromJValWithStatus

-- * Data querying functionality

-- | The input data for node query.
queryNodesMsg :: L.LuxiOp
queryNodesMsg =
  L.Query L.QRNode ["name", "mtotal", "mnode", "mfree", "dtotal", "dfree",
                    "ctotal", "offline", "drained", "vm_capable",
                    "group.uuid"] ()

-- | The input data for instance query.
queryInstancesMsg :: L.LuxiOp
queryInstancesMsg =
    L.Query L.QRInstance ["name", "disk_usage", "be/memory", "be/vcpus",
                          "status", "pnode", "snodes", "tags", "oper_ram",
                          "be/auto_balance", "disk_template"] ()

-- | The input data for cluster query.
queryClusterInfoMsg :: L.LuxiOp
queryClusterInfoMsg = L.QueryClusterInfo

-- | The input data for node group query.
queryGroupsMsg :: L.LuxiOp
queryGroupsMsg =
  L.Query L.QRGroup ["uuid", "name", "alloc_policy"] ()

-- | Wraper over 'callMethod' doing node query.
queryNodes :: L.Client -> IO (Result JSValue)
queryNodes = L.callMethod queryNodesMsg

-- | Wraper over 'callMethod' doing instance query.
queryInstances :: L.Client -> IO (Result JSValue)
queryInstances = L.callMethod queryInstancesMsg

-- | Wrapper over 'callMethod' doing cluster information query.
queryClusterInfo :: L.Client -> IO (Result JSValue)
queryClusterInfo = L.callMethod queryClusterInfoMsg

-- | Wrapper over callMethod doing group query.
queryGroups :: L.Client -> IO (Result JSValue)
queryGroups = L.callMethod queryGroupsMsg

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
                  , status, pnode, snodes, tags, oram
                  , auto_balance, disk_template ] = do
  xname <- annotateResult "Parsing new instance" (fromJValWithStatus name)
  let convert a = genericConvert "Instance" xname a
  xdisk <- convert "disk_usage" disk
  xmem <- (case oram of -- FIXME: remove the "guessing"
             (_, JSRational _ _) -> convert "oper_ram" oram
             _ -> convert "be/memory" mem)
  xvcpus <- convert "be/vcpus" vcpus
  xpnode <- convert "pnode" pnode >>= lookupNode ktn xname
  xsnodes <- convert "snodes" snodes::Result [JSString]
  snode <- (if null xsnodes then return Node.noSecondary
            else lookupNode ktn xname (fromJSString $ head xsnodes))
  xrunning <- convert "status" status
  xtags <- convert "tags" tags
  xauto_balance <- convert "auto_balance" auto_balance
  xdt <- convert "disk_template" disk_template
  let inst = Instance.create xname xmem xdisk xvcpus
             xrunning xtags xauto_balance xpnode snode xdt
  return (xname, inst)

parseInstance _ v = fail ("Invalid instance query result: " ++ show v)

-- | Parse a node list in JSON format.
getNodes :: NameAssoc -> JSValue -> Result [(String, Node.Node)]
getNodes ktg arr = extractArray arr >>= mapM (parseNode ktg)

-- | Construct a node from a JSON object.
parseNode :: NameAssoc -> [(JSValue, JSValue)] -> Result (String, Node.Node)
parseNode ktg [ name, mtotal, mnode, mfree, dtotal, dfree
              , ctotal, offline, drained, vm_capable, g_uuid ]
    = do
  xname <- annotateResult "Parsing new node" (fromJValWithStatus name)
  let convert a = genericConvert "Node" xname a
  xoffline <- convert "offline" offline
  xdrained <- convert "drained" drained
  xvm_capable <- convert "vm_capable" vm_capable
  xgdx   <- convert "group.uuid" g_uuid >>= lookupGroup ktg xname
  node <- (if xoffline || xdrained || not xvm_capable
           then return $ Node.create xname 0 0 0 0 0 0 True xgdx
           else do
             xmtotal  <- convert "mtotal" mtotal
             xmnode   <- convert "mnode" mnode
             xmfree   <- convert "mfree" mfree
             xdtotal  <- convert "dtotal" dtotal
             xdfree   <- convert "dfree" dfree
             xctotal  <- convert "ctotal" ctotal
             return $ Node.create xname xmtotal xmnode xmfree
                    xdtotal xdfree xctotal False xgdx)
  return (xname, node)

parseNode _ v = fail ("Invalid node query result: " ++ show v)

-- | Parses the cluster tags.
getClusterTags :: JSValue -> Result [String]
getClusterTags v = do
  let errmsg = "Parsing cluster info"
  obj <- annotateResult errmsg $ asJSObject v
  tryFromObj errmsg (fromJSObject obj) "tags"

-- | Parses the cluster groups.
getGroups :: JSValue -> Result [(String, Group.Group)]
getGroups jsv = extractArray jsv >>= mapM parseGroup

-- | Parses a given group information.
parseGroup :: [(JSValue, JSValue)] -> Result (String, Group.Group)
parseGroup [uuid, name, apol] = do
  xname <- annotateResult "Parsing new group" (fromJValWithStatus name)
  let convert a = genericConvert "Group" xname a
  xuuid <- convert "uuid" uuid
  xapol <- convert "alloc_policy" apol
  return (xuuid, Group.create xname xuuid xapol)

parseGroup v = fail ("Invalid group query result: " ++ show v)

-- * Main loader functionality

-- | Builds the cluster data by querying a given socket name.
readData :: String -- ^ Unix socket to use as source
         -> IO (Result JSValue, Result JSValue, Result JSValue, Result JSValue)
readData master =
  E.bracket
       (L.getClient master)
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
  ctags <- cinfo >>= getClusterTags
  return (ClusterData group_idx node_idx inst_idx ctags)

-- | Top level function for data loading.
loadData :: String -- ^ Unix socket to use as source
         -> IO (Result ClusterData)
loadData = fmap parseData . readData

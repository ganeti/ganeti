{-| Implementation of the LUXI loader.

-}

{-

Copyright (C) 2009, 2010 Google Inc.

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

import qualified Ganeti.Luxi as L
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Utils (fromJVal, annotateResult, tryFromObj, asJSObject)

-- * Utility functions

-- | Ensure a given JSValue is actually a JSArray.
toArray :: (Monad m) => JSValue -> m [JSValue]
toArray v =
    case v of
      JSArray arr -> return arr
      o -> fail ("Invalid input, expected array but got " ++ show o)

-- * Data querying functionality

-- | The input data for node query.
queryNodesMsg :: L.LuxiOp
queryNodesMsg =
  L.QueryNodes [] ["name", "mtotal", "mnode", "mfree", "dtotal", "dfree",
                   "ctotal", "offline", "drained", "vm_capable",
                   "group.uuid"] False

-- | The input data for instance query.
queryInstancesMsg :: L.LuxiOp
queryInstancesMsg =
  L.QueryInstances [] ["name", "disk_usage", "be/memory", "be/vcpus",
                       "status", "pnode", "snodes", "tags", "oper_ram"] False

-- | The input data for cluster query.
queryClusterInfoMsg :: L.LuxiOp
queryClusterInfoMsg = L.QueryClusterInfo

-- | The input data for node group query.
queryGroupsMsg :: L.LuxiOp
queryGroupsMsg =
  L.QueryGroups [] ["uuid", "name"] False

-- | Wraper over callMethod doing node query.
queryNodes :: L.Client -> IO (Result JSValue)
queryNodes = L.callMethod queryNodesMsg

-- | Wraper over callMethod doing instance query.
queryInstances :: L.Client -> IO (Result JSValue)
queryInstances = L.callMethod queryInstancesMsg

queryClusterInfo :: L.Client -> IO (Result JSValue)
queryClusterInfo = L.callMethod queryClusterInfoMsg

-- | Wrapper over callMethod doing group query.
queryGroups :: L.Client -> IO (Result JSValue)
queryGroups = L.callMethod queryGroupsMsg

-- | Parse a instance list in JSON format.
getInstances :: NameAssoc
             -> JSValue
             -> Result [(String, Instance.Instance)]
getInstances ktn arr = toArray arr >>= mapM (parseInstance ktn)

-- | Construct an instance from a JSON object.
parseInstance :: NameAssoc
              -> JSValue
              -> Result (String, Instance.Instance)
parseInstance ktn (JSArray [ name, disk, mem, vcpus
                           , status, pnode, snodes, tags, oram ]) = do
  xname <- annotateResult "Parsing new instance" (fromJVal name)
  let convert v = annotateResult ("Instance '" ++ xname ++ "'") (fromJVal v)
  xdisk <- convert disk
  xmem <- (case oram of
             JSRational _ _ -> convert oram
             _ -> convert mem)
  xvcpus <- convert vcpus
  xpnode <- convert pnode >>= lookupNode ktn xname
  xsnodes <- convert snodes::Result [JSString]
  snode <- (if null xsnodes then return Node.noSecondary
            else lookupNode ktn xname (fromJSString $ head xsnodes))
  xrunning <- convert status
  xtags <- convert tags
  let inst = Instance.create xname xmem xdisk xvcpus
             xrunning xtags xpnode snode
  return (xname, inst)

parseInstance _ v = fail ("Invalid instance query result: " ++ show v)

-- | Parse a node list in JSON format.
getNodes :: JSValue -> Result [(String, Node.Node)]
getNodes arr = toArray arr >>= mapM parseNode

-- | Construct a node from a JSON object.
parseNode :: JSValue -> Result (String, Node.Node)
parseNode (JSArray [ name, mtotal, mnode, mfree, dtotal, dfree
                   , ctotal, offline, drained, vm_capable, g_uuid ])
    = do
  xname <- annotateResult "Parsing new node" (fromJVal name)
  let convert v = annotateResult ("Node '" ++ xname ++ "'") (fromJVal v)
  xoffline <- convert offline
  xdrained <- convert drained
  xvm_capable <- convert vm_capable
  xguuid   <- convert g_uuid
  node <- (if xoffline || xdrained || not xvm_capable
           then return $ Node.create xname 0 0 0 0 0 0 True xguuid
           else do
             xmtotal  <- convert mtotal
             xmnode   <- convert mnode
             xmfree   <- convert mfree
             xdtotal  <- convert dtotal
             xdfree   <- convert dfree
             xctotal  <- convert ctotal
             return $ Node.create xname xmtotal xmnode xmfree
                    xdtotal xdfree xctotal False xguuid)
  return (xname, node)

parseNode v = fail ("Invalid node query result: " ++ show v)

getClusterTags :: JSValue -> Result [String]
getClusterTags v = do
  let errmsg = "Parsing cluster info"
  obj <- annotateResult errmsg $ asJSObject v
  tryFromObj errmsg (fromJSObject obj) "tags"

getGroups :: JSValue -> Result [(String, Group.Group)]
getGroups arr = toArray arr >>= mapM parseGroup

parseGroup :: JSValue -> Result (String, Group.Group)
parseGroup (JSArray [ uuid, name ]) = do
  xname <- annotateResult "Parsing new group" (fromJVal name)
  let convert v = annotateResult ("Node '" ++ xname ++ "'") (fromJVal v)
  xuuid <- convert uuid
  return $ (xuuid, Group.create xname xuuid AllocPreferred)

parseGroup v = fail ("Invalid group query result: " ++ show v)

-- * Main loader functionality

-- | Builds the cluster data from an URL.
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

parseData :: (Result JSValue, Result JSValue, Result JSValue, Result JSValue)
          -> Result (Group.List, Node.List, Instance.List, [String])
parseData (groups, nodes, instances, cinfo) = do
  group_data <- groups >>= getGroups
  let (_, group_idx) = assignIndices group_data
  node_data <- nodes >>= getNodes
  let (node_names, node_idx) = assignIndices node_data
  inst_data <- instances >>= getInstances node_names
  let (_, inst_idx) = assignIndices inst_data
  ctags <- cinfo >>= getClusterTags
  return (group_idx, node_idx, inst_idx, ctags)

-- | Top level function for data loading
loadData :: String -- ^ Unix socket to use as source
            -> IO (Result (Group.List, Node.List, Instance.List, [String]))
loadData master = readData master >>= return . parseData

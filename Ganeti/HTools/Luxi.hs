{-| Implementation of the LUXI loader.

-}

{-

Copyright (C) 2009 Google Inc.

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
    ) where

import Data.List
import qualified Control.Exception as E
import Control.Monad
import Text.JSON (JSValue, readJSON, JSON)
import qualified Text.JSON as J
import Text.JSON.Types

import qualified Ganeti.Luxi as L
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

-- * Utility functions

-- | Small wrapper over readJSON.
fromJVal :: (Monad m, JSON a) => JSValue -> m a
fromJVal v =
    case readJSON v of
      J.Error s -> fail ("Cannot convert value " ++ show v ++ ", error: " ++ s)
      J.Ok x -> return x

-- | Ensure a given JSValue is actually a JSArray.
toArray :: (Monad m) => JSValue -> m [JSValue]
toArray v =
    case v of
      JSArray arr -> return arr
      o -> fail ("Invalid input, expected array but got " ++ show o)

-- * Data querying functionality

-- | The input data for node query.
queryNodesMsg :: JSValue
queryNodesMsg =
    let nnames = JSArray []
        fnames = ["name",
                  "mtotal", "mnode", "mfree",
                  "dtotal", "dfree",
                  "ctotal",
                  "offline", "drained"]
        fields = JSArray $ map (JSString . toJSString) fnames
        use_locking = JSBool False
    in JSArray [nnames, fields, use_locking]

-- | The input data for instance query.
queryInstancesMsg :: JSValue
queryInstancesMsg =
    let nnames = JSArray []
        fnames = ["name",
                  "disk_usage", "be/memory", "be/vcpus",
                  "status", "pnode", "snodes"]
        fields = JSArray $ map (JSString . toJSString) fnames
        use_locking = JSBool False
    in JSArray [nnames, fields, use_locking]

-- | Wraper over callMethod doing node query.
queryNodes :: L.Client -> IO (Result JSValue)
queryNodes = L.callMethod L.QueryNodes queryNodesMsg

-- | Wraper over callMethod doing instance query.
queryInstances :: L.Client -> IO (Result JSValue)
queryInstances = L.callMethod L.QueryInstances queryInstancesMsg

-- | Parse a instance list in JSON format.
getInstances :: NameAssoc
             -> JSValue
             -> Result [(String, Instance.Instance)]
getInstances ktn arr = toArray arr >>= mapM (parseInstance ktn)

-- | Construct an instance from a JSON object.
parseInstance :: [(String, Ndx)]
              -> JSValue
              -> Result (String, Instance.Instance)
parseInstance ktn (JSArray (name:disk:mem:vcpus:status:pnode:snodes:[])) = do
  xname <- fromJVal name
  xdisk <- fromJVal disk
  xmem <- fromJVal mem
  xvcpus <- fromJVal vcpus
  xpnode <- fromJVal pnode >>= lookupNode ktn xname
  xsnodes <- fromJVal snodes::Result [JSString]
  snode <- (if null xsnodes then return Node.noSecondary
            else lookupNode ktn xname (fromJSString $ head xsnodes))
  xrunning <- fromJVal status
  let inst = Instance.create xname xmem xdisk xvcpus xrunning xpnode snode
  return (xname, inst)

parseInstance _ v = fail ("Invalid instance query result: " ++ show v)

-- | Parse a node list in JSON format.
getNodes :: JSValue -> Result [(String, Node.Node)]
getNodes arr = toArray arr >>= mapM parseNode

-- | Construct a node from a JSON object.
parseNode :: JSValue -> Result (String, Node.Node)
parseNode (JSArray
           (name:mtotal:mnode:mfree:dtotal:dfree:ctotal:offline:drained:[]))
    = do
  xname <- fromJVal name
  xoffline <- fromJVal offline
  node <- (if xoffline
           then return $ Node.create xname 0 0 0 0 0 0 True
           else do
             xdrained <- fromJVal drained
             xmtotal  <- fromJVal mtotal
             xmnode   <- fromJVal mnode
             xmfree   <- fromJVal mfree
             xdtotal  <- fromJVal dtotal
             xdfree   <- fromJVal dfree
             xctotal  <- fromJVal ctotal
             return $ Node.create xname xmtotal xmnode xmfree
                    xdtotal xdfree xctotal (xoffline || xdrained))
  return (xname, node)

parseNode v = fail ("Invalid node query result: " ++ show v)

-- * Main loader functionality

-- | Builds the cluster data from an URL.
loadData :: String -- ^ Unix socket to use as source
         -> IO (Result (Node.AssocList, Instance.AssocList))
loadData master =
  E.bracket
       (L.getClient master)
       L.closeClient
       (\s -> do
          nodes <- queryNodes s
          instances <- queryInstances s
          return $ do -- Result monad
            node_data <- nodes >>= getNodes
            let (node_names, node_idx) = assignIndices node_data
            inst_data <- instances >>= getInstances node_names
            let (_, inst_idx) = assignIndices inst_data
            return (node_idx, inst_idx)
       )

{-| Implementation of the iallocator interface.

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

module Ganeti.HTools.IAlloc
    ( parseData
    , formatResponse
    ) where

import Data.Either ()
import Control.Monad
import Text.JSON (JSObject, JSValue(JSBool, JSString, JSArray),
                  makeObj, encodeStrict, decodeStrict,
                  fromJSObject, toJSString)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Loader
import Ganeti.HTools.Utils
import Ganeti.HTools.Types

-- | Parse the basic specifications of an instance.
--
-- Instances in the cluster instance list and the instance in an
-- 'Allocate' request share some common properties, which are read by
-- this function.
parseBaseInstance :: String
                  -> [(String, JSValue)]
                  -> Result (String, Instance.Instance)
parseBaseInstance n a = do
  disk <- fromObj "disk_space_total" a
  mem <- fromObj "memory" a
  vcpus <- fromObj "vcpus" a
  tags <- fromObj "tags" a
  let running = "running"
  return (n, Instance.create n mem disk vcpus running tags 0 0)

-- | Parses an instance as found in the cluster instance listg.
parseInstance :: NameAssoc        -- ^ The node name-to-index association list
              -> String           -- ^ The name of the instance
              -> [(String, JSValue)] -- ^ The JSON object
              -> Result (String, Instance.Instance)
parseInstance ktn n a = do
  base <- parseBaseInstance n a
  nodes <- fromObj "nodes" a
  pnode <- if null nodes
           then Bad $ "empty node list for instance " ++ n
           else readEitherString $ head nodes
  pidx <- lookupNode ktn n pnode
  let snodes = tail nodes
  sidx <- (if null snodes then return Node.noSecondary
           else readEitherString (head snodes) >>= lookupNode ktn n)
  return (n, Instance.setBoth (snd base) pidx sidx)

-- | Parses a node as found in the cluster node list.
parseNode :: NameAssoc           -- ^ The group association
          -> String              -- ^ The node's name
          -> [(String, JSValue)] -- ^ The JSON object
          -> Result (String, Node.Node)
parseNode ktg n a = do
  offline <- fromObj "offline" a
  drained <- fromObj "drained" a
  guuid   <- fromObj "group" a
  gidx <- lookupGroup ktg n guuid
  node <- (if offline || drained
           then return $ Node.create n 0 0 0 0 0 0 True gidx
           else do
             mtotal <- fromObj "total_memory" a
             mnode  <- fromObj "reserved_memory" a
             mfree  <- fromObj "free_memory"  a
             dtotal <- fromObj "total_disk"   a
             dfree  <- fromObj "free_disk"    a
             ctotal <- fromObj "total_cpus"   a
             return $ Node.create n mtotal mnode mfree
                    dtotal dfree ctotal False gidx)
  return (n, node)

-- | Parses a group as found in the cluster group list.
parseGroup :: String              -- ^ The group UUID
           -> [(String, JSValue)] -- ^ The JSON object
           -> Result (String, Group.Group)
parseGroup u a = do
  name <- fromObj "name" a
  return (u, Group.create name u AllocPreferred)

-- | Top-level parser.
parseData :: String         -- ^ The JSON message as received from Ganeti
          -> Result Request -- ^ A (possible valid) request
parseData body = do
  decoded <- fromJResult "Parsing input IAllocator message" (decodeStrict body)
  let obj = fromJSObject decoded
  -- request parser
  request <- liftM fromJSObject (fromObj "request" obj)
  -- existing group parsing
  glist <- liftM fromJSObject (fromObj "nodegroups" obj)
  gobj <- mapM (\(x, y) -> asJSObject y >>= parseGroup x . fromJSObject) glist
  let (ktg, gl) = assignIndices gobj
  -- existing node parsing
  nlist <- liftM fromJSObject (fromObj "nodes" obj)
  nobj <- mapM (\(x,y) ->
                    asJSObject y >>= parseNode ktg x . fromJSObject) nlist
  let (ktn, nl) = assignIndices nobj
  -- existing instance parsing
  ilist <- fromObj "instances" obj
  let idata = fromJSObject ilist
  iobj <- mapM (\(x,y) ->
                    asJSObject y >>= parseInstance ktn x . fromJSObject) idata
  let (kti, il) = assignIndices iobj
  -- cluster tags
  ctags <- fromObj "cluster_tags" obj
  (map_g, map_n, map_i, ptags) <- mergeData [] [] [] (gl, nl, il, ctags)
  optype <- fromObj "type" request
  rqtype <-
      case optype of
        "allocate" ->
            do
              rname <- fromObj "name" request
              req_nodes <- fromObj "required_nodes" request
              inew <- parseBaseInstance rname request
              let io = snd inew
              return $ Allocate io req_nodes
        "relocate" ->
            do
              rname <- fromObj "name" request
              ridx <- lookupInstance kti rname
              req_nodes <- fromObj "required_nodes" request
              ex_nodes <- fromObj "relocate_from" request
              ex_idex <- mapM (Container.findByName map_n) ex_nodes
              return $ Relocate ridx req_nodes (map Node.idx ex_idex)
        "multi-evacuate" ->
            do
              ex_names <- fromObj "evac_nodes" request
              ex_nodes <- mapM (Container.findByName map_n) ex_names
              let ex_ndx = map Node.idx ex_nodes
              return $ Evacuate ex_ndx
        other -> fail ("Invalid request type '" ++ other ++ "'")
  return $ Request rqtype (ClusterData map_g map_n map_i ptags)

-- | Format the result
formatRVal :: RqType -> [Node.AllocElement] -> JSValue
formatRVal _ [] = JSArray []

formatRVal (Evacuate _) elems =
    let sols = map (\(_, inst, nl, _) -> Instance.name inst : map Node.name nl)
               elems
        jsols = map (JSArray . map (JSString . toJSString)) sols
    in JSArray jsols

formatRVal _ elems =
    let (_, _, nodes, _) = head elems
        nodes' = map Node.name nodes
    in JSArray $ map (JSString . toJSString) nodes'

-- | Formats the response into a valid IAllocator response message.
formatResponse :: Bool     -- ^ Whether the request was successful
               -> String   -- ^ Information text
               -> RqType   -- ^ Request type
               -> [Node.AllocElement] -- ^ The resulting allocations
               -> String   -- ^ The JSON-formatted message
formatResponse success info rq elems =
    let
        e_success = ("success", JSBool success)
        e_info = ("info", JSString . toJSString $ info)
        e_nodes = ("nodes", formatRVal rq elems)
    in encodeStrict $ makeObj [e_success, e_info, e_nodes]

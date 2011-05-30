{-| Implementation of the iallocator interface.

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

module Ganeti.HTools.IAlloc
    ( parseData
    , formatResponse
    ) where

import Data.Either ()
import Data.Maybe (fromMaybe)
import Control.Monad
import Text.JSON (JSObject, JSValue(JSBool, JSString, JSArray),
                  makeObj, encodeStrict, decodeStrict,
                  fromJSObject, toJSString)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.Constants as C
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
  let extract x = tryFromObj ("invalid data for instance '" ++ n ++ "'") a x
  disk  <- extract "disk_space_total"
  mem   <- extract "memory"
  vcpus <- extract "vcpus"
  tags  <- extract "tags"
  let running = "running"
  return (n, Instance.create n mem disk vcpus running tags True 0 0)

-- | Parses an instance as found in the cluster instance listg.
parseInstance :: NameAssoc        -- ^ The node name-to-index association list
              -> String           -- ^ The name of the instance
              -> [(String, JSValue)] -- ^ The JSON object
              -> Result (String, Instance.Instance)
parseInstance ktn n a = do
  base <- parseBaseInstance n a
  nodes <- fromObj a "nodes"
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
  let desc = "invalid data for node '" ++ n ++ "'"
      extract x = tryFromObj desc a x
  offline <- extract "offline"
  drained <- extract "drained"
  guuid   <- extract "group"
  vm_capable  <- annotateResult desc $ maybeFromObj a "vm_capable"
  let vm_capable' = fromMaybe True vm_capable
  gidx <- lookupGroup ktg n guuid
  node <- (if offline || drained || not vm_capable'
           then return $ Node.create n 0 0 0 0 0 0 True gidx
           else do
             mtotal <- extract "total_memory"
             mnode  <- extract "reserved_memory"
             mfree  <- extract "free_memory"
             dtotal <- extract "total_disk"
             dfree  <- extract "free_disk"
             ctotal <- extract "total_cpus"
             return $ Node.create n mtotal mnode mfree
                    dtotal dfree ctotal False gidx)
  return (n, node)

-- | Parses a group as found in the cluster group list.
parseGroup :: String              -- ^ The group UUID
           -> [(String, JSValue)] -- ^ The JSON object
           -> Result (String, Group.Group)
parseGroup u a = do
  let extract x = tryFromObj ("invalid data for group '" ++ u ++ "'") a x
  name <- extract "name"
  apol <- extract "alloc_policy"
  return (u, Group.create name u apol)

parseTargetGroups :: [(String, JSValue)] -- ^ The JSON object (request dict)
                  -> Group.List          -- ^ The existing groups
                  -> Result [Gdx]
parseTargetGroups req map_g = do
  group_uuids <- fromObjWithDefault req "target_groups" []
  mapM (liftM Group.idx . Container.findByName map_g) group_uuids

-- | Top-level parser.
parseData :: String         -- ^ The JSON message as received from Ganeti
          -> Result Request -- ^ A (possible valid) request
parseData body = do
  decoded <- fromJResult "Parsing input IAllocator message" (decodeStrict body)
  let obj = fromJSObject decoded
      extrObj x = tryFromObj "invalid iallocator message" obj x
  -- request parser
  request <- liftM fromJSObject (extrObj "request")
  let extrReq x = tryFromObj "invalid request dict" request x
  -- existing group parsing
  glist <- liftM fromJSObject (extrObj "nodegroups")
  gobj <- mapM (\(x, y) -> asJSObject y >>= parseGroup x . fromJSObject) glist
  let (ktg, gl) = assignIndices gobj
  -- existing node parsing
  nlist <- liftM fromJSObject (extrObj "nodes")
  nobj <- mapM (\(x,y) ->
                    asJSObject y >>= parseNode ktg x . fromJSObject) nlist
  let (ktn, nl) = assignIndices nobj
  -- existing instance parsing
  ilist <- extrObj "instances"
  let idata = fromJSObject ilist
  iobj <- mapM (\(x,y) ->
                    asJSObject y >>= parseInstance ktn x . fromJSObject) idata
  let (kti, il) = assignIndices iobj
  -- cluster tags
  ctags <- extrObj "cluster_tags"
  cdata <- mergeData [] [] [] (ClusterData gl nl il ctags)
  let map_n = cdNodes cdata
      map_i = cdInstances cdata
      map_g = cdGroups cdata
  optype <- extrReq "type"
  rqtype <-
      case () of
        _ | optype == C.iallocatorModeAlloc ->
              do
                rname     <- extrReq "name"
                req_nodes <- extrReq "required_nodes"
                inew      <- parseBaseInstance rname request
                let io = snd inew
                return $ Allocate io req_nodes
          | optype == C.iallocatorModeReloc ->
              do
                rname     <- extrReq "name"
                ridx      <- lookupInstance kti rname
                req_nodes <- extrReq "required_nodes"
                ex_nodes  <- extrReq "relocate_from"
                ex_idex   <- mapM (Container.findByName map_n) ex_nodes
                return $ Relocate ridx req_nodes (map Node.idx ex_idex)
          | optype == C.iallocatorModeMevac ->
              do
                ex_names <- extrReq "evac_nodes"
                ex_nodes <- mapM (Container.findByName map_n) ex_names
                let ex_ndx = map Node.idx ex_nodes
                return $ Evacuate ex_ndx
          | optype == C.iallocatorModeMreloc ->
              do
                rl_names <- extrReq "instances"
                rl_insts <- mapM (Container.findByName map_i) rl_names
                let rl_idx = map Instance.idx rl_insts
                rl_mode <- do
                   case extrReq "reloc_mode" of
                     Ok s | s == C.iallocatorMrelocKeep -> return KeepGroup
                          | s == C.iallocatorMrelocChange ->
                              do
                                tg_groups <- parseTargetGroups request map_g
                                return $ ChangeGroup tg_groups
                          | s == C.iallocatorMrelocAny -> return AnyGroup
                          | otherwise -> Bad $ "Invalid relocate mode " ++ s
                     Bad x -> Bad x
                return $ MultiReloc rl_idx rl_mode

          | otherwise -> fail ("Invalid request type '" ++ optype ++ "'")
  return $ Request rqtype cdata

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
        e_result = ("result", formatRVal rq elems)
    in encodeStrict $ makeObj [e_success, e_info, e_result]

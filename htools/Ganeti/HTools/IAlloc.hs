{-| Implementation of the iallocator interface.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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
  ( readRequest
  , runIAllocator
  , processRelocate
  , loadData
  ) where

import Data.Either ()
import Data.Maybe (fromMaybe, isJust, fromJust)
import Data.List
import Control.Monad
import Text.JSON (JSObject, JSValue(JSArray),
                  makeObj, encodeStrict, decodeStrict, fromJSObject, showJSON)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.Constants as C
import Ganeti.HTools.CLI
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import Ganeti.JSON
import Ganeti.Utils

{-# ANN module "HLint: ignore Eta reduce" #-}

-- | Type alias for the result of an IAllocator call.
type IAllocResult = (String, JSValue, Node.List, Instance.List)

-- | Parse the basic specifications of an instance.
--
-- Instances in the cluster instance list and the instance in an
-- 'Allocate' request share some common properties, which are read by
-- this function.
parseBaseInstance :: String
                  -> JSRecord
                  -> Result (String, Instance.Instance)
parseBaseInstance n a = do
  let extract x = tryFromObj ("invalid data for instance '" ++ n ++ "'") a x
  disk  <- extract "disk_space_total"
  mem   <- extract "memory"
  vcpus <- extract "vcpus"
  tags  <- extract "tags"
  dt    <- extract "disk_template"
  su    <- extract "spindle_use"
  return (n, Instance.create n mem disk vcpus Running tags True 0 0 dt su)

-- | Parses an instance as found in the cluster instance list.
parseInstance :: NameAssoc -- ^ The node name-to-index association list
              -> String    -- ^ The name of the instance
              -> JSRecord  -- ^ The JSON object
              -> Result (String, Instance.Instance)
parseInstance ktn n a = do
  base <- parseBaseInstance n a
  nodes <- fromObj a "nodes"
  pnode <- if null nodes
           then Bad $ "empty node list for instance " ++ n
           else readEitherString $ head nodes
  pidx <- lookupNode ktn n pnode
  let snodes = tail nodes
  sidx <- if null snodes
            then return Node.noSecondary
            else readEitherString (head snodes) >>= lookupNode ktn n
  return (n, Instance.setBoth (snd base) pidx sidx)

-- | Parses a node as found in the cluster node list.
parseNode :: NameAssoc   -- ^ The group association
          -> String      -- ^ The node's name
          -> JSRecord    -- ^ The JSON object
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
  node <- if offline || drained || not vm_capable'
            then return $ Node.create n 0 0 0 0 0 0 True 0 gidx
            else do
              mtotal <- extract "total_memory"
              mnode  <- extract "reserved_memory"
              mfree  <- extract "free_memory"
              dtotal <- extract "total_disk"
              dfree  <- extract "free_disk"
              ctotal <- extract "total_cpus"
              ndparams <- extract "ndparams" >>= asJSObject
              spindles <- tryFromObj desc (fromJSObject ndparams)
                          "spindle_count"
              return $ Node.create n mtotal mnode mfree
                     dtotal dfree ctotal False spindles gidx
  return (n, node)

-- | Parses a group as found in the cluster group list.
parseGroup :: String     -- ^ The group UUID
           -> JSRecord   -- ^ The JSON object
           -> Result (String, Group.Group)
parseGroup u a = do
  let extract x = tryFromObj ("invalid data for group '" ++ u ++ "'") a x
  name <- extract "name"
  apol <- extract "alloc_policy"
  ipol <- extract "ipolicy"
  tags <- extract "tags"
  return (u, Group.create name u apol ipol tags)

-- | Top-level parser.
--
-- The result is a tuple of eventual warning messages and the parsed
-- request; if parsing the input data fails, we'll return a 'Bad'
-- value.
parseData :: String -- ^ The JSON message as received from Ganeti
          -> Result ([String], Request) -- ^ Result tuple
parseData body = do
  decoded <- fromJResult "Parsing input IAllocator message" (decodeStrict body)
  let obj = fromJSObject decoded
      extrObj x = tryFromObj "invalid iallocator message" obj x
  -- request parser
  request <- liftM fromJSObject (extrObj "request")
  let extrFromReq r x = tryFromObj "invalid request dict" r x
  let extrReq x = extrFromReq request x
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
  cdata1 <- mergeData [] [] [] [] (ClusterData gl nl il ctags defIPolicy)
  let (msgs, fix_nl) = checkData (cdNodes cdata1) (cdInstances cdata1)
      cdata = cdata1 { cdNodes = fix_nl }
      map_n = cdNodes cdata
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
        | optype == C.iallocatorModeChgGroup ->
            do
              rl_names <- extrReq "instances"
              rl_insts <- mapM (liftM Instance.idx .
                                Container.findByName map_i) rl_names
              gr_uuids <- extrReq "target_groups"
              gr_idxes <- mapM (liftM Group.idx .
                                Container.findByName map_g) gr_uuids
              return $ ChangeGroup rl_insts gr_idxes
        | optype == C.iallocatorModeNodeEvac ->
            do
              rl_names <- extrReq "instances"
              rl_insts <- mapM (Container.findByName map_i) rl_names
              let rl_idx = map Instance.idx rl_insts
              rl_mode <- extrReq "evac_mode"
              return $ NodeEvacuate rl_idx rl_mode
        | optype == C.iallocatorModeMultiAlloc ->
            do
              arry <- extrReq "instances" :: Result [JSObject JSValue]
              let inst_reqs = map fromJSObject arry
              prqs <- mapM (\r ->
                               do
                                 rname     <- extrFromReq r "name"
                                 req_nodes <- extrFromReq r "required_nodes"
                                 inew      <- parseBaseInstance rname r
                                 let io = snd inew
                                 return (io, req_nodes)) inst_reqs
              return $ MultiAllocate prqs
        | otherwise -> fail ("Invalid request type '" ++ optype ++ "'")
  return (msgs, Request rqtype cdata)

-- | Formats the result into a valid IAllocator response message.
formatResponse :: Bool     -- ^ Whether the request was successful
               -> String   -- ^ Information text
               -> JSValue  -- ^ The JSON encoded result
               -> String   -- ^ The full JSON-formatted message
formatResponse success info result =
  let e_success = ("success", showJSON success)
      e_info = ("info", showJSON info)
      e_result = ("result", result)
  in encodeStrict $ makeObj [e_success, e_info, e_result]

-- | Flatten the log of a solution into a string.
describeSolution :: Cluster.AllocSolution -> String
describeSolution = intercalate ", " . Cluster.asLog

-- | Convert allocation/relocation results into the result format.
formatAllocate :: Instance.List -> Cluster.AllocSolution -> Result IAllocResult
formatAllocate il as = do
  let info = describeSolution as
  case Cluster.asSolution as of
    Nothing -> fail info
    Just (nl, inst, nodes, _) ->
      do
        let il' = Container.add (Instance.idx inst) inst il
        return (info, showJSON $ map Node.name nodes, nl, il')

-- | Convert multi allocation results into the result format.
formatMultiAlloc :: (Node.List, Instance.List, Cluster.AllocSolutionList)
                 -> Result IAllocResult
formatMultiAlloc (fin_nl, fin_il, ars) =
  let rars = reverse ars
      (allocated, failed) = partition (isJust . Cluster.asSolution . snd) rars
      aars = map (\(_, ar) ->
                     let (_, inst, nodes, _) = fromJust $ Cluster.asSolution ar
                         iname = Instance.name inst
                         nnames = map Node.name nodes
                     in (iname, nnames)) allocated
      fars = map (\(inst, ar) ->
                     let iname = Instance.name inst
                     in (iname, describeSolution ar)) failed
      info = show (length failed) ++ " instances failed to allocate and " ++
             show (length allocated) ++ " were allocated successfully"
  in return (info, showJSON (aars, fars), fin_nl, fin_il)

-- | Convert a node-evacuation/change group result.
formatNodeEvac :: Group.List
               -> Node.List
               -> Instance.List
               -> (Node.List, Instance.List, Cluster.EvacSolution)
               -> Result IAllocResult
formatNodeEvac gl nl il (fin_nl, fin_il, es) =
  let iname = Instance.name . flip Container.find il
      nname = Node.name . flip Container.find nl
      gname = Group.name . flip Container.find gl
      fes = map (\(idx, msg) -> (iname idx, msg)) $ Cluster.esFailed es
      mes = map (\(idx, gdx, ndxs) -> (iname idx, gname gdx, map nname ndxs))
            $ Cluster.esMoved es
      failed = length fes
      moved  = length mes
      info = show failed ++ " instances failed to move and " ++ show moved ++
             " were moved successfully"
  in Ok (info, showJSON (mes, fes, Cluster.esOpCodes es), fin_nl, fin_il)

-- | Runs relocate for a single instance.
--
-- This is wrapper over the 'Cluster.tryNodeEvac' function that is run
-- with a single instance (ours), and further it checks that the
-- result it got (in the nodes field) is actually consistent, as
-- tryNodeEvac is designed to output primarily an opcode list, not a
-- node list.
processRelocate :: Group.List      -- ^ The group list
                -> Node.List       -- ^ The node list
                -> Instance.List   -- ^ The instance list
                -> Idx             -- ^ The index of the instance to move
                -> Int             -- ^ The number of nodes required
                -> [Ndx]           -- ^ Nodes which should not be used
                -> Result (Node.List, Instance.List, [Ndx]) -- ^ Solution list
processRelocate gl nl il idx 1 exndx = do
  let orig = Container.find idx il
      sorig = Instance.sNode orig
      porig = Instance.pNode orig
      mir_type = Instance.mirrorType orig
  (exp_node, node_type, reloc_type) <-
    case mir_type of
      MirrorNone -> fail "Can't relocate non-mirrored instances"
      MirrorInternal -> return (sorig, "secondary", ChangeSecondary)
      MirrorExternal -> return (porig, "primary", ChangePrimary)
  when (exndx /= [exp_node]) .
       -- FIXME: we can't use the excluded nodes here; the logic is
       -- already _but only partially_ implemented in tryNodeEvac...
       fail $ "Unsupported request: excluded nodes not equal to\
              \ instance's " ++  node_type ++ "(" ++ show exp_node
              ++ " versus " ++ show exndx ++ ")"
  (nl', il', esol) <- Cluster.tryNodeEvac gl nl il reloc_type [idx]
  nodes <- case lookup idx (Cluster.esFailed esol) of
             Just msg -> fail msg
             Nothing ->
                 case lookup idx (map (\(a, _, b) -> (a, b))
                                  (Cluster.esMoved esol)) of
                   Nothing ->
                       fail "Internal error: lost instance idx during move"
                   Just n -> return n
  let inst = Container.find idx il'
      pnode = Instance.pNode inst
      snode = Instance.sNode inst
  nodes' <-
    case mir_type of
      MirrorNone -> fail "Internal error: mirror type none after relocation?!"
      MirrorInternal ->
        do
          when (snode == sorig) $
               fail "Internal error: instance didn't change secondary node?!"
          when (snode == pnode) $
               fail "Internal error: selected primary as new secondary?!"
          if nodes == [pnode, snode]
            then return [snode] -- only the new secondary is needed
            else fail $ "Internal error: inconsistent node list (" ++
                 show nodes ++ ") versus instance nodes (" ++ show pnode ++
                 "," ++ show snode ++ ")"
      MirrorExternal ->
        do
          when (pnode == porig) $
               fail "Internal error: instance didn't change primary node?!"
          if nodes == [pnode]
            then return nodes
            else fail $ "Internal error: inconsistent node list (" ++
                 show nodes ++ ") versus instance node (" ++ show pnode ++ ")"
  return (nl', il', nodes')

processRelocate _ _ _ _ reqn _ =
  fail $ "Exchange " ++ show reqn ++ " nodes mode is not implemented"

formatRelocate :: (Node.List, Instance.List, [Ndx])
               -> Result IAllocResult
formatRelocate (nl, il, ndxs) =
  let nodes = map (`Container.find` nl) ndxs
      names = map Node.name nodes
  in Ok ("success", showJSON names, nl, il)

-- | Process a request and return new node lists.
processRequest :: Request -> Result IAllocResult
processRequest request =
  let Request rqtype (ClusterData gl nl il _ _) = request
  in case rqtype of
       Allocate xi reqn ->
         Cluster.tryMGAlloc gl nl il xi reqn >>= formatAllocate il
       Relocate idx reqn exnodes ->
         processRelocate gl nl il idx reqn exnodes >>= formatRelocate
       ChangeGroup gdxs idxs ->
         Cluster.tryChangeGroup gl nl il idxs gdxs >>=
                formatNodeEvac gl nl il
       NodeEvacuate xi mode ->
         Cluster.tryNodeEvac gl nl il mode xi >>=
                formatNodeEvac gl nl il
       MultiAllocate xies ->
         Cluster.allocList gl nl il xies [] >>= formatMultiAlloc

-- | Reads the request from the data file(s).
readRequest :: FilePath -> IO Request
readRequest fp = do
  input_data <- case fp of
                  "-" -> getContents
                  _   -> readFile fp
  case parseData input_data of
    Bad err -> exitErr err
    Ok (fix_msgs, rq) -> maybeShowWarnings fix_msgs >> return rq

-- | Main iallocator pipeline.
runIAllocator :: Request -> (Maybe (Node.List, Instance.List), String)
runIAllocator request =
  let (ok, info, result, cdata) =
        case processRequest request of
          Ok (msg, r, nl, il) -> (True, "Request successful: " ++ msg, r,
                                  Just (nl, il))
          Bad msg -> (False, "Request failed: " ++ msg, JSArray [], Nothing)
      rstring = formatResponse ok info result
  in (cdata, rstring)

-- | Load the data from an iallocation request file
loadData :: FilePath -- ^ The path to the file
         -> IO (Result ClusterData)
loadData fp = do
  Request _ cdata <- readRequest fp
  return $ Ok cdata

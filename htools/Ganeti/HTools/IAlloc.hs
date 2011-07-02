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
    ( readRequest
    , runIAllocator
    ) where

import Data.Either ()
import Data.Maybe (fromMaybe, isJust)
import Data.List
import Control.Monad
import Text.JSON (JSObject, JSValue(JSArray),
                  makeObj, encodeStrict, decodeStrict, fromJSObject, showJSON)
import System (exitWith, ExitCode(..))
import System.IO

import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.Constants as C
import Ganeti.HTools.CLI
import Ganeti.HTools.Loader
import Ganeti.HTools.ExtLoader (loadExternalData)
import Ganeti.HTools.Utils
import Ganeti.HTools.Types

-- | Type alias for the result of an IAllocator call.
type IAllocResult = (String, JSValue)

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
  let running = "running"
  return (n, Instance.create n mem disk vcpus running tags True 0 0 dt)

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
  sidx <- (if null snodes then return Node.noSecondary
           else readEitherString (head snodes) >>= lookupNode ktn n)
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
parseGroup :: String     -- ^ The group UUID
           -> JSRecord   -- ^ The JSON object
           -> Result (String, Group.Group)
parseGroup u a = do
  let extract x = tryFromObj ("invalid data for group '" ++ u ++ "'") a x
  name <- extract "name"
  apol <- extract "alloc_policy"
  return (u, Group.create name u apol)

parseTargetGroups :: JSRecord      -- ^ The JSON object (request dict)
                  -> Group.List    -- ^ The existing groups
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
  cdata <- mergeData [] [] [] [] (ClusterData gl nl il ctags)
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
                rl_mode <-
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
          | optype == C.iallocatorModeNodeEvac ->
              do
                rl_names <- extrReq "instances"
                rl_insts <- mapM (Container.findByName map_i) rl_names
                let rl_idx = map Instance.idx rl_insts
                rl_mode <-
                   case extrReq "evac_mode" of
                     Ok s | s == C.iallocatorNevacAll -> return ChangeAll
                          | s == C.iallocatorNevacPri -> return ChangePrimary
                          | s == C.iallocatorNevacSec -> return ChangeSecondary
                          | otherwise -> Bad $ "Invalid evacuate mode " ++ s
                     Bad x -> Bad x
                return $ NodeEvacuate rl_idx rl_mode

          | otherwise -> fail ("Invalid request type '" ++ optype ++ "'")
  return $ Request rqtype cdata

-- | Formats the result into a valid IAllocator response message.
formatResponse :: Bool     -- ^ Whether the request was successful
               -> String   -- ^ Information text
               -> JSValue  -- ^ The JSON encoded result
               -> String   -- ^ The full JSON-formatted message
formatResponse success info result =
    let
        e_success = ("success", showJSON success)
        e_info = ("info", showJSON info)
        e_result = ("result", result)
    in encodeStrict $ makeObj [e_success, e_info, e_result]

-- | Flatten the log of a solution into a string.
describeSolution :: Cluster.AllocSolution -> String
describeSolution = intercalate ", " . Cluster.asLog

-- | Convert evacuation results into the result format.
formatEvacuate :: Cluster.AllocSolution -> Result IAllocResult
formatEvacuate as = do
  let info = describeSolution as
      elems = Cluster.asSolutions as
  when (null elems) $ fail info
  let sols = map (\(_, inst, nl, _) -> Instance.name inst : map Node.name nl)
             elems
  return (info, showJSON sols)

-- | Convert allocation/relocation results into the result format.
formatAllocate :: Cluster.AllocSolution -> Result IAllocResult
formatAllocate as = do
  let info = describeSolution as
  case Cluster.asSolutions as of
    [] -> fail info
    (_, _, nodes, _):[] -> return (info, showJSON $ map (Node.name) nodes)
    _ -> fail "Internal error: multiple allocation solutions"

-- | Process a request and return new node lists
processRequest :: Request -> Result IAllocResult
processRequest request =
  let Request rqtype (ClusterData gl nl il _) = request
  in case rqtype of
       Allocate xi reqn ->
           Cluster.tryMGAlloc gl nl il xi reqn >>= formatAllocate
       Relocate idx reqn exnodes ->
           Cluster.tryMGReloc gl nl il idx reqn exnodes >>= formatAllocate
       Evacuate exnodes ->
           Cluster.tryMGEvac gl nl il exnodes >>= formatEvacuate
       MultiReloc _ _ -> fail "multi-reloc not handled"
       NodeEvacuate _ _ -> fail "node-evacuate not handled"

-- | Reads the request from the data file(s)
readRequest :: Options -> [String] -> IO Request
readRequest opts args = do
  when (null args) $ do
         hPutStrLn stderr "Error: this program needs an input file."
         exitWith $ ExitFailure 1

  input_data <- readFile (head args)
  r1 <- case parseData input_data of
          Bad err -> do
            hPutStrLn stderr $ "Error: " ++ err
            exitWith $ ExitFailure 1
          Ok rq -> return rq
  (if isJust (optDataFile opts) ||  (not . null . optNodeSim) opts
   then do
     cdata <- loadExternalData opts
     let Request rqt _ = r1
     return $ Request rqt cdata
   else return r1)

-- | Main iallocator pipeline.
runIAllocator :: Request -> String
runIAllocator request =
  let (ok, info, result) =
          case processRequest request of
            Ok (msg, r) -> (True, "Request successful: " ++ msg, r)
            Bad msg -> (False, "Request failed: " ++ msg, JSArray [])
  in  formatResponse ok info result

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
  let (_, il) = assignIndices iobj
  -- cluster tags
  ctags <- extrObj "cluster_tags"
  cdata1 <- mergeData [] [] [] [] (ClusterData gl nl il ctags)
  let (msgs, fix_nl) = checkData (cdNodes cdata1) (cdInstances cdata1)
      cdata = cdata1 { cdNodes = fix_nl }
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

          | otherwise -> fail ("Invalid request type '" ++ optype ++ "'")
  return $ (msgs, Request rqtype cdata)

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

-- | Convert allocation/relocation results into the result format.
formatAllocate :: Instance.List -> Cluster.AllocSolution -> Result IAllocResult
formatAllocate il as = do
  let info = describeSolution as
  case Cluster.asSolutions as of
    [] -> fail info
    (nl, inst, nodes, _):[] ->
        do
          let il' = Container.add (Instance.idx inst) inst il
          return (info, showJSON $ map (Node.name) nodes, nl, il')
    _ -> fail "Internal error: multiple allocation solutions"

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

-- | Process a request and return new node lists
processRequest :: Request -> Result IAllocResult
processRequest request =
  let Request rqtype (ClusterData gl nl il _) = request
  in case rqtype of
       Allocate xi reqn ->
           Cluster.tryMGAlloc gl nl il xi reqn >>= formatAllocate il
       ChangeGroup gdxs idxs ->
           Cluster.tryChangeGroup gl nl il idxs gdxs >>=
                  formatNodeEvac gl nl il
       NodeEvacuate xi mode ->
           Cluster.tryNodeEvac gl nl il mode xi >>=
                  formatNodeEvac gl nl il

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
          Ok (fix_msgs, rq) -> maybeShowWarnings fix_msgs >> return rq
  (if isJust (optDataFile opts) ||  (not . null . optNodeSim) opts
   then do
     cdata <- loadExternalData opts
     let Request rqt _ = r1
     return $ Request rqt cdata
   else return r1)

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

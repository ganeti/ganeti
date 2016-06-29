{-| Implementation of the iallocator interface.

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

module Ganeti.HTools.Backend.IAlloc
  ( readRequest
  , runIAllocator
  , processRelocate
  , loadData
  , formatAllocate
  , formatIAllocResult
  , formatMultiAlloc
  ) where

import Data.Either ()
import Data.Maybe (fromMaybe, isJust, fromJust)
import Data.List
import Control.Monad
import System.Time
import Text.JSON (JSObject, JSValue(JSArray),
                  makeObj, encodeStrict, decodeStrict, fromJSObject, showJSON)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.AllocationSolution as AllocSol
import qualified Ganeti.HTools.Cluster.AllocateSecondary as AllocSecondary
import qualified Ganeti.HTools.Cluster.Evacuate as Evacuate
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Nic as Nic
import qualified Ganeti.Constants as C
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(algRestrictToNodes))
import Ganeti.HTools.CLI
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import Ganeti.JSON (maybeFromObj, JSRecord, tryFromObj, toArray, asObjectList, readEitherString, fromJResult, fromObj, fromObjWithDefault, asJSObject)
import Ganeti.Types ( EvacMode(ChangePrimary, ChangeSecondary)
                    , adminStateFromRaw, AdminState(..))
import Ganeti.Utils

{-# ANN module "HLint: ignore Eta reduce" #-}

-- | Type alias for the result of an IAllocator call.
type IAllocResult = (String, JSValue, Node.List, Instance.List)

-- | Parse a NIC within an instance (in a creation request)
parseNic :: String -> JSRecord -> Result Nic.Nic
parseNic n a = do
  mac     <- maybeFromObj a "mac"
  ip      <- maybeFromObj a "ip"
  mode    <- maybeFromObj a "mode" >>= \m -> case m of
               Just "bridged" -> Ok $ Just Nic.Bridged
               Just "routed" -> Ok $ Just Nic.Routed
               Just "openvswitch" -> Ok $ Just Nic.OpenVSwitch
               Nothing -> Ok Nothing
               _ -> Bad $ "invalid NIC mode in instance " ++ n
  link    <- maybeFromObj a "link"
  bridge  <- maybeFromObj a "bridge"
  network <- maybeFromObj a "network"
  return (Nic.create mac ip mode link bridge network)

-- | Parse the basic specifications of an instance.
--
-- Instances in the cluster instance list and the instance in an
-- 'Allocate' request share some common properties, which are read by
-- this function.
parseBaseInstance :: String
                  -> JSRecord
                  -> Result (String, Instance.Instance)
parseBaseInstance n a = do
  let errorMessage = "invalid data for instance '" ++ n ++ "'"
  let extract x = tryFromObj errorMessage a x
  disk  <- extract "disk_space_total"
  jsdisks <- extract "disks" >>= toArray >>= asObjectList
  dsizes <- mapM (flip (tryFromObj errorMessage) "size" . fromJSObject) jsdisks
  dspindles <- mapM (annotateResult errorMessage .
                     flip maybeFromObj "spindles" . fromJSObject) jsdisks
  let disks = zipWith Instance.Disk dsizes dspindles
  mem   <- extract "memory"
  vcpus <- extract "vcpus"
  tags  <- extract "tags"
  dt    <- extract "disk_template"
  su    <- extract "spindle_use"
  nics  <- extract "nics" >>= toArray >>= asObjectList >>=
           mapM (parseNic n . fromJSObject)
  state <- (tryFromObj errorMessage a "admin_state" >>= adminStateFromRaw)
           `mplus` Ok AdminUp
  let getRunSt AdminOffline = StatusOffline
      getRunSt AdminDown = StatusDown
      getRunSt AdminUp = Running
  -- Not forthcoming by default.
  forthcoming <- extract "forthcoming" `orElse` Ok False
  return
    (n,
     Instance.create n mem disk disks vcpus (getRunSt state) tags
                     True 0 0 dt su nics forthcoming)

-- | Parses an instance as found in the cluster instance list.
parseInstance :: NameAssoc -- ^ The node name-to-index association list
              -> String    -- ^ The name of the instance
              -> JSRecord  -- ^ The JSON object
              -> Result (String, Instance.Instance)
parseInstance ktn n a = do
  base <- parseBaseInstance n a
  nodes <- fromObj a "nodes"
  (pnode, snodes) <-
    case nodes of
      [] -> Bad $ "empty node list for instance " ++ n
      x:xs -> readEitherString x >>= \x' -> return (x', xs)
  pidx <- lookupNode ktn n pnode
  sidx <- case snodes of
            [] -> return Node.noSecondary
            x:_ -> readEitherString x >>= lookupNode ktn n
  return (n, Instance.setBoth (snd base) pidx sidx)

-- | Parses a node as found in the cluster node list.
parseNode :: NameAssoc   -- ^ The group association
          -> String      -- ^ The node's name
          -> JSRecord    -- ^ The JSON object
          -> Result (String, Node.Node)
parseNode ktg n a = do
  let desc = "invalid data for node '" ++ n ++ "'"
      extract x = tryFromObj desc a x
      extractDef def key = fromObjWithDefault a key def
  offline <- extract "offline"
  drained <- extract "drained"
  guuid   <- extract "group"
  vm_capable  <- annotateResult desc $ maybeFromObj a "vm_capable"
  let vm_capable' = fromMaybe True vm_capable
  gidx <- lookupGroup ktg n guuid
  ndparams <- extract "ndparams" >>= asJSObject
  -- Despite the fact that tags field is reported by iallocator.py,
  -- some tests don't contain tags field
  tags <- extractDef [] "tags"
  excl_stor <- tryFromObj desc (fromJSObject ndparams) "exclusive_storage"
  let live = not offline && vm_capable'
      lvextract def = eitherLive live def . extract
  sptotal <- if excl_stor
             then lvextract 0 "total_spindles"
             else tryFromObj desc (fromJSObject ndparams) "spindle_count"
  spfree <- lvextract 0 "free_spindles"
  mtotal <- lvextract 0.0 "total_memory"
  mnode  <- lvextract 0 "reserved_memory"
  mfree  <- lvextract 0 "free_memory"
  dtotal <- lvextract 0.0 "total_disk"
  dfree  <- lvextract 0 "free_disk"
  ctotal <- lvextract 0.0 "total_cpus"
  cnos <- lvextract 0 "reserved_cpus"
  let node = flip Node.setNodeTags tags $
             Node.create n mtotal mnode mfree dtotal dfree ctotal cnos
             (not live || drained) sptotal spfree gidx excl_stor
  return (n, node)

-- | Parses a group as found in the cluster group list.
parseGroup :: String     -- ^ The group UUID
           -> JSRecord   -- ^ The JSON object
           -> Result (String, Group.Group)
parseGroup u a = do
  let extract x = tryFromObj ("invalid data for group '" ++ u ++ "'") a x
  name <- extract "name"
  apol <- extract "alloc_policy"
  nets <- extract "networks"
  ipol <- extract "ipolicy"
  tags <- extract "tags"
  return (u, Group.create name u apol nets ipol tags)

-- | Top-level parser.
--
-- The result is a tuple of eventual warning messages and the parsed
-- request; if parsing the input data fails, we'll return a 'Bad'
-- value.
parseData :: ClockTime -- ^ The current time
          -> String -- ^ The JSON message as received from Ganeti
          -> Result ([String], Request) -- ^ Result tuple
parseData now body = do
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
  let ex_tags = extractExTags ctags
      dsrd_loc_tags = extractDesiredLocations ctags
      updateTags = updateExclTags ex_tags .
                   updateDesiredLocationTags dsrd_loc_tags
  cdata1 <- mergeData [] [] [] [] now (ClusterData gl nl il ctags defIPolicy)
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
              rgn       <- maybeFromObj request "group_name"
              rest_nodes <- maybeFromObj request "restrict-to-nodes"
              req_nodes <- extrReq "required_nodes"
              inew      <- parseBaseInstance rname request
              let io = updateTags $ snd inew
              return $ Allocate io (Cluster.AllocDetails req_nodes rgn)
                                rest_nodes
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
              prqs <- forM inst_reqs (\r ->
                               do
                                 rname     <- extrFromReq r "name"
                                 rgn       <- maybeFromObj request "group_name"
                                 req_nodes <- extrFromReq r "required_nodes"
                                 inew      <- parseBaseInstance rname r
                                 let io = updateTags $ snd inew
                                 return (io, Cluster.AllocDetails
                                               req_nodes rgn))
              return $ MultiAllocate prqs
        | optype == C.iallocatorModeAllocateSecondary ->
            do
              rname <- extrReq "name"
              ridx  <- lookupInstance kti rname
              return $ AllocateSecondary ridx
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
describeSolution :: AllocSol.GenericAllocSolution a -> String
describeSolution = intercalate ", " . AllocSol.asLog

-- | Convert allocation/relocation results into the result format.
formatAllocate :: Instance.List
               -> AllocSol.GenericAllocSolution a
               -> Result IAllocResult
formatAllocate il as = do
  let info = describeSolution as
  case AllocSol.asSolution as of
    Nothing -> fail info
    Just (nl, inst, nodes, _) ->
      do
        let il' = Container.add (Instance.idx inst) inst il
        return (info, showJSON $ map Node.name nodes, nl, il')

-- | Convert allocation/relocation results into the result format.
formatAllocateSecondary :: Instance.List
                        -> AllocSol.GenericAllocSolution a
                        -> Result IAllocResult
formatAllocateSecondary il as = do
  let info = describeSolution as
  case AllocSol.asSolution as of
    Nothing -> fail info
    Just (nl, inst, [_, snode], _) ->
      do
        let il' = Container.add (Instance.idx inst) inst il
        return (info, showJSON $ Node.name snode, nl, il')
    _ -> fail $ "Internal error (not a DRBD allocation); info was: " ++ info

-- | Convert multi allocation results into the result format.
formatMultiAlloc :: ( Node.List, Instance.List
                    , Cluster.GenericAllocSolutionList a)
                 -> Result IAllocResult
formatMultiAlloc (fin_nl, fin_il, ars) =
  let rars = reverse ars
      (allocated, failed) = partition (isJust . AllocSol.asSolution . snd) rars
      aars = map (\(_, ar) ->
                     let (_, inst, nodes, _) = fromJust $ AllocSol.asSolution ar
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
               -> (Node.List, Instance.List, Evacuate.EvacSolution)
               -> Result IAllocResult
formatNodeEvac gl nl il (fin_nl, fin_il, es) =
  let iname = Instance.name . flip Container.find il
      nname = Node.name . flip Container.find nl
      gname = Group.name . flip Container.find gl
      fes = map (\(idx, msg) -> (iname idx, msg)) $ Evacuate.esFailed es
      mes = map (\(idx, gdx, ndxs) -> (iname idx, gname gdx, map nname ndxs))
            $ Evacuate.esMoved es
      failed = length fes
      moved  = length mes
      info = show failed ++ " instances failed to move and " ++ show moved ++
             " were moved successfully"
  in Ok (info, showJSON (mes, fes, Evacuate.esOpCodes es), fin_nl, fin_il)

-- | Runs relocate for a single instance.
--
-- This is wrapper over the 'Cluster.tryNodeEvac' function that is run
-- with a single instance (ours), and further it checks that the
-- result it got (in the nodes field) is actually consistent, as
-- tryNodeEvac is designed to output primarily an opcode list, not a
-- node list.
processRelocate :: AlgorithmOptions
                -> Group.List      -- ^ The group list
                -> Node.List       -- ^ The node list
                -> Instance.List   -- ^ The instance list
                -> Idx             -- ^ The index of the instance to move
                -> Int             -- ^ The number of nodes required
                -> [Ndx]           -- ^ Nodes which should not be used
                -> Result (Node.List, Instance.List, [Ndx]) -- ^ Solution list
processRelocate opts gl nl il idx 1 exndx = do
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
  (nl', il', esol) <- Evacuate.tryNodeEvac opts gl nl il reloc_type [idx]
  nodes <- case lookup idx (Evacuate.esFailed esol) of
             Just msg -> fail msg
             Nothing ->
                 case lookup idx (map (\(a, _, b) -> (a, b))
                                  (Evacuate.esMoved esol)) of
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

processRelocate _ _ _ _ _ reqn _ =
  fail $ "Exchange " ++ show reqn ++ " nodes mode is not implemented"

formatRelocate :: (Node.List, Instance.List, [Ndx])
               -> Result IAllocResult
formatRelocate (nl, il, ndxs) =
  let nodes = map (`Container.find` nl) ndxs
      names = map Node.name nodes
  in Ok ("success", showJSON names, nl, il)

-- | Process a request and return new node lists.
processRequest :: AlgorithmOptions -> Request -> Result IAllocResult
processRequest opts request =
  let Request rqtype (ClusterData gl nl il _ _) = request
  in case rqtype of
       Allocate xi (Cluster.AllocDetails reqn Nothing) rest_nodes ->
         let opts' = opts { algRestrictToNodes = algRestrictToNodes opts
                                                 `mplus` rest_nodes }
         in Cluster.tryMGAlloc opts' gl nl il xi reqn >>= formatAllocate il
       Allocate xi (Cluster.AllocDetails reqn (Just gn)) rest_nodes ->
         let opts' = opts { algRestrictToNodes = algRestrictToNodes opts
                                                 `mplus` rest_nodes }
         in Cluster.tryGroupAlloc opts' gl nl il gn xi reqn
            >>= formatAllocate il
       Relocate idx reqn exnodes ->
         processRelocate opts gl nl il idx reqn exnodes >>= formatRelocate
       ChangeGroup gdxs idxs ->
         Cluster.tryChangeGroup opts gl nl il idxs gdxs >>=
                formatNodeEvac gl nl il
       NodeEvacuate xi mode ->
         Evacuate.tryNodeEvac opts gl nl il mode xi >>=
                formatNodeEvac gl nl il
       MultiAllocate xies ->
         Cluster.allocList opts gl nl il xies [] >>= formatMultiAlloc
       AllocateSecondary xi ->
         AllocSecondary.tryAllocateSecondary opts gl nl il xi
           >>= formatAllocateSecondary il

-- | Reads the request from the data file(s).
readRequest :: FilePath -> IO Request
readRequest fp = do
  now <- getClockTime
  input_data <- case fp of
                  "-" -> getContents
                  _   -> readFile fp
  case parseData now input_data of
    Bad err -> exitErr err
    Ok (fix_msgs, rq) -> maybeShowWarnings fix_msgs >> return rq

-- | Format an IAlloc result to maybe the new cluster and a response.
formatIAllocResult :: Result IAllocResult
                   -> (Maybe (Node.List, Instance.List), String)
formatIAllocResult iallocResult =
  let (ok, info, result, cdata) =
        case iallocResult of
          Ok (msg, r, nl, il) -> (True, "Request successful: " ++ msg, r,
                                  Just (nl, il))
          Bad msg -> (False, "Request failed: " ++ msg, JSArray [], Nothing)
      rstring = formatResponse ok info result
  in (cdata, rstring)

-- | Main iallocator pipeline.
runIAllocator :: AlgorithmOptions
              -> Request -> (Maybe (Node.List, Instance.List), String)
runIAllocator opts request = formatIAllocResult $ processRequest opts request

-- | Load the data from an iallocation request file
loadData :: FilePath -- ^ The path to the file
         -> IO (Result ClusterData)
loadData fp = do
  Request _ cdata <- readRequest fp
  return $ Ok cdata

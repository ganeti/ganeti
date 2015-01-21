{-# LANGUAGE TupleSections #-}

{-| Parsing data from text-files.

This module holds the code for loading the cluster state from text
files, as produced by @gnt-node@ and @gnt-instance@ @list@ command.

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

module Ganeti.HTools.Backend.Text
  ( loadData
  , parseData
  , loadInst
  , loadNode
  , loadISpec
  , loadMultipleMinMaxISpecs
  , loadIPolicy
  , serializeInstance
  , serializeInstances
  , serializeNode
  , serializeNodes
  , serializeGroup
  , serializeISpec
  , serializeMultipleMinMaxISpecs
  , serializeIPolicy
  , serializeCluster
  ) where

import Control.Monad
import Data.List

import Text.Printf (printf)

import Ganeti.BasicTypes
import Ganeti.Utils
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

-- * Helper functions

-- | Simple wrapper over sepSplit
commaSplit :: String -> [String]
commaSplit = sepSplit ','

-- * Serialisation functions

-- | Serialize a single group.
serializeGroup :: Group.Group -> String
serializeGroup grp =
  printf "%s|%s|%s|%s|%s" (Group.name grp) (Group.uuid grp)
           (allocPolicyToRaw (Group.allocPolicy grp))
           (intercalate "," (Group.allTags grp))
           (intercalate "," (Group.networks grp))

-- | Generate group file data from a group list.
serializeGroups :: Group.List -> String
serializeGroups = unlines . map serializeGroup . Container.elems

-- | Serialize a single node.
serializeNode :: Group.List -- ^ The list of groups (needed for group uuid)
              -> Node.Node  -- ^ The node to be serialised
              -> String
serializeNode gl node =
  printf "%s|%.0f|%d|%d|%.0f|%d|%.0f|%c|%s|%d|%s|%s|%d|%d|%f" (Node.name node)
           (Node.tMem node) (Node.nMem node) (Node.fMem node)
           (Node.tDsk node) (Node.fDsk node) (Node.tCpu node)
           (if Node.offline node then 'Y' else
              if Node.isMaster node then 'M' else 'N')
           (Group.uuid grp)
           (Node.tSpindles node)
           (intercalate "," (Node.nTags node))
           (if Node.exclStorage node then "Y" else "N")
           (Node.fSpindles node)
           (Node.nCpu node) (Node.tCpuSpeed node)
    where grp = Container.find (Node.group node) gl

-- | Generate node file data from node objects.
serializeNodes :: Group.List -> Node.List -> String
serializeNodes gl = unlines . map (serializeNode gl) . Container.elems

-- | Serialize a single instance.
serializeInstance :: Node.List         -- ^ The node list (needed for
                                       -- node names)
                  -> Instance.Instance -- ^ The instance to be serialised
                  -> String
serializeInstance nl inst =
  let iname = Instance.name inst
      pnode = Container.nameOf nl (Instance.pNode inst)
      sidx = Instance.sNode inst
      snode = (if sidx == Node.noSecondary
                 then ""
                 else Container.nameOf nl sidx)
  in printf "%s|%d|%d|%d|%s|%s|%s|%s|%s|%s|%d|%s|%s"
       iname (Instance.mem inst) (Instance.dsk inst)
       (Instance.vcpus inst) (instanceStatusToRaw (Instance.runSt inst))
       (if Instance.autoBalance inst then "Y" else "N")
       pnode snode (diskTemplateToRaw (Instance.diskTemplate inst))
       (intercalate "," (Instance.allTags inst)) (Instance.spindleUse inst)
       -- disk spindles are summed together, as it's done for disk size
       (case Instance.getTotalSpindles inst of
          Nothing -> "-"
          Just x -> show x)
       (if Instance.forthcoming inst then "Y" else "N")

-- | Generate instance file data from instance objects.
serializeInstances :: Node.List -> Instance.List -> String
serializeInstances nl =
  unlines . map (serializeInstance nl) . Container.elems

-- | Separator between ISpecs (in MinMaxISpecs).
iSpecsSeparator :: Char
iSpecsSeparator = ';'

-- | Generate a spec data from a given ISpec object.
serializeISpec :: ISpec -> String
serializeISpec ispec =
  -- this needs to be kept in sync with the object definition
  let ISpec mem_s cpu_c disk_s disk_c nic_c su = ispec
      strings = [show mem_s, show cpu_c, show disk_s, show disk_c, show nic_c,
                 show su]
  in intercalate "," strings

-- | Generate disk template data.
serializeDiskTemplates :: [DiskTemplate] -> String
serializeDiskTemplates = intercalate "," . map diskTemplateToRaw

-- | Generate min/max instance specs data.
serializeMultipleMinMaxISpecs :: [MinMaxISpecs] -> String
serializeMultipleMinMaxISpecs minmaxes =
  intercalate [iSpecsSeparator] $ foldr serialpair [] minmaxes
  where serialpair (MinMaxISpecs minspec maxspec) acc =
          serializeISpec minspec : serializeISpec maxspec : acc

-- | Generate policy data from a given policy object.
serializeIPolicy :: String -> IPolicy -> String
serializeIPolicy owner ipol =
  let IPolicy minmax stdspec dts vcpu_ratio spindle_ratio = ipol
      strings = [ owner
                , serializeISpec stdspec
                , serializeMultipleMinMaxISpecs minmax
                , serializeDiskTemplates dts
                , show vcpu_ratio
                , show spindle_ratio
                ]
  in intercalate "|" strings

-- | Generates the entire ipolicy section from the cluster and group
-- objects.
serializeAllIPolicies :: IPolicy -> Group.List -> String
serializeAllIPolicies cpol gl =
  let groups = Container.elems gl
      allpolicies = ("", cpol) :
                    map (\g -> (Group.name g, Group.iPolicy g)) groups
      strings = map (uncurry serializeIPolicy) allpolicies
  in unlines strings

-- | Generate complete cluster data from node and instance lists.
serializeCluster :: ClusterData -> String
serializeCluster (ClusterData gl nl il ctags cpol) =
  let gdata = serializeGroups gl
      ndata = serializeNodes gl nl
      idata = serializeInstances nl il
      pdata = serializeAllIPolicies cpol gl
  -- note: not using 'unlines' as that adds too many newlines
  in intercalate "\n" [gdata, ndata, idata, unlines ctags, pdata]

-- * Parsing functions

-- | Load a group from a field list.
loadGroup :: (Monad m) => [String]
          -> m (String, Group.Group) -- ^ The result, a tuple of group
                                     -- UUID and group object
loadGroup (name:gid:apol:tags:nets:_) = do
  xapol <- allocPolicyFromRaw apol
  let xtags = commaSplit tags
  let xnets = commaSplit nets
  return (gid, Group.create name gid xapol xnets defIPolicy xtags)
loadGroup [name, gid, apol, tags] = loadGroup [name, gid, apol, tags, ""]
loadGroup s = fail $ "Invalid/incomplete group data: '" ++ show s ++ "'"

-- | Load a node from a field list.
loadNode :: (Monad m) =>
            NameAssoc             -- ^ Association list with current groups
         -> [String]              -- ^ Input data as a list of fields
         -> m (String, Node.Node) -- ^ The result, a tuple o node name
                                  -- and node object
loadNode ktg (name:tm:nm:fm:td:fd:tc:fo:gu:spindles:tags:
              excl_stor:free_spindles:nos_cpu:cpu_speed:_) = do
  gdx <- lookupGroup ktg name gu
  new_node <-
      if "?" `elem` [tm,nm,fm,td,fd,tc] then
          return $ Node.create name 0 0 0 0 0 0 0 True 0 0 gdx False
      else do
        let vtags = commaSplit tags
        vtm <- tryRead name tm
        vnm <- tryRead name nm
        vfm <- tryRead name fm
        vtd <- tryRead name td
        vfd <- tryRead name fd
        vtc <- tryRead name tc
        vnc <- tryRead name nos_cpu
        vspindles <- tryRead name spindles
        vcpu_speed <- tryRead name cpu_speed
        vfree_spindles <- tryRead name free_spindles
        vexcl_stor <- case excl_stor of
                        "Y" -> return True
                        "N" -> return False
                        _ -> fail $
                             "Invalid exclusive_storage value for node '" ++
                             name ++ "': " ++ excl_stor
        return . flip Node.setMaster (fo == "M") . flip Node.setNodeTags vtags
          . flip Node.setCpuSpeed vcpu_speed
          $ Node.create name vtm vnm vfm vtd vfd vtc vnc (fo == "Y") vspindles
            vfree_spindles gdx vexcl_stor
  return (name, new_node)

loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu] =
  loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, "1"]

loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles] =
  loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, ""]

loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, tags] =
  loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, tags, "N"]

loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, tags,
              excl_stor] =
  loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, tags,
                excl_stor, "0"]

loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, tags,
              excl_stor, free_spindles] =
  loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, tags,
                excl_stor, free_spindles, "1"]

loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, tags,
              excl_stor, free_spindles, nos_cpu] =
  loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu, spindles, tags,
                excl_stor, free_spindles, nos_cpu, "1.0"]

loadNode _ s = fail $ "Invalid/incomplete node data: '" ++ show s ++ "'"

-- | Load an instance from a field list.
loadInst :: NameAssoc -- ^ Association list with the current nodes
         -> [String]  -- ^ Input data as a list of fields
         -> Result (String, Instance.Instance) -- ^ A tuple of
                                               -- instance name and
                                               -- the instance object
loadInst ktn (name:mem:dsk:vcpus:status:auto_bal:pnode:snode
             :dt:tags:su:spindles:forthcoming_yn:_) = do
  pidx <- lookupNode ktn name pnode
  sidx <- if null snode
            then return Node.noSecondary
            else lookupNode ktn name snode
  vmem <- tryRead name mem
  dsize <- tryRead name dsk
  vvcpus <- tryRead name vcpus
  vstatus <- instanceStatusFromRaw status
  auto_balance <- case auto_bal of
                    "Y" -> return True
                    "N" -> return False
                    _ -> fail $ "Invalid auto_balance value '" ++ auto_bal ++
                         "' for instance " ++ name
  disk_template <- annotateResult ("Instance " ++ name)
                   (diskTemplateFromRaw dt)
  spindle_use <- tryRead name su
  vspindles <- case spindles of
                 "-" -> return Nothing
                 _ -> liftM Just (tryRead name spindles)
  forthcoming <- case forthcoming_yn of
                   "Y" -> return True
                   "N" -> return False
                   x -> fail $ "Invalid forthcoming value '"
                               ++ x ++ "' for instance " ++ name
  let disk = Instance.Disk dsize vspindles
  let vtags = commaSplit tags
      newinst = Instance.create name vmem dsize [disk] vvcpus vstatus vtags
                auto_balance pidx sidx disk_template spindle_use [] forthcoming
  when (Instance.hasSecondary newinst && sidx == pidx) . fail $
    "Instance " ++ name ++ " has same primary and secondary node - " ++ pnode
  return (name, newinst)

loadInst ktn [ name, mem, dsk, vcpus, status, auto_bal, pnode, snode
             , dt, tags, su, spindles ] =
  loadInst ktn [ name, mem, dsk, vcpus, status, auto_bal, pnode, snode
               , dt, tags, su, spindles, "N" ] -- older versions were not
                                               -- forthcoming

loadInst ktn [ name, mem, dsk, vcpus, status, auto_bal, pnode, snode
             , dt, tags ] = loadInst ktn [ name, mem, dsk, vcpus, status,
                                           auto_bal, pnode, snode, dt, tags,
                                           "1" ]

loadInst ktn [ name, mem, dsk, vcpus, status, auto_bal, pnode, snode
             , dt, tags, su ] =
  loadInst ktn [ name, mem, dsk, vcpus, status, auto_bal, pnode, snode, dt
               , tags, su, "-" ]

loadInst _ s = fail $ "Invalid/incomplete instance data: '" ++ show s ++ "'"

-- | Loads a spec from a field list.
loadISpec :: String -> [String] -> Result ISpec
loadISpec owner (mem_s:cpu_c:dsk_s:dsk_c:nic_c:su:_) = do
  xmem_s <- tryRead (owner ++ "/memsize") mem_s
  xcpu_c <- tryRead (owner ++ "/cpucount") cpu_c
  xdsk_s <- tryRead (owner ++ "/disksize") dsk_s
  xdsk_c <- tryRead (owner ++ "/diskcount") dsk_c
  xnic_c <- tryRead (owner ++ "/niccount") nic_c
  xsu    <- tryRead (owner ++ "/spindleuse") su
  return $ ISpec xmem_s xcpu_c xdsk_s xdsk_c xnic_c xsu
loadISpec owner s = fail $ "Invalid ispec data for " ++ owner ++ ": " ++ show s

-- | Load a single min/max ISpec pair
loadMinMaxISpecs :: String -> String -> String -> Result MinMaxISpecs
loadMinMaxISpecs owner minspec maxspec = do
  xminspec <- loadISpec (owner ++ "/minspec") (commaSplit minspec)
  xmaxspec <- loadISpec (owner ++ "/maxspec") (commaSplit maxspec)
  return $ MinMaxISpecs xminspec xmaxspec

-- | Break a list of ispecs strings into a list of (min/max) ispecs pairs
breakISpecsPairs :: String -> [String] -> Result [(String, String)]
breakISpecsPairs _ [] =
  return []
breakISpecsPairs owner (x:y:xs) = do
  rest <- breakISpecsPairs owner xs
  return $ (x, y) : rest
breakISpecsPairs owner _ =
  fail $ "Odd number of min/max specs for " ++ owner

-- | Load a list of min/max ispecs pairs
loadMultipleMinMaxISpecs :: String -> [String] -> Result [MinMaxISpecs]
loadMultipleMinMaxISpecs owner ispecs = do
  pairs <- breakISpecsPairs owner ispecs
  mapM (uncurry $ loadMinMaxISpecs owner) pairs

-- | Loads an ipolicy from a field list.
loadIPolicy :: [String] -> Result (String, IPolicy)
loadIPolicy (owner:stdspec:minmaxspecs:dtemplates:
             vcpu_ratio:spindle_ratio:_) = do
  xstdspec <- loadISpec (owner ++ "/stdspec") (commaSplit stdspec)
  xminmaxspecs <- loadMultipleMinMaxISpecs owner $
                  sepSplit iSpecsSeparator minmaxspecs
  xdts <- mapM diskTemplateFromRaw $ commaSplit dtemplates
  xvcpu_ratio <- tryRead (owner ++ "/vcpu_ratio") vcpu_ratio
  xspindle_ratio <- tryRead (owner ++ "/spindle_ratio") spindle_ratio
  return (owner,
          IPolicy xminmaxspecs xstdspec
                xdts xvcpu_ratio xspindle_ratio)
loadIPolicy s = fail $ "Invalid ipolicy data: '" ++ show s ++ "'"

loadOnePolicy :: (IPolicy, Group.List) -> String
              -> Result (IPolicy, Group.List)
loadOnePolicy (cpol, gl) line = do
  (owner, ipol) <- loadIPolicy (sepSplit '|' line)
  case owner of
    "" -> return (ipol, gl) -- this is a cluster policy (no owner)
    _ -> do
      grp <- Container.findByName gl owner
      let grp' = grp { Group.iPolicy = ipol }
          gl' = Container.add (Group.idx grp') grp' gl
      return (cpol, gl')

-- | Loads all policies from the policy section
loadAllIPolicies :: Group.List -> [String] -> Result (IPolicy, Group.List)
loadAllIPolicies gl =
  foldM loadOnePolicy (defIPolicy, gl)

-- | Convert newline and delimiter-separated text.
--
-- This function converts a text in tabular format as generated by
-- @gnt-instance list@ and @gnt-node list@ to a list of objects using
-- a supplied conversion function.
loadTabular :: (Monad m, Element a) =>
               [String] -- ^ Input data, as a list of lines
            -> ([String] -> m (String, a)) -- ^ Conversion function
            -> m ( NameAssoc
                 , Container.Container a ) -- ^ A tuple of an
                                           -- association list (name
                                           -- to object) and a set as
                                           -- used in
                                           -- "Ganeti.HTools.Container"

loadTabular lines_data convert_fn = do
  let rows = map (sepSplit '|') lines_data
  kerows <- mapM convert_fn rows
  return $ assignIndices kerows

-- | Load the cluser data from disk.
--
-- This is an alias to 'readFile' just for consistency with the other
-- modules.
readData :: String    -- ^ Path to the text file
         -> IO String -- ^ Contents of the file
readData = readFile

-- | Builds the cluster data from text input.
parseData :: String -- ^ Text data
          -> Result ClusterData
parseData fdata = do
  let flines = lines fdata
  (glines, nlines, ilines, ctags, pollines) <-
      case sepSplit "" flines of
        -- Ignore all additional fields
        a:b:c:d:e:_ -> Ok (a, b, c, d, e)
        [a, b, c, d] -> Ok (a, b, c, d, [])
        xs -> Bad $ printf "Invalid format of the input file: %d sections\
                           \ instead of 4 or more" (length xs)
  {- group file: name uuid alloc_policy -}
  (ktg, gl) <- loadTabular glines loadGroup
  {- node file: name t_mem n_mem f_mem t_disk f_disk t_cpu offline grp_uuid
                spindles tags -}
  (ktn, nl) <- loadTabular nlines (loadNode ktg)
  {- instance file: name mem disk vcpus status auto_bal pnode snode
                    disk_template tags spindle_use -}
  (_, il) <- loadTabular ilines (loadInst ktn)
  {- the tags are simply line-based, no processing needed -}
  {- process policies -}
  (cpol, gl') <- loadAllIPolicies gl pollines
  return (ClusterData gl' nl il ctags cpol)

-- | Top level function for data loading.
loadData :: String -- ^ Path to the text file
         -> IO (Result ClusterData)
loadData = fmap parseData . readData

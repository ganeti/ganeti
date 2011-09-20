{-| Parsing data from text-files.

This module holds the code for loading the cluster state from text
files, as produced by @gnt-node@ and @gnt-instance@ @list@ command.

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

module Ganeti.HTools.Text
    (
      loadData
    , parseData
    , loadInst
    , loadNode
    , serializeInstances
    , serializeNode
    , serializeNodes
    , serializeCluster
    ) where

import Control.Monad
import Data.List

import Text.Printf (printf)

import Ganeti.HTools.Utils
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

-- * Serialisation functions

-- | Serialize a single group.
serializeGroup :: Group.Group -> String
serializeGroup grp =
    printf "%s|%s|%s" (Group.name grp) (Group.uuid grp)
               (allocPolicyToString (Group.allocPolicy grp))

-- | Generate group file data from a group list.
serializeGroups :: Group.List -> String
serializeGroups = unlines . map serializeGroup . Container.elems

-- | Serialize a single node.
serializeNode :: Group.List -- ^ The list of groups (needed for group uuid)
              -> Node.Node  -- ^ The node to be serialised
              -> String
serializeNode gl node =
    printf "%s|%.0f|%d|%d|%.0f|%d|%.0f|%c|%s" (Node.name node)
               (Node.tMem node) (Node.nMem node) (Node.fMem node)
               (Node.tDsk node) (Node.fDsk node) (Node.tCpu node)
               (if Node.offline node then 'Y' else 'N')
               (Group.uuid grp)
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
    let
        iname = Instance.name inst
        pnode = Container.nameOf nl (Instance.pNode inst)
        sidx = Instance.sNode inst
        snode = (if sidx == Node.noSecondary
                    then ""
                    else Container.nameOf nl sidx)
    in
      printf "%s|%d|%d|%d|%s|%s|%s|%s|%s|%s"
             iname (Instance.mem inst) (Instance.dsk inst)
             (Instance.vcpus inst) (Instance.runSt inst)
             (if Instance.autoBalance inst then "Y" else "N")
             pnode snode (diskTemplateToString (Instance.diskTemplate inst))
             (intercalate "," (Instance.tags inst))

-- | Generate instance file data from instance objects.
serializeInstances :: Node.List -> Instance.List -> String
serializeInstances nl =
    unlines . map (serializeInstance nl) . Container.elems

-- | Generate complete cluster data from node and instance lists.
serializeCluster :: ClusterData -> String
serializeCluster (ClusterData gl nl il ctags) =
  let gdata = serializeGroups gl
      ndata = serializeNodes gl nl
      idata = serializeInstances nl il
  -- note: not using 'unlines' as that adds too many newlines
  in intercalate "\n" [gdata, ndata, idata, unlines ctags]

-- * Parsing functions

-- | Load a group from a field list.
loadGroup :: (Monad m) => [String]
          -> m (String, Group.Group) -- ^ The result, a tuple of group
                                     -- UUID and group object
loadGroup [name, gid, apol] = do
  xapol <- allocPolicyFromString apol
  return (gid, Group.create name gid xapol)

loadGroup s = fail $ "Invalid/incomplete group data: '" ++ show s ++ "'"

-- | Load a node from a field list.
loadNode :: (Monad m) =>
            NameAssoc             -- ^ Association list with current groups
         -> [String]              -- ^ Input data as a list of fields
         -> m (String, Node.Node) -- ^ The result, a tuple o node name
                                  -- and node object
loadNode ktg [name, tm, nm, fm, td, fd, tc, fo, gu] = do
  gdx <- lookupGroup ktg name gu
  new_node <-
      if any (== "?") [tm,nm,fm,td,fd,tc] || fo == "Y" then
          return $ Node.create name 0 0 0 0 0 0 True gdx
      else do
        vtm <- tryRead name tm
        vnm <- tryRead name nm
        vfm <- tryRead name fm
        vtd <- tryRead name td
        vfd <- tryRead name fd
        vtc <- tryRead name tc
        return $ Node.create name vtm vnm vfm vtd vfd vtc False gdx
  return (name, new_node)
loadNode _ s = fail $ "Invalid/incomplete node data: '" ++ show s ++ "'"

-- | Load an instance from a field list.
loadInst :: NameAssoc -- ^ Association list with the current nodes
         -> [String]  -- ^ Input data as a list of fields
         -> Result (String, Instance.Instance) -- ^ A tuple of
                                               -- instance name and
                                               -- the instance object
loadInst ktn [ name, mem, dsk, vcpus, status, auto_bal, pnode, snode
             , dt, tags ] = do
  pidx <- lookupNode ktn name pnode
  sidx <- (if null snode then return Node.noSecondary
           else lookupNode ktn name snode)
  vmem <- tryRead name mem
  vdsk <- tryRead name dsk
  vvcpus <- tryRead name vcpus
  auto_balance <- case auto_bal of
                    "Y" -> return True
                    "N" -> return False
                    _ -> fail $ "Invalid auto_balance value '" ++ auto_bal ++
                         "' for instance " ++ name
  disk_template <- annotateResult ("Instance " ++ name)
                   (diskTemplateFromString dt)
  when (sidx == pidx) $ fail $ "Instance " ++ name ++
           " has same primary and secondary node - " ++ pnode
  let vtags = sepSplit ',' tags
      newinst = Instance.create name vmem vdsk vvcpus status vtags
                auto_balance pidx sidx disk_template
  return (name, newinst)
loadInst _ s = fail $ "Invalid/incomplete instance data: '" ++ show s ++ "'"

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
  (glines, nlines, ilines, ctags) <-
      case sepSplit "" flines of
        [a, b, c, d] -> Ok (a, b, c, d)
        xs -> Bad $ printf "Invalid format of the input file: %d sections\
                           \ instead of 4" (length xs)
  {- group file: name uuid -}
  (ktg, gl) <- loadTabular glines loadGroup
  {- node file: name t_mem n_mem f_mem t_disk f_disk -}
  (ktn, nl) <- loadTabular nlines (loadNode ktg)
  {- instance file: name mem disk status pnode snode -}
  (_, il) <- loadTabular ilines (loadInst ktn)
  {- the tags are simply line-based, no processing needed -}
  return (ClusterData gl nl il ctags)

-- | Top level function for data loading.
loadData :: String -- ^ Path to the text file
         -> IO (Result ClusterData)
loadData = fmap parseData . readData

{-| Generic data loader.

This module holds the common code for parsing the input data after it
has been loaded from external sources.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

module Ganeti.HTools.Loader
  ( mergeData
  , clearDynU
  , checkData
  , assignIndices
  , setMaster
  , lookupNode
  , lookupInstance
  , lookupGroup
  , eitherLive
  , commonSuffix
  , extractExTags
  , updateExclTags
  , RqType(..)
  , Request(..)
  , ClusterData(..)
  , isAllocationRequest
  , emptyCluster
  , extractDesiredLocations
  , updateDesiredLocationTags
  ) where

import Control.Monad
import Data.List
import qualified Data.Map as M
import Data.Maybe
import qualified Data.Set as Set
import Text.Printf (printf)
import System.Time (ClockTime(..))

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Moves as Moves

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Tags as Tags
import qualified Ganeti.HTools.Tags.Constants as TagsC
import Ganeti.HTools.Types
import Ganeti.Utils
import Ganeti.Types (EvacMode)

-- * Types

{-| The iallocator request type.

This type denotes what request we got from Ganeti and also holds
request-specific fields.

-}
data RqType
  = Allocate Instance.Instance Cluster.AllocDetails (Maybe [String])
    -- ^ A new instance allocation, maybe with allocation restrictions
  | AllocateSecondary Idx                             -- ^ Find a suitable
                                                      -- secondary node for disk
                                                      -- conversion
  | Relocate Idx Int [Ndx]                            -- ^ Choose a new
                                                      --   secondary node
  | NodeEvacuate [Idx] EvacMode                       -- ^ node-evacuate mode
  | ChangeGroup [Gdx] [Idx]                           -- ^ Multi-relocate mode
  | MultiAllocate [(Instance.Instance, Cluster.AllocDetails)]
                                                      -- ^ Multi-allocate mode
    deriving (Show)

-- | A complete request, as received from Ganeti.
data Request = Request RqType ClusterData
               deriving (Show)

-- | Decide whether a request asks to allocate new instances; if so, also
-- return the desired node group, if a unique node group is specified.
-- That is, return `Nothing` if the request is not an allocation request,
-- `Just Nothing`, if it is an Allocation request, but there is no unique
-- group specified, and return `Just (Just g)` if it is an allocation request
-- uniquely requesting Group `g`.
isAllocationRequest :: RqType -> Maybe (Maybe String)
isAllocationRequest (Allocate _ (Cluster.AllocDetails _ grp) _) = Just grp
isAllocationRequest (MultiAllocate reqs) = Just $
  case ordNub . catMaybes
       $ map (\(_, Cluster.AllocDetails _ grp) -> grp) reqs of
    [grp] -> Just grp
    _ -> Nothing
isAllocationRequest _ = Nothing

-- | The cluster state.
data ClusterData = ClusterData
  { cdGroups    :: Group.List    -- ^ The node group list
  , cdNodes     :: Node.List     -- ^ The node list
  , cdInstances :: Instance.List -- ^ The instance list
  , cdTags      :: [String]      -- ^ The cluster tags
  , cdIPolicy   :: IPolicy       -- ^ The cluster instance policy
  } deriving (Show, Eq)

-- | An empty cluster.
emptyCluster :: ClusterData
emptyCluster = ClusterData Container.empty Container.empty Container.empty []
                 defIPolicy

-- * Functions

-- | Lookups a node into an assoc list.
lookupNode :: (Monad m) => NameAssoc -> String -> String -> m Ndx
lookupNode ktn inst node =
  maybe (fail $ "Unknown node '" ++ node ++ "' for instance " ++ inst) return $
    M.lookup node ktn

-- | Lookups an instance into an assoc list.
lookupInstance :: (Monad m) => NameAssoc -> String -> m Idx
lookupInstance kti inst =
  maybe (fail $ "Unknown instance '" ++ inst ++ "'") return $ M.lookup inst kti

-- | Lookups a group into an assoc list.
lookupGroup :: (Monad m) => NameAssoc -> String -> String -> m Gdx
lookupGroup ktg nname gname =
  maybe (fail $ "Unknown group '" ++ gname ++ "' for node " ++ nname) return $
    M.lookup gname ktg

-- | Given a list of elements (and their names), assign indices to them.
assignIndices :: (Element a) =>
                 [(String, a)]
              -> (NameAssoc, Container.Container a)
assignIndices name_element =
  let (name_idx, idx_element) =
          unzip . map (\ (idx, (k, v)) -> ((k, idx), (idx, setIdx v idx)))
          . zip [0..] $ name_element
  in (M.fromList name_idx, Container.fromList idx_element)

-- | Given am indexed node list, and the name of the master, mark it as such.
setMaster :: (Monad m) => NameAssoc -> Node.List -> String -> m Node.List
setMaster node_names node_idx master = do
  kmaster <- maybe (fail $ "Master node " ++ master ++ " unknown") return $
             M.lookup master node_names
  let mnode = Container.find kmaster node_idx
  return $ Container.add kmaster (Node.setMaster mnode True) node_idx

-- | Given the nodes with the location tags already set correctly, compute
-- the location score for an instance.
setLocationScore :: Node.List -> Instance.Instance -> Instance.Instance
setLocationScore nl inst =
  let pnode = Container.find (Instance.pNode inst) nl
      snode = Container.find (Instance.sNode inst) nl
  in Moves.setInstanceLocationScore inst pnode snode

-- | For each instance, add its index to its primary and secondary nodes.
fixNodes :: Node.List
         -> Instance.Instance
         -> Node.List
fixNodes accu inst =
  let pdx = Instance.pNode inst
      sdx = Instance.sNode inst
      pold = Container.find pdx accu
      pnew = Node.setPri pold inst
      ac2 = Container.add pdx pnew accu
  in if sdx /= Node.noSecondary
       then let sold = Container.find sdx accu
                snew = Node.setSec sold inst
            in Container.add sdx snew ac2
       else ac2

-- | Set the node's policy to its group one. Note that this requires
-- the group to exist (should have been checked before), otherwise it
-- will abort with a runtime error.
setNodePolicy :: Group.List -> Node.Node -> Node.Node
setNodePolicy gl node =
  let grp = Container.find (Node.group node) gl
      gpol = Group.iPolicy grp
  in Node.setPolicy gpol node

-- | Update instance with exclusion tags list.
updateExclTags :: [String] -> Instance.Instance -> Instance.Instance
updateExclTags tl inst =
  let allTags = Instance.allTags inst
      exclTags = filter (\tag -> any (`isPrefixOf` tag) tl) allTags
  in inst { Instance.exclTags = exclTags }

-- | Update instance with desired location tags list.
updateDesiredLocationTags :: [String] -> Instance.Instance -> Instance.Instance
updateDesiredLocationTags tl inst =
  let allTags = Instance.allTags inst
      dsrdLocTags = filter (\tag -> any (`isPrefixOf` tag) tl) allTags
  in inst { Instance.dsrdLocTags = Set.fromList dsrdLocTags }


-- | Update the movable attribute.
updateMovable :: [String]           -- ^ Selected instances (if not empty)
              -> [String]           -- ^ Excluded instances
              -> Instance.Instance  -- ^ Target Instance
              -> Instance.Instance  -- ^ Target Instance with updated attribute
updateMovable selinsts exinsts inst =
  if Instance.name inst `elem` exinsts ||
     not (null selinsts || Instance.name inst `elem` selinsts)
    then Instance.setMovable inst False
    else inst

-- | Disables moves for instances with a split group.
disableSplitMoves :: Node.List -> Instance.Instance -> Instance.Instance
disableSplitMoves nl inst =
  if not . isOk . Cluster.instanceGroup nl $ inst
    then Instance.setMovable inst False
    else inst

-- | Set the auto-repair policy for an instance.
setArPolicy :: [String]       -- ^ Cluster tags
            -> Group.List     -- ^ List of node groups
            -> Node.List      -- ^ List of nodes
            -> Instance.List  -- ^ List of instances
            -> ClockTime      -- ^ Current timestamp, to evaluate ArSuspended
            -> Instance.List  -- ^ Updated list of instances
setArPolicy ctags gl nl il time =
  let getArPolicy' = flip getArPolicy time
      cpol = fromMaybe ArNotEnabled $ getArPolicy' ctags
      gpols = Container.map (fromMaybe cpol . getArPolicy' . Group.allTags) gl
      ipolfn = getArPolicy' . Instance.allTags
      nlookup = flip Container.find nl . Instance.pNode
      glookup = flip Container.find gpols . Node.group . nlookup
      updateInstance inst = inst {
        Instance.arPolicy = fromMaybe (glookup inst) $ ipolfn inst }
  in
   Container.map updateInstance il

-- | Get the auto-repair policy from a list of tags.
--
-- This examines the ganeti:watcher:autorepair and
-- ganeti:watcher:autorepair:suspend tags to determine the policy. If none of
-- these tags are present, Nothing (and not ArNotEnabled) is returned.
getArPolicy :: [String] -> ClockTime -> Maybe AutoRepairPolicy
getArPolicy tags time =
  let enabled = mapMaybe (autoRepairTypeFromRaw <=<
                          chompPrefix TagsC.autoRepairTagEnabled) tags
      suspended = mapMaybe (chompPrefix TagsC.autoRepairTagSuspended) tags
      futureTs = filter (> time) . map (flip TOD 0) $
                   mapMaybe (tryRead "auto-repair suspend time") suspended
  in
   case () of
     -- Note how we must return ArSuspended even if "enabled" is empty, so that
     -- node groups or instances can suspend repairs that were enabled at an
     -- upper scope (cluster or node group).
     _ | "" `elem` suspended -> Just $ ArSuspended Forever
       | not $ null futureTs -> Just . ArSuspended . Until . maximum $ futureTs
       | not $ null enabled  -> Just $ ArEnabled (minimum enabled)
       | otherwise           -> Nothing

-- | Compute the longest common suffix of a list of strings that
-- starts with a dot.
longestDomain :: [String] -> String
longestDomain [] = ""
longestDomain (x:xs) =
  foldr (\ suffix accu -> if all (isSuffixOf suffix) xs
                            then suffix
                            else accu)
          "" $ filter (isPrefixOf ".") (tails x)

-- | Extracts the exclusion tags from the cluster configuration.
extractExTags :: [String] -> [String]
extractExTags = filter (not . null) . mapMaybe (chompPrefix TagsC.exTagsPrefix)

-- | Extracts the desired locations from the instance tags.
extractDesiredLocations :: [String] -> [String]
extractDesiredLocations =
  filter (not . null) . mapMaybe (chompPrefix TagsC.desiredLocationPrefix)

-- | Extracts the common suffix from node\/instance names.
commonSuffix :: Node.List -> Instance.List -> String
commonSuffix nl il =
  let node_names = map Node.name $ Container.elems nl
      inst_names = map Instance.name $ Container.elems il
  in longestDomain (node_names ++ inst_names)

-- | Set the migration-related tags on a node given the cluster tags;
-- this assumes that the node tags are already set on that node.
addMigrationTags :: [String]  -- ^ cluster tags
                 -> Node.Node -> Node.Node
addMigrationTags ctags node =
  let ntags = Node.nTags node
      migTags = Tags.getMigRestrictions ctags ntags
      rmigTags = Tags.getRecvMigRestrictions ctags ntags
  in Node.setRecvMigrationTags (Node.setMigrationTags node migTags) rmigTags

-- | Set the location tags on a node given the cluster tags;
-- this assumes that the node tags are already set on that node.
addLocationTags :: [String] -- ^ cluster tags
                -> Node.Node -> Node.Node
addLocationTags ctags node =
  let ntags = Node.nTags node
  in Node.setLocationTags node $ Tags.getLocations ctags ntags

-- | Initializer function that loads the data from a node and instance
-- list and massages it into the correct format.
mergeData :: [(String, DynUtil)]  -- ^ Instance utilisation data
          -> [String]             -- ^ Exclusion tags
          -> [String]             -- ^ Selected instances (if not empty)
          -> [String]             -- ^ Excluded instances
          -> ClockTime            -- ^ The current timestamp
          -> ClusterData          -- ^ Data from backends
          -> Result ClusterData   -- ^ Fixed cluster data
mergeData um extags selinsts exinsts time cdata@(ClusterData gl nl il ctags _) =
  let il2 = setArPolicy ctags gl nl il time
      il3 = foldl' (\im (name, n_util) ->
                        case Container.findByName im name of
                          Nothing -> im -- skipping unknown instance
                          Just inst ->
                              let new_i = inst { Instance.util = n_util }
                              in Container.add (Instance.idx inst) new_i im
                   ) il2 um
      allextags = extags ++ extractExTags ctags
      dsrdLocTags = extractDesiredLocations ctags
      inst_names = map Instance.name $ Container.elems il3
      selinst_lkp = map (lookupName inst_names) selinsts
      exinst_lkp = map (lookupName inst_names) exinsts
      lkp_unknown = filter (not . goodLookupResult) (selinst_lkp ++ exinst_lkp)
      selinst_names = map lrContent selinst_lkp
      exinst_names = map lrContent exinst_lkp
      node_names = map Node.name (Container.elems nl)
      common_suffix = longestDomain (node_names ++ inst_names)
      il4 = Container.map (computeAlias common_suffix .
                           updateExclTags allextags .
                           updateDesiredLocationTags dsrdLocTags .
                           updateMovable selinst_names exinst_names) il3
      nl2 = Container.map (addLocationTags ctags) nl
      il5 = Container.map (setLocationScore nl2) il4
      nl3 = foldl' fixNodes nl2 (Container.elems il5)
      nl4 = Container.map (setNodePolicy gl .
                           computeAlias common_suffix .
                           (`Node.buildPeers` il4)) nl3
      il6 = Container.map (disableSplitMoves nl3) il5
      nl5 = Container.map (addMigrationTags ctags) nl4
  in if' (null lkp_unknown)
         (Ok cdata { cdNodes = nl5, cdInstances = il6 })
         (Bad $ "Unknown instance(s): " ++ show(map lrContent lkp_unknown))

-- | In a cluster description, clear dynamic utilisation information.
clearDynU :: ClusterData -> Result ClusterData
clearDynU cdata@(ClusterData _ _ il _ _) =
  let il2 = Container.map (\ inst -> inst {Instance.util = zeroUtil }) il
  in Ok cdata { cdInstances = il2 }

-- | Checks the cluster data for consistency.
checkData :: Node.List -> Instance.List
          -> ([String], Node.List)
checkData nl il =
    Container.mapAccum
        (\ msgs node ->
             let nname = Node.name node
                 delta_mem = truncate (Node.tMem node)
                             - Node.nMem node
                             - Node.fMem node
                             - nodeImem node il
                 delta_dsk = truncate (Node.tDsk node)
                             - Node.fDsk node
                             - nodeIdsk node il
                 newn = node `Node.setXmem` delta_mem
                 umsg1 =
                   if delta_mem > 512 || delta_dsk > 1024
                      then printf "node %s is missing %d MB ram \
                                  \and %d GB disk"
                                  nname delta_mem (delta_dsk `div` 1024):msgs
                      else msgs
             in (umsg1, newn)
        ) [] nl

-- | Compute the amount of memory used by primary instances on a node.
nodeImem :: Node.Node -> Instance.List -> Int
nodeImem node il =
  let rfind = flip Container.find il
      il' = map rfind $ Node.pList node
      oil' = filter Instance.usesMemory il'
  in sum . map Instance.mem $ oil'


-- | Compute the amount of disk used by instances on a node (either primary
-- or secondary).
nodeIdsk :: Node.Node -> Instance.List -> Int
nodeIdsk node il =
  let rfind = flip Container.find il
  in sum . map (Instance.dsk . rfind)
       $ Node.pList node ++ Node.sList node

-- | Get live information or a default value
eitherLive :: (Monad m) => Bool -> a -> m a -> m a
eitherLive True _ live_data = live_data
eitherLive False def_data _ = return def_data

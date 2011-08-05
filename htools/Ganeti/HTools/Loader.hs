{-| Generic data loader.

This module holds the common code for parsing the input data after it
has been loaded from external sources.

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

module Ganeti.HTools.Loader
    ( mergeData
    , checkData
    , assignIndices
    , lookupName
    , goodLookupResult
    , lookupNode
    , lookupInstance
    , lookupGroup
    , commonSuffix
    , RqType(..)
    , Request(..)
    , ClusterData(..)
    , emptyCluster
    , compareNameComponent
    , prefixMatch
    , LookupResult(..)
    , MatchPriority(..)
    ) where

import Data.List
import Data.Function
import qualified Data.Map as M
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group

import Ganeti.HTools.Types
import Ganeti.HTools.Utils

-- * Constants

-- | The exclusion tag prefix.
exTagsPrefix :: String
exTagsPrefix = "htools:iextags:"

-- * Types

{-| The iallocator request type.

This type denotes what request we got from Ganeti and also holds
request-specific fields.

-}
data RqType
    = Allocate Instance.Instance Int -- ^ A new instance allocation
    | Relocate Idx Int [Ndx]         -- ^ Choose a new secondary node
    | NodeEvacuate [Idx] EvacMode    -- ^ node-evacuate mode
    | ChangeGroup [Gdx] [Idx]        -- ^ Multi-relocate mode
    deriving (Show, Read)

-- | A complete request, as received from Ganeti.
data Request = Request RqType ClusterData
    deriving (Show, Read)

-- | The cluster state.
data ClusterData = ClusterData
    { cdGroups    :: Group.List    -- ^ The node group list
    , cdNodes     :: Node.List     -- ^ The node list
    , cdInstances :: Instance.List -- ^ The instance list
    , cdTags      :: [String]      -- ^ The cluster tags
    } deriving (Show, Read)

-- | The priority of a match in a lookup result.
data MatchPriority = ExactMatch
                   | MultipleMatch
                   | PartialMatch
                   | FailMatch
                   deriving (Show, Read, Enum, Eq, Ord)

-- | The result of a name lookup in a list.
data LookupResult = LookupResult
    { lrMatchPriority :: MatchPriority -- ^ The result type
    -- | Matching value (for ExactMatch, PartialMatch), Lookup string otherwise
    , lrContent :: String
    } deriving (Show, Read)

-- | Lookup results have an absolute preference ordering.
instance Eq LookupResult where
  (==) = (==) `on` lrMatchPriority

instance Ord LookupResult where
  compare = compare `on` lrMatchPriority

-- | An empty cluster.
emptyCluster :: ClusterData
emptyCluster = ClusterData Container.empty Container.empty Container.empty []

-- * Functions

-- | Lookups a node into an assoc list.
lookupNode :: (Monad m) => NameAssoc -> String -> String -> m Ndx
lookupNode ktn inst node =
    case M.lookup node ktn of
      Nothing -> fail $ "Unknown node '" ++ node ++ "' for instance " ++ inst
      Just idx -> return idx

-- | Lookups an instance into an assoc list.
lookupInstance :: (Monad m) => NameAssoc -> String -> m Idx
lookupInstance kti inst =
    case M.lookup inst kti of
      Nothing -> fail $ "Unknown instance '" ++ inst ++ "'"
      Just idx -> return idx

-- | Lookups a group into an assoc list.
lookupGroup :: (Monad m) => NameAssoc -> String -> String -> m Gdx
lookupGroup ktg nname gname =
    case M.lookup gname ktg of
      Nothing -> fail $ "Unknown group '" ++ gname ++ "' for node " ++ nname
      Just idx -> return idx

-- | Check for prefix matches in names.
-- Implemented in Ganeti core utils.text.MatchNameComponent
-- as the regexp r"^%s(\..*)?$" % re.escape(key)
prefixMatch :: String  -- ^ Lookup
            -> String  -- ^ Full name
            -> Bool    -- ^ Whether there is a prefix match
prefixMatch lkp = isPrefixOf (lkp ++ ".")

-- | Is the lookup priority a "good" one?
goodMatchPriority :: MatchPriority -> Bool
goodMatchPriority ExactMatch = True
goodMatchPriority PartialMatch = True
goodMatchPriority _ = False

-- | Is the lookup result an actual match?
goodLookupResult :: LookupResult -> Bool
goodLookupResult = goodMatchPriority . lrMatchPriority

-- | Compares a canonical name and a lookup string.
compareNameComponent :: String        -- ^ Canonical (target) name
                     -> String        -- ^ Partial (lookup) name
                     -> LookupResult  -- ^ Result of the lookup
compareNameComponent cnl lkp =
  select (LookupResult FailMatch lkp)
  [ (cnl == lkp          , LookupResult ExactMatch cnl)
  , (prefixMatch lkp cnl , LookupResult PartialMatch cnl)
  ]

-- | Lookup a string and choose the best result.
chooseLookupResult :: String       -- ^ Lookup key
                   -> String       -- ^ String to compare to the lookup key
                   -> LookupResult -- ^ Previous result
                   -> LookupResult -- ^ New result
chooseLookupResult lkp cstr old =
  -- default: use class order to pick the minimum result
  select (min new old)
  -- special cases:
  -- short circuit if the new result is an exact match
  [ ((lrMatchPriority new) == ExactMatch, new)
  -- if both are partial matches generate a multiple match
  , (partial2, LookupResult MultipleMatch lkp)
  ] where new = compareNameComponent cstr lkp
          partial2 = all ((PartialMatch==) . lrMatchPriority) [old, new]

-- | Find the canonical name for a lookup string in a list of names.
lookupName :: [String]      -- ^ List of keys
           -> String        -- ^ Lookup string
           -> LookupResult  -- ^ Result of the lookup
lookupName l s = foldr (chooseLookupResult s)
                       (LookupResult FailMatch s) l

-- | Given a list of elements (and their names), assign indices to them.
assignIndices :: (Element a) =>
                 [(String, a)]
              -> (NameAssoc, Container.Container a)
assignIndices nodes =
  let (na, idx_node) =
          unzip . map (\ (idx, (k, v)) -> ((k, idx), (idx, setIdx v idx)))
          . zip [0..] $ nodes
  in (M.fromList na, Container.fromList idx_node)

-- | For each instance, add its index to its primary and secondary nodes.
fixNodes :: Node.List
         -> Instance.Instance
         -> Node.List
fixNodes accu inst =
    let
        pdx = Instance.pNode inst
        sdx = Instance.sNode inst
        pold = Container.find pdx accu
        pnew = Node.setPri pold inst
        ac2 = Container.add pdx pnew accu
    in
      if sdx /= Node.noSecondary
      then let sold = Container.find sdx accu
               snew = Node.setSec sold inst
           in Container.add sdx snew ac2
      else ac2

-- | Remove non-selected tags from the exclusion list.
filterExTags :: [String] -> Instance.Instance -> Instance.Instance
filterExTags tl inst =
    let old_tags = Instance.tags inst
        new_tags = filter (\tag -> any (`isPrefixOf` tag) tl)
                   old_tags
    in inst { Instance.tags = new_tags }

-- | Update the movable attribute.
updateMovable :: [String]           -- ^ Selected instances (if not empty)
              -> [String]           -- ^ Excluded instances
              -> Instance.Instance  -- ^ Target Instance
              -> Instance.Instance  -- ^ Target Instance with updated attribute
updateMovable selinsts exinsts inst =
    if Instance.sNode inst == Node.noSecondary ||
       Instance.name inst `elem` exinsts ||
       not (null selinsts || Instance.name inst `elem` selinsts)
    then Instance.setMovable inst False
    else inst

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
extractExTags =
    map (drop (length exTagsPrefix)) .
    filter (isPrefixOf exTagsPrefix)

-- | Extracts the common suffix from node\/instance names.
commonSuffix :: Node.List -> Instance.List -> String
commonSuffix nl il =
    let node_names = map Node.name $ Container.elems nl
        inst_names = map Instance.name $ Container.elems il
    in longestDomain (node_names ++ inst_names)

-- | Initializer function that loads the data from a node and instance
-- list and massages it into the correct format.
mergeData :: [(String, DynUtil)]  -- ^ Instance utilisation data
          -> [String]             -- ^ Exclusion tags
          -> [String]             -- ^ Selected instances (if not empty)
          -> [String]             -- ^ Excluded instances
          -> ClusterData          -- ^ Data from backends
          -> Result ClusterData   -- ^ Fixed cluster data
mergeData um extags selinsts exinsts cdata@(ClusterData _ nl il2 tags) =
  let il = Container.elems il2
      il3 = foldl' (\im (name, n_util) ->
                        case Container.findByName im name of
                          Nothing -> im -- skipping unknown instance
                          Just inst ->
                              let new_i = inst { Instance.util = n_util }
                              in Container.add (Instance.idx inst) new_i im
                   ) il2 um
      allextags = extags ++ extractExTags tags
      inst_names = map Instance.name il
      selinst_lkp = map (lookupName inst_names) selinsts
      exinst_lkp = map (lookupName inst_names) exinsts
      lkp_unknown = filter (not . goodLookupResult) (selinst_lkp ++ exinst_lkp)
      selinst_names = map lrContent selinst_lkp
      exinst_names = map lrContent exinst_lkp
      il4 = Container.map (filterExTags allextags .
                           updateMovable selinst_names exinst_names) il3
      nl2 = foldl' fixNodes nl (Container.elems il4)
      nl3 = Container.map (`Node.buildPeers` il4) nl2
      node_names = map Node.name (Container.elems nl)
      common_suffix = longestDomain (node_names ++ inst_names)
      snl = Container.map (computeAlias common_suffix) nl3
      sil = Container.map (computeAlias common_suffix) il4
  in if' (null lkp_unknown)
         (Ok cdata { cdNodes = snl, cdInstances = sil })
         (Bad $ "Unknown instance(s): " ++ show(map lrContent lkp_unknown))

-- | Checks the cluster data for consistency.
checkData :: Node.List -> Instance.List
          -> ([String], Node.List)
checkData nl il =
    Container.mapAccum
        (\ msgs node ->
             let nname = Node.name node
                 nilst = map (`Container.find` il) (Node.pList node)
                 dilst = filter (not . Instance.running) nilst
                 adj_mem = sum . map Instance.mem $ dilst
                 delta_mem = truncate (Node.tMem node)
                             - Node.nMem node
                             - Node.fMem node
                             - nodeImem node il
                             + adj_mem
                 delta_dsk = truncate (Node.tDsk node)
                             - Node.fDsk node
                             - nodeIdsk node il
                 newn = Node.setFmem (Node.setXmem node delta_mem)
                        (Node.fMem node - adj_mem)
                 umsg1 = [printf "node %s is missing %d MB ram \
                                 \and %d GB disk"
                                 nname delta_mem (delta_dsk `div` 1024) |
                                 delta_mem > 512 || delta_dsk > 1024]::[String]
             in (msgs ++ umsg1, newn)
        ) [] nl

-- | Compute the amount of memory used by primary instances on a node.
nodeImem :: Node.Node -> Instance.List -> Int
nodeImem node il =
    let rfind = flip Container.find il
    in sum . map (Instance.mem . rfind)
           $ Node.pList node

-- | Compute the amount of disk used by instances on a node (either primary
-- or secondary).
nodeIdsk :: Node.Node -> Instance.List -> Int
nodeIdsk node il =
    let rfind = flip Container.find il
    in sum . map (Instance.dsk . rfind)
           $ Node.pList node ++ Node.sList node

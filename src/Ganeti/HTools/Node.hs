{-| Module describing a node.

    All updates are functional (copy-based) and return a new node with
    updated value.
-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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

module Ganeti.HTools.Node
  ( Node(..)
  , List
  -- * Constructor
  , create
  -- ** Finalization after data loading
  , buildPeers
  , setIdx
  , setAlias
  , setOffline
  , setXmem
  , setFmem
  , setPri
  , setSec
  , setMaster
  , setNodeTags
  , setMdsk
  , setMcpu
  , setPolicy
  -- * Tag maps
  , addTags
  , delTags
  , rejectAddTags
  -- * Instance (re)location
  , removePri
  , removeSec
  , addPri
  , addPriEx
  , addSec
  , addSecEx
  -- * Stats
  , availDisk
  , availMem
  , availCpu
  , iMem
  , iDsk
  , conflictingPrimaries
  -- * Formatting
  , defaultFields
  , showHeader
  , showField
  , list
  -- * Misc stuff
  , AssocList
  , AllocElement
  , noSecondary
  , computeGroups
  , mkNodeGraph
  , mkRebootNodeGraph
  , haveExclStorage
  ) where

import Control.Monad (liftM, liftM2)
import Control.Applicative ((<$>), (<*>))
import qualified Data.Foldable as Foldable
import Data.Function (on)
import qualified Data.Graph as Graph
import qualified Data.IntMap as IntMap
import Data.List hiding (group)
import qualified Data.Map as Map
import Data.Ord (comparing)
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.PeerMap as P

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Types as T

-- * Type declarations

-- | The tag map type.
type TagMap = Map.Map String Int

-- | The node type.
data Node = Node
  { name     :: String    -- ^ The node name
  , alias    :: String    -- ^ The shortened name (for display purposes)
  , tMem     :: Double    -- ^ Total memory (MiB)
  , nMem     :: Int       -- ^ Node memory (MiB)
  , fMem     :: Int       -- ^ Free memory (MiB)
  , xMem     :: Int       -- ^ Unaccounted memory (MiB)
  , tDsk     :: Double    -- ^ Total disk space (MiB)
  , fDsk     :: Int       -- ^ Free disk space (MiB)
  , tCpu     :: Double    -- ^ Total CPU count
  , nCpu     :: Int       -- ^ VCPUs used by the node OS
  , uCpu     :: Int       -- ^ Used VCPU count
  , tSpindles :: Int      -- ^ Node spindles (spindle_count node parameter,
                          -- or actual spindles, see note below)
  , fSpindles :: Int      -- ^ Free spindles (see note below)
  , pList    :: [T.Idx]   -- ^ List of primary instance indices
  , sList    :: [T.Idx]   -- ^ List of secondary instance indices
  , idx      :: T.Ndx     -- ^ Internal index for book-keeping
  , peers    :: P.PeerMap -- ^ Pnode to instance mapping
  , failN1   :: Bool      -- ^ Whether the node has failed n1
  , rMem     :: Int       -- ^ Maximum memory needed for failover by
                          -- primaries of this node
  , pMem     :: Double    -- ^ Percent of free memory
  , pDsk     :: Double    -- ^ Percent of free disk
  , pRem     :: Double    -- ^ Percent of reserved memory
  , pCpu     :: Double    -- ^ Ratio of virtual to physical CPUs
  , mDsk     :: Double    -- ^ Minimum free disk ratio
  , loDsk    :: Int       -- ^ Autocomputed from mDsk low disk
                          -- threshold
  , hiCpu    :: Int       -- ^ Autocomputed from mCpu high cpu
                          -- threshold
  , hiSpindles :: Double  -- ^ Limit auto-computed from policy spindle_ratio
                          -- and the node spindle count (see note below)
  , instSpindles :: Double -- ^ Spindles used by instances (see note below)
  , offline  :: Bool      -- ^ Whether the node should not be used for
                          -- allocations and skipped from score
                          -- computations
  , isMaster :: Bool      -- ^ Whether the node is the master node
  , nTags    :: [String]  -- ^ The node tags for this node
  , utilPool :: T.DynUtil -- ^ Total utilisation capacity
  , utilLoad :: T.DynUtil -- ^ Sum of instance utilisation
  , pTags    :: TagMap    -- ^ Primary instance exclusion tags and their count
  , group    :: T.Gdx     -- ^ The node's group (index)
  , iPolicy  :: T.IPolicy -- ^ The instance policy (of the node's group)
  , exclStorage :: Bool   -- ^ Effective value of exclusive_storage
  } deriving (Show, Eq)
{- A note on how we handle spindles

With exclusive storage spindles is a resource, so we track the number of
spindles still available (fSpindles). This is the only reliable way, as some
spindles could be used outside of Ganeti. When exclusive storage is off,
spindles are a way to represent disk I/O pressure, and hence we track the amount
used by the instances. We compare it against 'hiSpindles', computed from the
instance policy, to avoid policy violations. In both cases we store the total
spindles in 'tSpindles'.
-}

instance T.Element Node where
  nameOf = name
  idxOf = idx
  setAlias = setAlias
  setIdx = setIdx
  allNames n = [name n, alias n]

-- | A simple name for the int, node association list.
type AssocList = [(T.Ndx, Node)]

-- | A simple name for a node map.
type List = Container.Container Node

-- | A simple name for an allocation element (here just for logistic
-- reasons).
type AllocElement = (List, Instance.Instance, [Node], T.Score)

-- | Constant node index for a non-moveable instance.
noSecondary :: T.Ndx
noSecondary = -1

-- * Helper functions

-- | Add a tag to a tagmap.
addTag :: TagMap -> String -> TagMap
addTag t s = Map.insertWith (+) s 1 t

-- | Add multiple tags.
addTags :: TagMap -> [String] -> TagMap
addTags = foldl' addTag

-- | Adjust or delete a tag from a tagmap.
delTag :: TagMap -> String -> TagMap
delTag t s = Map.update (\v -> if v > 1
                                 then Just (v-1)
                                 else Nothing)
             s t

-- | Remove multiple tags.
delTags :: TagMap -> [String] -> TagMap
delTags = foldl' delTag

-- | Check if we can add a list of tags to a tagmap.
rejectAddTags :: TagMap -> [String] -> Bool
rejectAddTags t = any (`Map.member` t)

-- | Check how many primary instances have conflicting tags. The
-- algorithm to compute this is to sum the count of all tags, then
-- subtract the size of the tag map (since each tag has at least one,
-- non-conflicting instance); this is equivalent to summing the
-- values in the tag map minus one.
conflictingPrimaries :: Node -> Int
conflictingPrimaries (Node { pTags = t }) = Foldable.sum t - Map.size t

-- | Helper function to increment a base value depending on the passed
-- boolean argument.
incIf :: (Num a) => Bool -> a -> a -> a
incIf True  base delta = base + delta
incIf False base _     = base

-- | Helper function to decrement a base value depending on the passed
-- boolean argument.
decIf :: (Num a) => Bool -> a -> a -> a
decIf True  base delta = base - delta
decIf False base _     = base

-- | Is exclusive storage enabled on any node?
haveExclStorage :: List -> Bool
haveExclStorage nl =
  any exclStorage $ Container.elems nl

-- * Initialization functions

-- | Create a new node.
--
-- The index and the peers maps are empty, and will be need to be
-- update later via the 'setIdx' and 'buildPeers' functions.
create :: String -> Double -> Int -> Int
       -> Double -> Int -> Double -> Int -> Bool
       -> Int -> Int -> T.Gdx -> Bool
       -> Node
create name_init mem_t_init mem_n_init mem_f_init
       dsk_t_init dsk_f_init cpu_t_init cpu_n_init offline_init
       spindles_t_init spindles_f_init group_init excl_stor =
  Node { name = name_init
       , alias = name_init
       , tMem = mem_t_init
       , nMem = mem_n_init
       , fMem = mem_f_init
       , tDsk = dsk_t_init
       , fDsk = dsk_f_init
       , tCpu = cpu_t_init
       , nCpu = cpu_n_init
       , uCpu = cpu_n_init
       , tSpindles = spindles_t_init
       , fSpindles = spindles_f_init
       , pList = []
       , sList = []
       , failN1 = True
       , idx = -1
       , peers = P.empty
       , rMem = 0
       , pMem = fromIntegral mem_f_init / mem_t_init
       , pDsk = if excl_stor
                then computePDsk spindles_f_init $ fromIntegral spindles_t_init
                else computePDsk dsk_f_init dsk_t_init
       , pRem = 0
       , pCpu = fromIntegral cpu_n_init / cpu_t_init
       , offline = offline_init
       , isMaster = False
       , nTags = []
       , xMem = 0
       , mDsk = T.defReservedDiskRatio
       , loDsk = mDskToloDsk T.defReservedDiskRatio dsk_t_init
       , hiCpu = mCpuTohiCpu (T.iPolicyVcpuRatio T.defIPolicy) cpu_t_init
       , hiSpindles = computeHiSpindles (T.iPolicySpindleRatio T.defIPolicy)
                      spindles_t_init
       , instSpindles = 0
       , utilPool = T.baseUtil
       , utilLoad = T.zeroUtil
       , pTags = Map.empty
       , group = group_init
       , iPolicy = T.defIPolicy
       , exclStorage = excl_stor
       }

-- | Conversion formula from mDsk\/tDsk to loDsk.
mDskToloDsk :: Double -> Double -> Int
mDskToloDsk mval = floor . (mval *)

-- | Conversion formula from mCpu\/tCpu to hiCpu.
mCpuTohiCpu :: Double -> Double -> Int
mCpuTohiCpu mval = floor . (mval *)

-- | Conversiojn formula from spindles and spindle ratio to hiSpindles.
computeHiSpindles :: Double -> Int -> Double
computeHiSpindles spindle_ratio = (spindle_ratio *) . fromIntegral

-- | Changes the index.
--
-- This is used only during the building of the data structures.
setIdx :: Node -> T.Ndx -> Node
setIdx t i = t {idx = i}

-- | Changes the alias.
--
-- This is used only during the building of the data structures.
setAlias :: Node -> String -> Node
setAlias t s = t { alias = s }

-- | Sets the offline attribute.
setOffline :: Node -> Bool -> Node
setOffline t val = t { offline = val }

-- | Sets the master attribute
setMaster :: Node -> Bool -> Node
setMaster t val = t { isMaster = val }

-- | Sets the node tags attribute
setNodeTags :: Node -> [String] -> Node
setNodeTags t val = t { nTags = val }

-- | Sets the unnaccounted memory.
setXmem :: Node -> Int -> Node
setXmem t val = t { xMem = val }

-- | Sets the max disk usage ratio.
setMdsk :: Node -> Double -> Node
setMdsk t val = t { mDsk = val, loDsk = mDskToloDsk val (tDsk t) }

-- | Sets the max cpu usage ratio. This will update the node's
-- ipolicy, losing sharing (but it should be a seldomly done operation).
setMcpu :: Node -> Double -> Node
setMcpu t val =
  let new_ipol = (iPolicy t) { T.iPolicyVcpuRatio = val }
  in t { hiCpu = mCpuTohiCpu val (tCpu t), iPolicy = new_ipol }

-- | Sets the policy.
setPolicy :: T.IPolicy -> Node -> Node
setPolicy pol node =
  node { iPolicy = pol
       , hiCpu = mCpuTohiCpu (T.iPolicyVcpuRatio pol) (tCpu node)
       , hiSpindles = computeHiSpindles (T.iPolicySpindleRatio pol)
                      (tSpindles node)
       }

-- | Computes the maximum reserved memory for peers from a peer map.
computeMaxRes :: P.PeerMap -> P.Elem
computeMaxRes = P.maxElem

-- | Builds the peer map for a given node.
buildPeers :: Node -> Instance.List -> Node
buildPeers t il =
  let mdata = map
              (\i_idx -> let inst = Container.find i_idx il
                             mem = if Instance.usesSecMem inst
                                     then Instance.mem inst
                                     else 0
                         in (Instance.pNode inst, mem))
              (sList t)
      pmap = P.accumArray (+) mdata
      new_rmem = computeMaxRes pmap
      new_failN1 = fMem t <= new_rmem
      new_prem = fromIntegral new_rmem / tMem t
  in t {peers=pmap, failN1 = new_failN1, rMem = new_rmem, pRem = new_prem}

-- | Calculate the new spindle usage
calcSpindleUse ::
                  Bool -- Action: True = adding instance, False = removing it
               -> Node -> Instance.Instance -> Double
calcSpindleUse _ (Node {exclStorage = True}) _ = 0.0
calcSpindleUse act n@(Node {exclStorage = False}) i =
  f (Instance.usesLocalStorage i) (instSpindles n)
    (fromIntegral $ Instance.spindleUse i)
    where
      f :: Bool -> Double -> Double -> Double -- avoid monomorphism restriction
      f = if act then incIf else decIf

-- | Calculate the new number of free spindles
calcNewFreeSpindles ::
                       Bool -- Action: True = adding instance, False = removing
                    -> Node -> Instance.Instance -> Int
calcNewFreeSpindles _ (Node {exclStorage = False}) _ = 0
calcNewFreeSpindles act n@(Node {exclStorage = True}) i =
  case Instance.getTotalSpindles i of
    Nothing -> if act
               then -1 -- Force a spindle error, so the instance don't go here
               else fSpindles n -- No change, as we aren't sure
    Just s -> (if act then (-) else (+)) (fSpindles n) s

-- | Assigns an instance to a node as primary and update the used VCPU
-- count, utilisation data and tags map.
setPri :: Node -> Instance.Instance -> Node
setPri t inst = t { pList = Instance.idx inst:pList t
                  , uCpu = new_count
                  , pCpu = fromIntegral new_count / tCpu t
                  , utilLoad = utilLoad t `T.addUtil` Instance.util inst
                  , pTags = addTags (pTags t) (Instance.exclTags inst)
                  , instSpindles = calcSpindleUse True t inst
                  }
  where new_count = Instance.applyIfOnline inst (+ Instance.vcpus inst)
                    (uCpu t )

-- | Assigns an instance to a node as secondary and updates disk utilisation.
setSec :: Node -> Instance.Instance -> Node
setSec t inst = t { sList = Instance.idx inst:sList t
                  , utilLoad = old_load { T.dskWeight = T.dskWeight old_load +
                                          T.dskWeight (Instance.util inst) }
                  , instSpindles = calcSpindleUse True t inst
                  }
  where old_load = utilLoad t

-- | Computes the new 'pDsk' value, handling nodes without local disk
-- storage (we consider all their disk unused).
computePDsk :: Int -> Double -> Double
computePDsk _    0     = 1
computePDsk free total = fromIntegral free / total

-- | Computes the new 'pDsk' value, handling the exclusive storage state.
computeNewPDsk :: Node -> Int -> Int -> Double
computeNewPDsk node new_free_sp new_free_dsk =
  if exclStorage node
  then computePDsk new_free_sp . fromIntegral $ tSpindles node
  else computePDsk new_free_dsk $ tDsk node

-- * Update functions

-- | Sets the free memory.
setFmem :: Node -> Int -> Node
setFmem t new_mem =
  let new_n1 = new_mem < rMem t
      new_mp = fromIntegral new_mem / tMem t
  in t { fMem = new_mem, failN1 = new_n1, pMem = new_mp }

-- | Removes a primary instance.
removePri :: Node -> Instance.Instance -> Node
removePri t inst =
  let iname = Instance.idx inst
      i_online = Instance.notOffline inst
      uses_disk = Instance.usesLocalStorage inst
      new_plist = delete iname (pList t)
      new_mem = incIf i_online (fMem t) (Instance.mem inst)
      new_dsk = incIf uses_disk (fDsk t) (Instance.dsk inst)
      new_free_sp = calcNewFreeSpindles False t inst
      new_inst_sp = calcSpindleUse False t inst
      new_mp = fromIntegral new_mem / tMem t
      new_dp = computeNewPDsk t new_free_sp new_dsk
      new_failn1 = new_mem <= rMem t
      new_ucpu = decIf i_online (uCpu t) (Instance.vcpus inst)
      new_rcpu = fromIntegral new_ucpu / tCpu t
      new_load = utilLoad t `T.subUtil` Instance.util inst
  in t { pList = new_plist, fMem = new_mem, fDsk = new_dsk
       , failN1 = new_failn1, pMem = new_mp, pDsk = new_dp
       , uCpu = new_ucpu, pCpu = new_rcpu, utilLoad = new_load
       , pTags = delTags (pTags t) (Instance.exclTags inst)
       , instSpindles = new_inst_sp, fSpindles = new_free_sp
       }

-- | Removes a secondary instance.
removeSec :: Node -> Instance.Instance -> Node
removeSec t inst =
  let iname = Instance.idx inst
      uses_disk = Instance.usesLocalStorage inst
      cur_dsk = fDsk t
      pnode = Instance.pNode inst
      new_slist = delete iname (sList t)
      new_dsk = incIf uses_disk cur_dsk (Instance.dsk inst)
      new_free_sp = calcNewFreeSpindles False t inst
      new_inst_sp = calcSpindleUse False t inst
      old_peers = peers t
      old_peem = P.find pnode old_peers
      new_peem = decIf (Instance.usesSecMem inst) old_peem (Instance.mem inst)
      new_peers = if new_peem > 0
                    then P.add pnode new_peem old_peers
                    else P.remove pnode old_peers
      old_rmem = rMem t
      new_rmem = if old_peem < old_rmem
                   then old_rmem
                   else computeMaxRes new_peers
      new_prem = fromIntegral new_rmem / tMem t
      new_failn1 = fMem t <= new_rmem
      new_dp = computeNewPDsk t new_free_sp new_dsk
      old_load = utilLoad t
      new_load = old_load { T.dskWeight = T.dskWeight old_load -
                                          T.dskWeight (Instance.util inst) }
  in t { sList = new_slist, fDsk = new_dsk, peers = new_peers
       , failN1 = new_failn1, rMem = new_rmem, pDsk = new_dp
       , pRem = new_prem, utilLoad = new_load
       , instSpindles = new_inst_sp, fSpindles = new_free_sp
       }

-- | Adds a primary instance (basic version).
addPri :: Node -> Instance.Instance -> T.OpResult Node
addPri = addPriEx False

-- | Adds a primary instance (extended version).
addPriEx :: Bool               -- ^ Whether to override the N+1 and
                               -- other /soft/ checks, useful if we
                               -- come from a worse status
                               -- (e.g. offline)
         -> Node               -- ^ The target node
         -> Instance.Instance  -- ^ The instance to add
         -> T.OpResult Node    -- ^ The result of the operation,
                               -- either the new version of the node
                               -- or a failure mode
addPriEx force t inst =
  let iname = Instance.idx inst
      i_online = Instance.notOffline inst
      uses_disk = Instance.usesLocalStorage inst
      cur_dsk = fDsk t
      new_mem = decIf i_online (fMem t) (Instance.mem inst)
      new_dsk = decIf uses_disk cur_dsk (Instance.dsk inst)
      new_free_sp = calcNewFreeSpindles True t inst
      new_inst_sp = calcSpindleUse True t inst
      new_failn1 = new_mem <= rMem t
      new_ucpu = incIf i_online (uCpu t) (Instance.vcpus inst)
      new_pcpu = fromIntegral new_ucpu / tCpu t
      new_dp = computeNewPDsk t new_free_sp new_dsk
      l_cpu = T.iPolicyVcpuRatio $ iPolicy t
      new_load = utilLoad t `T.addUtil` Instance.util inst
      inst_tags = Instance.exclTags inst
      old_tags = pTags t
      strict = not force
  in case () of
       _ | new_mem <= 0 -> Bad T.FailMem
         | uses_disk && new_dsk <= 0 -> Bad T.FailDisk
         | uses_disk && new_dsk < loDsk t && strict -> Bad T.FailDisk
         | uses_disk && exclStorage t && new_free_sp < 0 -> Bad T.FailSpindles
         | uses_disk && new_inst_sp > hiSpindles t && strict -> Bad T.FailDisk
         | new_failn1 && not (failN1 t) && strict -> Bad T.FailMem
         | l_cpu >= 0 && l_cpu < new_pcpu && strict -> Bad T.FailCPU
         | rejectAddTags old_tags inst_tags -> Bad T.FailTags
         | otherwise ->
           let new_plist = iname:pList t
               new_mp = fromIntegral new_mem / tMem t
               r = t { pList = new_plist, fMem = new_mem, fDsk = new_dsk
                     , failN1 = new_failn1, pMem = new_mp, pDsk = new_dp
                     , uCpu = new_ucpu, pCpu = new_pcpu
                     , utilLoad = new_load
                     , pTags = addTags old_tags inst_tags
                     , instSpindles = new_inst_sp
                     , fSpindles = new_free_sp
                     }
           in Ok r

-- | Adds a secondary instance (basic version).
addSec :: Node -> Instance.Instance -> T.Ndx -> T.OpResult Node
addSec = addSecEx False

-- | Adds a secondary instance (extended version).
addSecEx :: Bool -> Node -> Instance.Instance -> T.Ndx -> T.OpResult Node
addSecEx force t inst pdx =
  let iname = Instance.idx inst
      old_peers = peers t
      old_mem = fMem t
      new_dsk = fDsk t - Instance.dsk inst
      new_free_sp = calcNewFreeSpindles True t inst
      new_inst_sp = calcSpindleUse True t inst
      secondary_needed_mem = if Instance.usesSecMem inst
                               then Instance.mem inst
                               else 0
      new_peem = P.find pdx old_peers + secondary_needed_mem
      new_peers = P.add pdx new_peem old_peers
      new_rmem = max (rMem t) new_peem
      new_prem = fromIntegral new_rmem / tMem t
      new_failn1 = old_mem <= new_rmem
      new_dp = computeNewPDsk t new_free_sp new_dsk
      old_load = utilLoad t
      new_load = old_load { T.dskWeight = T.dskWeight old_load +
                                          T.dskWeight (Instance.util inst) }
      strict = not force
  in case () of
       _ | not (Instance.hasSecondary inst) -> Bad T.FailDisk
         | new_dsk <= 0 -> Bad T.FailDisk
         | new_dsk < loDsk t && strict -> Bad T.FailDisk
         | exclStorage t && new_free_sp < 0 -> Bad T.FailSpindles
         | new_inst_sp > hiSpindles t && strict -> Bad T.FailDisk
         | secondary_needed_mem >= old_mem && strict -> Bad T.FailMem
         | new_failn1 && not (failN1 t) && strict -> Bad T.FailMem
         | otherwise ->
           let new_slist = iname:sList t
               r = t { sList = new_slist, fDsk = new_dsk
                     , peers = new_peers, failN1 = new_failn1
                     , rMem = new_rmem, pDsk = new_dp
                     , pRem = new_prem, utilLoad = new_load
                     , instSpindles = new_inst_sp
                     , fSpindles = new_free_sp
                     }
           in Ok r

-- * Stats functions

-- | Computes the amount of available disk on a given node.
availDisk :: Node -> Int
availDisk t =
  let _f = fDsk t
      _l = loDsk t
  in if _f < _l
       then 0
       else _f - _l

-- | Computes the amount of used disk on a given node.
iDsk :: Node -> Int
iDsk t = truncate (tDsk t) - fDsk t

-- | Computes the amount of available memory on a given node.
availMem :: Node -> Int
availMem t =
  let _f = fMem t
      _l = rMem t
  in if _f < _l
       then 0
       else _f - _l

-- | Computes the amount of available memory on a given node.
availCpu :: Node -> Int
availCpu t =
  let _u = uCpu t
      _l = hiCpu t
  in if _l >= _u
       then _l - _u
       else 0

-- | The memory used by instances on a given node.
iMem :: Node -> Int
iMem t = truncate (tMem t) - nMem t - xMem t - fMem t

-- * Node graph functions
-- These functions do the transformations needed so that nodes can be
-- represented as a graph connected by the instances that are replicated
-- on them.

-- * Making of a Graph from a node/instance list

-- | Transform an instance into a list of edges on the node graph
instanceToEdges :: Instance.Instance -> [Graph.Edge]
instanceToEdges i
  | Instance.hasSecondary i = [(pnode,snode), (snode,pnode)]
  | otherwise = []
    where pnode = Instance.pNode i
          snode = Instance.sNode i

-- | Transform the list of instances into list of destination edges
instancesToEdges :: Instance.List -> [Graph.Edge]
instancesToEdges = concatMap instanceToEdges . Container.elems

-- | Transform the list of nodes into vertices bounds.
-- Returns Nothing is the list is empty.
nodesToBounds :: List -> Maybe Graph.Bounds
nodesToBounds nl = liftM2 (,) nmin nmax
    where nmin = fmap (fst . fst) (IntMap.minViewWithKey nl)
          nmax = fmap (fst . fst) (IntMap.maxViewWithKey nl)

-- | The clique of the primary nodes of the instances with a given secondary.
-- Return the full graph of those nodes that are primary node of at least one
-- instance that has the given node as secondary.
nodeToSharedSecondaryEdge :: Instance.List -> Node -> [Graph.Edge]
nodeToSharedSecondaryEdge il n = (,) <$> primaries <*> primaries
  where primaries = map (Instance.pNode . flip Container.find il) $ sList n


-- | Predicate of an edge having both vertices in a set of nodes.
filterValid :: List -> [Graph.Edge] -> [Graph.Edge]
filterValid nl  =  filter $ \(x,y) -> IntMap.member x nl && IntMap.member y nl

-- | Transform a Node + Instance list into a NodeGraph type.
-- Returns Nothing if the node list is empty.
mkNodeGraph :: List -> Instance.List -> Maybe Graph.Graph
mkNodeGraph nl il =
  liftM (`Graph.buildG` (filterValid nl . instancesToEdges $ il))
  (nodesToBounds nl)

-- | Transform a Nodes + Instances into a NodeGraph with all reboot exclusions.
-- This includes edges between nodes that are the primary nodes of instances
-- that have the same secondary node. Nodes not in the node list will not be
-- part of the graph, but they are still considered for the edges arising from
-- two instances having the same secondary node.
-- Return Nothing if the node list is empty.
mkRebootNodeGraph :: List -> List -> Instance.List -> Maybe Graph.Graph
mkRebootNodeGraph allnodes nl il =
  liftM (`Graph.buildG` filterValid nl edges) (nodesToBounds nl)
  where
    edges = instancesToEdges il `union`
            (Container.elems allnodes >>= nodeToSharedSecondaryEdge il) 

-- * Display functions

-- | Return a field for a given node.
showField :: Node   -- ^ Node which we're querying
          -> String -- ^ Field name
          -> String -- ^ Field value as string
showField t field =
  case field of
    "idx"  -> printf "%4d" $ idx t
    "name" -> alias t
    "fqdn" -> name t
    "status" -> case () of
                  _ | offline t -> "-"
                    | failN1 t -> "*"
                    | otherwise -> " "
    "tmem" -> printf "%5.0f" $ tMem t
    "nmem" -> printf "%5d" $ nMem t
    "xmem" -> printf "%5d" $ xMem t
    "fmem" -> printf "%5d" $ fMem t
    "imem" -> printf "%5d" $ iMem t
    "rmem" -> printf "%5d" $ rMem t
    "amem" -> printf "%5d" $ fMem t - rMem t
    "tdsk" -> printf "%5.0f" $ tDsk t / 1024
    "fdsk" -> printf "%5d" $ fDsk t `div` 1024
    "tcpu" -> printf "%4.0f" $ tCpu t
    "ucpu" -> printf "%4d" $ uCpu t
    "pcnt" -> printf "%3d" $ length (pList t)
    "scnt" -> printf "%3d" $ length (sList t)
    "plist" -> show $ pList t
    "slist" -> show $ sList t
    "pfmem" -> printf "%6.4f" $ pMem t
    "pfdsk" -> printf "%6.4f" $ pDsk t
    "rcpu"  -> printf "%5.2f" $ pCpu t
    "cload" -> printf "%5.3f" uC
    "mload" -> printf "%5.3f" uM
    "dload" -> printf "%5.3f" uD
    "nload" -> printf "%5.3f" uN
    "ptags" -> intercalate "," . map (uncurry (printf "%s=%d")) .
               Map.toList $ pTags t
    "peermap" -> show $ peers t
    "spindle_count" -> show $ tSpindles t
    "hi_spindles" -> show $ hiSpindles t
    "inst_spindles" -> show $ instSpindles t
    _ -> T.unknownField
  where
    T.DynUtil { T.cpuWeight = uC, T.memWeight = uM,
                T.dskWeight = uD, T.netWeight = uN } = utilLoad t

-- | Returns the header and numeric propery of a field.
showHeader :: String -> (String, Bool)
showHeader field =
  case field of
    "idx" -> ("Index", True)
    "name" -> ("Name", False)
    "fqdn" -> ("Name", False)
    "status" -> ("F", False)
    "tmem" -> ("t_mem", True)
    "nmem" -> ("n_mem", True)
    "xmem" -> ("x_mem", True)
    "fmem" -> ("f_mem", True)
    "imem" -> ("i_mem", True)
    "rmem" -> ("r_mem", True)
    "amem" -> ("a_mem", True)
    "tdsk" -> ("t_dsk", True)
    "fdsk" -> ("f_dsk", True)
    "tcpu" -> ("pcpu", True)
    "ucpu" -> ("vcpu", True)
    "pcnt" -> ("pcnt", True)
    "scnt" -> ("scnt", True)
    "plist" -> ("primaries", True)
    "slist" -> ("secondaries", True)
    "pfmem" -> ("p_fmem", True)
    "pfdsk" -> ("p_fdsk", True)
    "rcpu"  -> ("r_cpu", True)
    "cload" -> ("lCpu", True)
    "mload" -> ("lMem", True)
    "dload" -> ("lDsk", True)
    "nload" -> ("lNet", True)
    "ptags" -> ("PrimaryTags", False)
    "peermap" -> ("PeerMap", False)
    "spindle_count" -> ("NodeSpindles", True)
    "hi_spindles" -> ("MaxSpindles", True)
    "inst_spindles" -> ("InstSpindles", True)
    -- TODO: add node fields (group.uuid, group)
    _ -> (T.unknownField, False)

-- | String converter for the node list functionality.
list :: [String] -> Node -> [String]
list fields t = map (showField t) fields

-- | Constant holding the fields we're displaying by default.
defaultFields :: [String]
defaultFields =
  [ "status", "name", "tmem", "nmem", "imem", "xmem", "fmem"
  , "rmem", "tdsk", "fdsk", "tcpu", "ucpu", "pcnt", "scnt"
  , "pfmem", "pfdsk", "rcpu"
  , "cload", "mload", "dload", "nload" ]

{-# ANN computeGroups "HLint: ignore Use alternative" #-}
-- | Split a list of nodes into a list of (node group UUID, list of
-- associated nodes).
computeGroups :: [Node] -> [(T.Gdx, [Node])]
computeGroups nodes =
  let nodes' = sortBy (comparing group) nodes
      nodes'' = groupBy ((==) `on` group) nodes'
  -- use of head here is OK, since groupBy returns non-empty lists; if
  -- you remove groupBy, also remove use of head
  in map (\nl -> (group (head nl), nl)) nodes''

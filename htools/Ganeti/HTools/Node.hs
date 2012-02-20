{-| Module describing a node.

    All updates are functional (copy-based) and return a new node with
    updated value.
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
  ) where

import Data.List hiding (group)
import qualified Data.Map as Map
import qualified Data.Foldable as Foldable
import Data.Ord (comparing)
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.PeerMap as P

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
  , uCpu     :: Int       -- ^ Used VCPU count
  , spindleCount :: Int   -- ^ Node spindles (spindle_count node parameter)
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
  , hiSpindles :: Double  -- ^ Auto-computed from policy spindle_ratio
                          -- and the node spindle count
  , instSpindles :: Double -- ^ Spindles used by instances
  , offline  :: Bool      -- ^ Whether the node should not be used for
                          -- allocations and skipped from score
                          -- computations
  , utilPool :: T.DynUtil -- ^ Total utilisation capacity
  , utilLoad :: T.DynUtil -- ^ Sum of instance utilisation
  , pTags    :: TagMap    -- ^ Map of primary instance tags and their count
  , group    :: T.Gdx     -- ^ The node's group (index)
  , iPolicy  :: T.IPolicy -- ^ The instance policy (of the node's group)
  } deriving (Show, Read, Eq)

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

-- * Initialization functions

-- | Create a new node.
--
-- The index and the peers maps are empty, and will be need to be
-- update later via the 'setIdx' and 'buildPeers' functions.
create :: String -> Double -> Int -> Int -> Double
       -> Int -> Double -> Bool -> Int -> T.Gdx -> Node
create name_init mem_t_init mem_n_init mem_f_init
       dsk_t_init dsk_f_init cpu_t_init offline_init spindles_init
       group_init =
  Node { name = name_init
       , alias = name_init
       , tMem = mem_t_init
       , nMem = mem_n_init
       , fMem = mem_f_init
       , tDsk = dsk_t_init
       , fDsk = dsk_f_init
       , tCpu = cpu_t_init
       , spindleCount = spindles_init
       , uCpu = 0
       , pList = []
       , sList = []
       , failN1 = True
       , idx = -1
       , peers = P.empty
       , rMem = 0
       , pMem = fromIntegral mem_f_init / mem_t_init
       , pDsk = fromIntegral dsk_f_init / dsk_t_init
       , pRem = 0
       , pCpu = 0
       , offline = offline_init
       , xMem = 0
       , mDsk = T.defReservedDiskRatio
       , loDsk = mDskToloDsk T.defReservedDiskRatio dsk_t_init
       , hiCpu = mCpuTohiCpu (T.iPolicyVcpuRatio T.defIPolicy) cpu_t_init
       , hiSpindles = computeHiSpindles (T.iPolicySpindleRatio T.defIPolicy)
                      spindles_init
       , instSpindles = 0
       , utilPool = T.baseUtil
       , utilLoad = T.zeroUtil
       , pTags = Map.empty
       , group = group_init
       , iPolicy = T.defIPolicy
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
                      (spindleCount node)
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

-- | Assigns an instance to a node as primary and update the used VCPU
-- count, utilisation data and tags map.
setPri :: Node -> Instance.Instance -> Node
setPri t inst = t { pList = Instance.idx inst:pList t
                  , uCpu = new_count
                  , pCpu = fromIntegral new_count / tCpu t
                  , utilLoad = utilLoad t `T.addUtil` Instance.util inst
                  , pTags = addTags (pTags t) (Instance.tags inst)
                  }
  where new_count = Instance.applyIfOnline inst (+ Instance.vcpus inst)
                    (uCpu t )

-- | Assigns an instance to a node as secondary without other updates.
setSec :: Node -> Instance.Instance -> Node
setSec t inst = t { sList = Instance.idx inst:sList t
                  , utilLoad = old_load { T.dskWeight = T.dskWeight old_load +
                                          T.dskWeight (Instance.util inst) }
                  }
  where old_load = utilLoad t

-- * Update functions

-- | Sets the free memory.
setFmem :: Node -> Int -> Node
setFmem t new_mem =
  let new_n1 = new_mem <= rMem t
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
      new_mp = fromIntegral new_mem / tMem t
      new_dp = fromIntegral new_dsk / tDsk t
      new_failn1 = new_mem <= rMem t
      new_ucpu = decIf i_online (uCpu t) (Instance.vcpus inst)
      new_rcpu = fromIntegral new_ucpu / tCpu t
      new_load = utilLoad t `T.subUtil` Instance.util inst
  in t { pList = new_plist, fMem = new_mem, fDsk = new_dsk
       , failN1 = new_failn1, pMem = new_mp, pDsk = new_dp
       , uCpu = new_ucpu, pCpu = new_rcpu, utilLoad = new_load
       , pTags = delTags (pTags t) (Instance.tags inst) }

-- | Removes a secondary instance.
removeSec :: Node -> Instance.Instance -> Node
removeSec t inst =
  let iname = Instance.idx inst
      uses_disk = Instance.usesLocalStorage inst
      cur_dsk = fDsk t
      pnode = Instance.pNode inst
      new_slist = delete iname (sList t)
      new_dsk = incIf uses_disk cur_dsk (Instance.dsk inst)
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
      new_dp = fromIntegral new_dsk / tDsk t
      old_load = utilLoad t
      new_load = old_load { T.dskWeight = T.dskWeight old_load -
                                          T.dskWeight (Instance.util inst) }
  in t { sList = new_slist, fDsk = new_dsk, peers = new_peers
       , failN1 = new_failn1, rMem = new_rmem, pDsk = new_dp
       , pRem = new_prem, utilLoad = new_load }

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
      new_failn1 = new_mem <= rMem t
      new_ucpu = incIf i_online (uCpu t) (Instance.vcpus inst)
      new_pcpu = fromIntegral new_ucpu / tCpu t
      new_dp = fromIntegral new_dsk / tDsk t
      l_cpu = T.iPolicyVcpuRatio $ iPolicy t
      new_load = utilLoad t `T.addUtil` Instance.util inst
      inst_tags = Instance.tags inst
      old_tags = pTags t
      strict = not force
  in case () of
       _ | new_mem <= 0 -> T.OpFail T.FailMem
         | uses_disk && new_dsk <= 0 -> T.OpFail T.FailDisk
         | uses_disk && mDsk t > new_dp && strict -> T.OpFail T.FailDisk
         | new_failn1 && not (failN1 t) && strict -> T.OpFail T.FailMem
         | l_cpu >= 0 && l_cpu < new_pcpu && strict -> T.OpFail T.FailCPU
         | rejectAddTags old_tags inst_tags -> T.OpFail T.FailTags
         | otherwise ->
           let new_plist = iname:pList t
               new_mp = fromIntegral new_mem / tMem t
               r = t { pList = new_plist, fMem = new_mem, fDsk = new_dsk
                     , failN1 = new_failn1, pMem = new_mp, pDsk = new_dp
                     , uCpu = new_ucpu, pCpu = new_pcpu
                     , utilLoad = new_load
                     , pTags = addTags old_tags inst_tags }
           in T.OpGood r

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
      secondary_needed_mem = if Instance.usesSecMem inst
                               then Instance.mem inst
                               else 0
      new_peem = P.find pdx old_peers + secondary_needed_mem
      new_peers = P.add pdx new_peem old_peers
      new_rmem = max (rMem t) new_peem
      new_prem = fromIntegral new_rmem / tMem t
      new_failn1 = old_mem <= new_rmem
      new_dp = fromIntegral new_dsk / tDsk t
      old_load = utilLoad t
      new_load = old_load { T.dskWeight = T.dskWeight old_load +
                                          T.dskWeight (Instance.util inst) }
      strict = not force
  in case () of
       _ | not (Instance.hasSecondary inst) -> T.OpFail T.FailDisk
         | new_dsk <= 0 -> T.OpFail T.FailDisk
         | mDsk t > new_dp && strict -> T.OpFail T.FailDisk
         | secondary_needed_mem >= old_mem && strict -> T.OpFail T.FailMem
         | new_failn1 && not (failN1 t) && strict -> T.OpFail T.FailMem
         | otherwise ->
           let new_slist = iname:sList t
               r = t { sList = new_slist, fDsk = new_dsk
                     , peers = new_peers, failN1 = new_failn1
                     , rMem = new_rmem, pDsk = new_dp
                     , pRem = new_prem, utilLoad = new_load }
           in T.OpGood r

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
    "spindle_count" -> show $ spindleCount t
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

-- | Split a list of nodes into a list of (node group UUID, list of
-- associated nodes).
computeGroups :: [Node] -> [(T.Gdx, [Node])]
computeGroups nodes =
  let nodes' = sortBy (comparing group) nodes
      nodes'' = groupBy (\a b -> group a == group b) nodes'
  in map (\nl -> (group (head nl), nl)) nodes''

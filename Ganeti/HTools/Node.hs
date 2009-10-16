{-| Module describing a node.

    All updates are functional (copy-based) and return a new node with
    updated value.
-}

{-

Copyright (C) 2009 Google Inc.

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
    ( Node(failN1, name, idx,
           tMem, nMem, fMem, rMem, xMem,
           tDsk, fDsk,
           tCpu, uCpu,
           pMem, pDsk, pRem, pCpu,
           mDsk, mCpu, loDsk, hiCpu,
           pList, sList, offline)
    , List
    -- * Constructor
    , create
    -- ** Finalization after data loading
    , buildPeers
    , setIdx
    , setName
    , setOffline
    , setXmem
    , setFmem
    , setPri
    , setSec
    , setMdsk
    , setMcpu
    -- * Instance (re)location
    , removePri
    , removeSec
    , addPri
    , addSec
    -- * Stats
    , availDisk
    -- * Formatting
    , list
    -- * Misc stuff
    , AssocList
    , noSecondary
    ) where

import Data.List
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.PeerMap as PeerMap

import qualified Ganeti.HTools.Types as T

-- * Type declarations

-- | The node type.
data Node = Node { name  :: String -- ^ The node name
                 , tMem :: Double  -- ^ Total memory (MiB)
                 , nMem :: Int     -- ^ Node memory (MiB)
                 , fMem :: Int     -- ^ Free memory (MiB)
                 , xMem :: Int     -- ^ Unaccounted memory (MiB)
                 , tDsk :: Double  -- ^ Total disk space (MiB)
                 , fDsk :: Int     -- ^ Free disk space (MiB)
                 , tCpu :: Double  -- ^ Total CPU count
                 , uCpu :: Int     -- ^ Used VCPU count
                 , pList :: [T.Idx]-- ^ List of primary instance indices
                 , sList :: [T.Idx]-- ^ List of secondary instance indices
                 , idx :: T.Ndx    -- ^ Internal index for book-keeping
                 , peers :: PeerMap.PeerMap -- ^ Pnode to instance mapping
                 , failN1:: Bool   -- ^ Whether the node has failed n1
                 , rMem :: Int     -- ^ Maximum memory needed for
                                   -- failover by primaries of this node
                 , pMem :: Double  -- ^ Percent of free memory
                 , pDsk :: Double  -- ^ Percent of free disk
                 , pRem :: Double  -- ^ Percent of reserved memory
                 , pCpu :: Double  -- ^ Ratio of virtual to physical CPUs
                 , mDsk :: Double  -- ^ Minimum free disk ratio
                 , mCpu :: Double  -- ^ Max ratio of virt-to-phys CPUs
                 , loDsk :: Int    -- ^ Autocomputed from mDsk low disk
                                   -- threshold
                 , hiCpu :: Int    -- ^ Autocomputed from mCpu high cpu
                                   -- threshold
                 , offline :: Bool -- ^ Whether the node should not be used
                                   -- for allocations and skipped from
                                   -- score computations
                 , utilPool :: T.DynUtil -- ^ Total utilisation capacity
                 , utilLoad :: T.DynUtil -- ^ Sum of instance utilisation
                 } deriving (Show)

instance T.Element Node where
    nameOf = name
    idxOf = idx
    setName = setName
    setIdx = setIdx

-- | A simple name for the int, node association list.
type AssocList = [(T.Ndx, Node)]

-- | A simple name for a node map.
type List = Container.Container Node

-- | Constant node index for a non-moveable instance.
noSecondary :: T.Ndx
noSecondary = -1

-- | No limit value
noLimit :: Double
noLimit = -1

-- | No limit int value
noLimitInt :: Int
noLimitInt = -1

-- * Initialization functions

-- | Create a new node.
--
-- The index and the peers maps are empty, and will be need to be
-- update later via the 'setIdx' and 'buildPeers' functions.
create :: String -> Double -> Int -> Int -> Double
       -> Int -> Double -> Bool -> Node
create name_init mem_t_init mem_n_init mem_f_init
       dsk_t_init dsk_f_init cpu_t_init offline_init =
    Node { name  = name_init
         , tMem = mem_t_init
         , nMem = mem_n_init
         , fMem = mem_f_init
         , tDsk = dsk_t_init
         , fDsk = dsk_f_init
         , tCpu = cpu_t_init
         , uCpu = 0
         , pList = []
         , sList = []
         , failN1 = True
         , idx = -1
         , peers = PeerMap.empty
         , rMem = 0
         , pMem = fromIntegral mem_f_init / mem_t_init
         , pDsk = fromIntegral dsk_f_init / dsk_t_init
         , pRem = 0
         , pCpu = 0
         , offline = offline_init
         , xMem = 0
         , mDsk = noLimit
         , mCpu = noLimit
         , loDsk = noLimitInt
         , hiCpu = noLimitInt
         , utilPool = T.zeroUtil
         , utilLoad = T.zeroUtil
         }

-- | Changes the index.
--
-- This is used only during the building of the data structures.
setIdx :: Node -> T.Ndx -> Node
setIdx t i = t {idx = i}

-- | Changes the name.
--
-- This is used only during the building of the data structures.
setName :: Node -> String -> Node
setName t s = t {name = s}

-- | Sets the offline attribute.
setOffline :: Node -> Bool -> Node
setOffline t val = t { offline = val }

-- | Sets the unnaccounted memory.
setXmem :: Node -> Int -> Node
setXmem t val = t { xMem = val }

-- | Sets the max disk usage ratio
setMdsk :: Node -> Double -> Node
setMdsk t val = t { mDsk = val,
                    loDsk = if val == noLimit
                             then noLimitInt
                             else floor (val * tDsk t) }

-- | Sets the max cpu usage ratio
setMcpu :: Node -> Double -> Node
setMcpu t val = t { mCpu = val, hiCpu = floor (val * tCpu t) }

-- | Computes the maximum reserved memory for peers from a peer map.
computeMaxRes :: PeerMap.PeerMap -> PeerMap.Elem
computeMaxRes = PeerMap.maxElem

-- | Builds the peer map for a given node.
buildPeers :: Node -> Instance.List -> Node
buildPeers t il =
    let mdata = map
                (\i_idx -> let inst = Container.find i_idx il
                           in (Instance.pNode inst, Instance.mem inst))
                (sList t)
        pmap = PeerMap.accumArray (+) mdata
        new_rmem = computeMaxRes pmap
        new_failN1 = fMem t <= new_rmem
        new_prem = fromIntegral new_rmem / tMem t
    in t {peers=pmap, failN1 = new_failN1, rMem = new_rmem, pRem = new_prem}

-- | Assigns an instance to a node as primary and update the used VCPU
-- count.
setPri :: Node -> Instance.Instance -> Node
setPri t inst = t { pList = (Instance.idx inst):pList t
                  , uCpu = new_count
                  , pCpu = fromIntegral new_count / tCpu t }
    where new_count = uCpu t + Instance.vcpus inst

-- | Assigns an instance to a node as secondary without other updates.
setSec :: Node -> Instance.Instance -> Node
setSec t inst = t { sList = (Instance.idx inst):sList t }

-- * Update functions

-- | Sets the free memory.
setFmem :: Node -> Int -> Node
setFmem t new_mem =
    let new_n1 = new_mem <= rMem t
        new_mp = fromIntegral new_mem / tMem t
    in
      t { fMem = new_mem, failN1 = new_n1, pMem = new_mp }

-- | Removes a primary instance.
removePri :: Node -> Instance.Instance -> Node
removePri t inst =
    let iname = Instance.idx inst
        new_plist = delete iname (pList t)
        new_mem = fMem t + Instance.mem inst
        new_dsk = fDsk t + Instance.dsk inst
        new_mp = fromIntegral new_mem / tMem t
        new_dp = fromIntegral new_dsk / tDsk t
        new_failn1 = new_mem <= rMem t
        new_ucpu = uCpu t - Instance.vcpus inst
        new_rcpu = fromIntegral new_ucpu / tCpu t
    in t {pList = new_plist, fMem = new_mem, fDsk = new_dsk,
          failN1 = new_failn1, pMem = new_mp, pDsk = new_dp,
          uCpu = new_ucpu, pCpu = new_rcpu}

-- | Removes a secondary instance.
removeSec :: Node -> Instance.Instance -> Node
removeSec t inst =
    let iname = Instance.idx inst
        pnode = Instance.pNode inst
        new_slist = delete iname (sList t)
        new_dsk = fDsk t + Instance.dsk inst
        old_peers = peers t
        old_peem = PeerMap.find pnode old_peers
        new_peem =  old_peem - Instance.mem inst
        new_peers = PeerMap.add pnode new_peem old_peers
        old_rmem = rMem t
        new_rmem = if old_peem < old_rmem then
                       old_rmem
                   else
                       computeMaxRes new_peers
        new_prem = fromIntegral new_rmem / tMem t
        new_failn1 = fMem t <= new_rmem
        new_dp = fromIntegral new_dsk / tDsk t
    in t {sList = new_slist, fDsk = new_dsk, peers = new_peers,
          failN1 = new_failn1, rMem = new_rmem, pDsk = new_dp,
          pRem = new_prem}

-- | Adds a primary instance.
addPri :: Node -> Instance.Instance -> T.OpResult Node
addPri t inst =
    let iname = Instance.idx inst
        new_mem = fMem t - Instance.mem inst
        new_dsk = fDsk t - Instance.dsk inst
        new_failn1 = new_mem <= rMem t
        new_ucpu = uCpu t + Instance.vcpus inst
        new_pcpu = fromIntegral new_ucpu / tCpu t
        new_dp = fromIntegral new_dsk / tDsk t
        l_cpu = mCpu t
    in if new_mem <= 0 then T.OpFail T.FailMem
       else if new_dsk <= 0 || mDsk t > new_dp then T.OpFail T.FailDisk
       else if new_failn1 && not (failN1 t) then T.OpFail T.FailMem
       else if l_cpu >= 0 && l_cpu < new_pcpu then T.OpFail T.FailCPU
       else
           let new_plist = iname:pList t
               new_mp = fromIntegral new_mem / tMem t
               r = t { pList = new_plist, fMem = new_mem, fDsk = new_dsk,
                       failN1 = new_failn1, pMem = new_mp, pDsk = new_dp,
                       uCpu = new_ucpu, pCpu = new_pcpu }
           in T.OpGood r

-- | Adds a secondary instance.
addSec :: Node -> Instance.Instance -> T.Ndx -> T.OpResult Node
addSec t inst pdx =
    let iname = Instance.idx inst
        old_peers = peers t
        old_mem = fMem t
        new_dsk = fDsk t - Instance.dsk inst
        new_peem = PeerMap.find pdx old_peers + Instance.mem inst
        new_peers = PeerMap.add pdx new_peem old_peers
        new_rmem = max (rMem t) new_peem
        new_prem = fromIntegral new_rmem / tMem t
        new_failn1 = old_mem <= new_rmem
        new_dp = fromIntegral new_dsk / tDsk t
    in if new_dsk <= 0 || mDsk t > new_dp then T.OpFail T.FailDisk
       else if new_failn1 && not (failN1 t) then T.OpFail T.FailMem
       else let new_slist = iname:sList t
                r = t { sList = new_slist, fDsk = new_dsk,
                        peers = new_peers, failN1 = new_failn1,
                        rMem = new_rmem, pDsk = new_dp,
                        pRem = new_prem }
           in T.OpGood r

-- * Stats functions

-- | Computes the amount of available disk on a given node
availDisk :: Node -> Int
availDisk t =
    let _f = fDsk t
        _l = loDsk t
    in
      if _l == noLimitInt
      then _f
      else if _f < _l
           then 0
           else _f - _l

-- * Display functions

-- | String converter for the node list functionality.
list :: Int -> Node -> String
list mname t =
    let pl = length $ pList t
        sl = length $ sList t
        mp = pMem t
        dp = pDsk t
        cp = pCpu t
        off = offline t
        fn = failN1 t
        tmem = tMem t
        nmem = nMem t
        xmem = xMem t
        fmem = fMem t
        imem = truncate tmem - nmem - xmem - fmem
        T.DynUtil { T.cpuWeight = uC, T.memWeight = uM,
                    T.dskWeight = uD, T.netWeight = uN } = utilLoad t
        wstr = printf " %5.3f %5.3f %5.3f %5.3f" uC uM uD uN::String
    in
      if off
         then printf " - %-*s %57s %3d %3d"
              mname (name t) "" pl sl
         else
             printf " %c %-*s %5.0f %5d %5d %5d %5d %5d %5.0f %5d\
                    \ %4.0f %4d %3d %3d %6.4f %6.4f %5.2f"
                 (if off then '-' else if fn then '*' else ' ')
                 mname (name t) tmem nmem imem xmem fmem (rMem t)
                 (tDsk t / 1024) (fDsk t `div` 1024)
                 (tCpu t) (uCpu t)
                 pl sl mp dp cp ++ wstr

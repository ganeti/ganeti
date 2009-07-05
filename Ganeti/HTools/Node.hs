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
    ( Node(failN1, name, idx, t_mem, n_mem, f_mem, r_mem,
           t_dsk, f_dsk,
           t_cpu, u_cpu,
           p_mem, p_dsk, p_rem, p_cpu,
           m_dsk, m_cpu, lo_dsk, hi_cpu,
           plist, slist, offline)
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
    , addCpus
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
                 , t_mem :: Double -- ^ Total memory (MiB)
                 , n_mem :: Int    -- ^ Node memory (MiB)
                 , f_mem :: Int    -- ^ Free memory (MiB)
                 , x_mem :: Int    -- ^ Unaccounted memory (MiB)
                 , t_dsk :: Double -- ^ Total disk space (MiB)
                 , f_dsk :: Int    -- ^ Free disk space (MiB)
                 , t_cpu :: Double -- ^ Total CPU count
                 , u_cpu :: Int    -- ^ Used VCPU count
                 , plist :: [T.Idx]-- ^ List of primary instance indices
                 , slist :: [T.Idx]-- ^ List of secondary instance indices
                 , idx :: T.Ndx    -- ^ Internal index for book-keeping
                 , peers :: PeerMap.PeerMap -- ^ Pnode to instance mapping
                 , failN1:: Bool   -- ^ Whether the node has failed n1
                 , r_mem :: Int    -- ^ Maximum memory needed for
                                   -- failover by primaries of this node
                 , p_mem :: Double -- ^ Percent of free memory
                 , p_dsk :: Double -- ^ Percent of free disk
                 , p_rem :: Double -- ^ Percent of reserved memory
                 , p_cpu :: Double -- ^ Ratio of virtual to physical CPUs
                 , m_dsk :: Double -- ^ Minimum free disk ratio
                 , m_cpu :: Double -- ^ Max ratio of virt-to-phys CPUs
                 , lo_dsk :: Int   -- ^ Autocomputed from m_dsk low disk
                                   -- threshold
                 , hi_cpu :: Int   -- ^ Autocomputed from m_cpu high cpu
                                   -- threshold
                 , offline :: Bool -- ^ Whether the node should not be used
                                   -- for allocations and skipped from
                                   -- score computations
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
    Node
    {
      name  = name_init,
      t_mem = mem_t_init,
      n_mem = mem_n_init,
      f_mem = mem_f_init,
      t_dsk = dsk_t_init,
      f_dsk = dsk_f_init,
      t_cpu = cpu_t_init,
      u_cpu = 0,
      plist = [],
      slist = [],
      failN1 = True,
      idx = -1,
      peers = PeerMap.empty,
      r_mem = 0,
      p_mem = (fromIntegral mem_f_init) / mem_t_init,
      p_dsk = (fromIntegral dsk_f_init) / dsk_t_init,
      p_rem = 0,
      p_cpu = 0,
      offline = offline_init,
      x_mem = 0,
      m_dsk = noLimit,
      m_cpu = noLimit,
      lo_dsk = noLimitInt,
      hi_cpu = noLimitInt
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
setXmem t val = t { x_mem = val }

-- | Sets the max disk usage ratio
setMdsk :: Node -> Double -> Node
setMdsk t val = t { m_dsk = val,
                    lo_dsk = if val == noLimit
                             then noLimitInt
                             else floor (val * (t_dsk t)) }

-- | Sets the max cpu usage ratio
setMcpu :: Node -> Double -> Node
setMcpu t val = t { m_cpu = val, hi_cpu = floor (val * (t_cpu t)) }

-- | Computes the maximum reserved memory for peers from a peer map.
computeMaxRes :: PeerMap.PeerMap -> PeerMap.Elem
computeMaxRes new_peers = PeerMap.maxElem new_peers

-- | Builds the peer map for a given node.
buildPeers :: Node -> Instance.List -> Node
buildPeers t il =
    let mdata = map
                (\i_idx -> let inst = Container.find i_idx il
                           in (Instance.pnode inst, Instance.mem inst))
                (slist t)
        pmap = PeerMap.accumArray (+) mdata
        new_rmem = computeMaxRes pmap
        new_failN1 = (f_mem t) <= new_rmem
        new_prem = (fromIntegral new_rmem) / (t_mem t)
    in t {peers=pmap, failN1 = new_failN1, r_mem = new_rmem, p_rem = new_prem}

-- | Assigns an instance to a node as primary without other updates.
setPri :: Node -> T.Idx -> Node
setPri t idx = t { plist = idx:(plist t) }

-- | Assigns an instance to a node as secondary without other updates.
setSec :: Node -> T.Idx -> Node
setSec t idx = t { slist = idx:(slist t) }

-- | Add primary cpus to a node
addCpus :: Node -> Int -> Node
addCpus t count =
    let new_count = (u_cpu t) + count
    in t { u_cpu = new_count, p_cpu = (fromIntegral new_count) / (t_cpu t) }

-- * Update functions

-- | Sets the free memory.
setFmem :: Node -> Int -> Node
setFmem t new_mem =
    let new_n1 = new_mem <= (r_mem t)
        new_mp = (fromIntegral new_mem) / (t_mem t)
    in
      t { f_mem = new_mem, failN1 = new_n1, p_mem = new_mp }

-- | Removes a primary instance.
removePri :: Node -> Instance.Instance -> Node
removePri t inst =
    let iname = Instance.idx inst
        new_plist = delete iname (plist t)
        new_mem = f_mem t + Instance.mem inst
        new_dsk = f_dsk t + Instance.dsk inst
        new_mp = (fromIntegral new_mem) / (t_mem t)
        new_dp = (fromIntegral new_dsk) / (t_dsk t)
        new_failn1 = new_mem <= (r_mem t)
        new_ucpu = (u_cpu t) - (Instance.vcpus inst)
        new_rcpu = (fromIntegral new_ucpu) / (t_cpu t)
    in t {plist = new_plist, f_mem = new_mem, f_dsk = new_dsk,
          failN1 = new_failn1, p_mem = new_mp, p_dsk = new_dp,
          u_cpu = new_ucpu, p_cpu = new_rcpu}

-- | Removes a secondary instance.
removeSec :: Node -> Instance.Instance -> Node
removeSec t inst =
    let iname = Instance.idx inst
        pnode = Instance.pnode inst
        new_slist = delete iname (slist t)
        new_dsk = f_dsk t + Instance.dsk inst
        old_peers = peers t
        old_peem = PeerMap.find pnode old_peers
        new_peem =  old_peem - (Instance.mem inst)
        new_peers = PeerMap.add pnode new_peem old_peers
        old_rmem = r_mem t
        new_rmem = if old_peem < old_rmem then
                       old_rmem
                   else
                       computeMaxRes new_peers
        new_prem = (fromIntegral new_rmem) / (t_mem t)
        new_failn1 = (f_mem t) <= new_rmem
        new_dp = (fromIntegral new_dsk) / (t_dsk t)
    in t {slist = new_slist, f_dsk = new_dsk, peers = new_peers,
          failN1 = new_failn1, r_mem = new_rmem, p_dsk = new_dp,
          p_rem = new_prem}

-- | Adds a primary instance.
addPri :: Node -> Instance.Instance -> T.OpResult Node
addPri t inst =
    let iname = Instance.idx inst
        new_mem = f_mem t - Instance.mem inst
        new_dsk = f_dsk t - Instance.dsk inst
        new_failn1 = new_mem <= (r_mem t)
        new_ucpu = (u_cpu t) + (Instance.vcpus inst)
        new_pcpu = (fromIntegral new_ucpu) / (t_cpu t)
        new_dp = (fromIntegral new_dsk) / (t_dsk t)
        l_cpu = m_cpu t
    in if new_mem <= 0 then T.OpFail T.FailMem
       else if new_dsk <= 0 || m_dsk t > new_dp then T.OpFail T.FailDisk
       else if (new_failn1 && not (failN1 t)) then T.OpFail T.FailMem
       else if l_cpu >= 0 && l_cpu < new_pcpu then T.OpFail T.FailCPU
       else
           let new_plist = iname:(plist t)
               new_mp = (fromIntegral new_mem) / (t_mem t)
               r = t { plist = new_plist, f_mem = new_mem, f_dsk = new_dsk,
                       failN1 = new_failn1, p_mem = new_mp, p_dsk = new_dp,
                       u_cpu = new_ucpu, p_cpu = new_pcpu }
           in T.OpGood r

-- | Adds a secondary instance.
addSec :: Node -> Instance.Instance -> T.Ndx -> T.OpResult Node
addSec t inst pdx =
    let iname = Instance.idx inst
        old_peers = peers t
        old_mem = f_mem t
        new_dsk = f_dsk t - Instance.dsk inst
        new_peem = PeerMap.find pdx old_peers + Instance.mem inst
        new_peers = PeerMap.add pdx new_peem old_peers
        new_rmem = max (r_mem t) new_peem
        new_prem = (fromIntegral new_rmem) / (t_mem t)
        new_failn1 = old_mem <= new_rmem
        new_dp = (fromIntegral new_dsk) / (t_dsk t)
    in if new_dsk <= 0 || m_dsk t > new_dp then T.OpFail T.FailDisk
       else if (new_failn1 && not (failN1 t)) then T.OpFail T.FailMem
       else let new_slist = iname:(slist t)
                r = t { slist = new_slist, f_dsk = new_dsk,
                        peers = new_peers, failN1 = new_failn1,
                        r_mem = new_rmem, p_dsk = new_dp,
                        p_rem = new_prem }
           in T.OpGood r

-- * Stats functions

-- | Computes the amount of available disk on a given node
availDisk :: Node -> Int
availDisk t =
    let _f = f_dsk t
        _l = lo_dsk t
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
    let pl = length $ plist t
        sl = length $ slist t
        mp = p_mem t
        dp = p_dsk t
        cp = p_cpu t
        off = offline t
        fn = failN1 t
        tmem = t_mem t
        nmem = n_mem t
        xmem = x_mem t
        fmem = f_mem t
        imem = (truncate tmem) - nmem - xmem - fmem
    in
      if off
         then printf " - %-*s %57s %3d %3d"
              mname (name t) "" pl sl
         else
             printf " %c %-*s %5.0f %5d %5d %5d %5d %5d %5.0f %5d\
                    \ %4.0f %4d %3d %3d %6.4f %6.4f %5.2f"
                 (if off then '-' else if fn then '*' else ' ')
                 mname (name t) tmem nmem imem xmem fmem (r_mem t)
                 ((t_dsk t) / 1024) ((f_dsk t) `div` 1024)
                 (t_cpu t) (u_cpu t)
                 pl sl mp dp cp

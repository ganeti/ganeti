{-| Module describing a node.

    All updates are functional (copy-based) and return a new node with
    updated value.
-}

module Ganeti.HTools.Node
    (
      Node(failN1, idx, t_mem, n_mem, f_mem, t_dsk, f_dsk,
           p_mem, p_dsk, p_rem,
           plist, slist, offline)
    -- * Constructor
    , create
    -- ** Finalization after data loading
    , buildPeers
    , setIdx
    , setOffline
    -- * Instance (re)location
    , removePri
    , removeSec
    , addPri
    , addSec
    , setPri
    , setSec
    -- * Formatting
    , list
    ) where

import Data.List
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.PeerMap as PeerMap

import Ganeti.HTools.Utils

data Node = Node { t_mem :: Double -- ^ total memory (MiB)
                 , n_mem :: Int    -- ^ node memory (MiB)
                 , f_mem :: Int    -- ^ free memory (MiB)
                 , t_dsk :: Double -- ^ total disk space (MiB)
                 , f_dsk :: Int    -- ^ free disk space (MiB)
                 , plist :: [Int]  -- ^ list of primary instance indices
                 , slist :: [Int]  -- ^ list of secondary instance indices
                 , idx :: Int      -- ^ internal index for book-keeping
                 , peers :: PeerMap.PeerMap -- ^ pnode to instance mapping
                 , failN1:: Bool   -- ^ whether the node has failed n1
                 , r_mem :: Int    -- ^ maximum memory needed for
                                   -- failover by primaries of this node
                 , p_mem :: Double -- ^ percent of free memory
                 , p_dsk :: Double -- ^ percent of free disk
                 , p_rem :: Double -- ^ percent of reserved memory
                 , offline :: Bool -- ^ whether the node should not be used
                                   -- for allocations and skipped from
                                   -- score computations
  } deriving (Show)

{- | Create a new node.

The index and the peers maps are empty, and will be need to be update
later via the 'setIdx' and 'buildPeers' functions.

-}
create :: Double -> Int -> Int -> Double -> Int -> Node
create mem_t_init mem_n_init mem_f_init dsk_t_init dsk_f_init =
    Node
    {
      t_mem = mem_t_init,
      n_mem = mem_n_init,
      f_mem = mem_f_init,
      t_dsk = dsk_t_init,
      f_dsk = dsk_f_init,
      plist = [],
      slist = [],
      failN1 = True,
      idx = -1,
      peers = PeerMap.empty,
      r_mem = 0,
      p_mem = (fromIntegral mem_f_init) / mem_t_init,
      p_dsk = (fromIntegral dsk_f_init) / dsk_t_init,
      p_rem = 0,
      offline = False
    }

-- | Changes the index.
-- This is used only during the building of the data structures.
setIdx :: Node -> Int -> Node
setIdx t i = t {idx = i}

-- | Sets the offline attribute
setOffline :: Node -> Bool -> Node
setOffline t val = t { offline = val }

-- | Given the rmem, free memory and disk, computes the failn1 status.
computeFailN1 :: Int -> Int -> Int -> Bool
computeFailN1 new_rmem new_mem new_dsk =
    new_mem <= new_rmem || new_dsk <= 0

-- | Given the new free memory and disk, fail if any of them is below zero.
failHealth :: Int -> Int -> Bool
failHealth new_mem new_dsk = new_mem <= 0 || new_dsk <= 0

-- | Computes the maximum reserved memory for peers from a peer map.
computeMaxRes :: PeerMap.PeerMap -> PeerMap.Elem
computeMaxRes new_peers = PeerMap.maxElem new_peers

-- | Builds the peer map for a given node.
buildPeers :: Node -> Container.Container Instance.Instance -> Int -> Node
buildPeers t il num_nodes =
    let mdata = map
                (\i_idx -> let inst = Container.find i_idx il
                           in (Instance.pnode inst, Instance.mem inst))
                (slist t)
        pmap = PeerMap.accumArray (+) 0 (0, num_nodes - 1) mdata
        new_rmem = computeMaxRes pmap
        new_failN1 = computeFailN1 new_rmem (f_mem t) (f_dsk t)
        new_prem = (fromIntegral new_rmem) / (t_mem t)
    in t {peers=pmap, failN1 = new_failN1, r_mem = new_rmem, p_rem = new_prem}

-- | Removes a primary instance.
removePri :: Node -> Instance.Instance -> Node
removePri t inst =
    let iname = Instance.idx inst
        new_plist = delete iname (plist t)
        new_mem = f_mem t + Instance.mem inst
        new_dsk = f_dsk t + Instance.dsk inst
        new_mp = (fromIntegral new_mem) / (t_mem t)
        new_dp = (fromIntegral new_dsk) / (t_dsk t)
        new_failn1 = computeFailN1 (r_mem t) new_mem new_dsk
    in t {plist = new_plist, f_mem = new_mem, f_dsk = new_dsk,
          failN1 = new_failn1, p_mem = new_mp, p_dsk = new_dp}

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
        new_failn1 = computeFailN1 new_rmem (f_mem t) new_dsk
        new_dp = (fromIntegral new_dsk) / (t_dsk t)
    in t {slist = new_slist, f_dsk = new_dsk, peers = new_peers,
          failN1 = new_failn1, r_mem = new_rmem, p_dsk = new_dp,
          p_rem = new_prem}

-- | Adds a primary instance.
addPri :: Node -> Instance.Instance -> Maybe Node
addPri t inst =
    let iname = Instance.idx inst
        new_mem = f_mem t - Instance.mem inst
        new_dsk = f_dsk t - Instance.dsk inst
        new_failn1 = computeFailN1 (r_mem t) new_mem new_dsk in
      if (failHealth new_mem new_dsk) || (new_failn1 && not (failN1 t)) then
        Nothing
      else
        let new_plist = iname:(plist t)
            new_mp = (fromIntegral new_mem) / (t_mem t)
            new_dp = (fromIntegral new_dsk) / (t_dsk t)
        in
        Just t {plist = new_plist, f_mem = new_mem, f_dsk = new_dsk,
                failN1 = new_failn1, p_mem = new_mp, p_dsk = new_dp}

-- | Adds a secondary instance.
addSec :: Node -> Instance.Instance -> Int -> Maybe Node
addSec t inst pdx =
    let iname = Instance.idx inst
        old_peers = peers t
        old_mem = f_mem t
        new_dsk = f_dsk t - Instance.dsk inst
        new_peem = PeerMap.find pdx old_peers + Instance.mem inst
        new_peers = PeerMap.add pdx new_peem old_peers
        new_rmem = max (r_mem t) new_peem
        new_prem = (fromIntegral new_rmem) / (t_mem t)
        new_failn1 = computeFailN1 new_rmem old_mem new_dsk in
    if (failHealth old_mem new_dsk) || (new_failn1 && not (failN1 t)) then
        Nothing
    else
        let new_slist = iname:(slist t)
            new_dp = (fromIntegral new_dsk) / (t_dsk t)
        in
        Just t {slist = new_slist, f_dsk = new_dsk,
                peers = new_peers, failN1 = new_failn1,
                r_mem = new_rmem, p_dsk = new_dp,
                p_rem = new_prem}

-- | Add a primary instance to a node without other updates
setPri :: Node -> Int -> Node
setPri t idx = t { plist = idx:(plist t) }

-- | Add a secondary instance to a node without other updates
setSec :: Node -> Int -> Node
setSec t idx = t { slist = idx:(slist t) }

-- | Simple converter to string.
str :: Node -> String
str t =
    printf ("Node %d (mem=%5d MiB, disk=%5.2f GiB)\n  Primaries:" ++
            " %s\nSecondaries: %s")
      (idx t) (f_mem t) ((f_dsk t) `div` 1024)
      (commaJoin (map show (plist t)))
      (commaJoin (map show (slist t)))

-- | String converter for the node list functionality.
list :: Int -> String -> Node -> String
list mname n t =
    let pl = plist t
        sl = slist t
        mp = p_mem t
        dp = p_dsk t
        off = offline t
        fn = failN1 t
    in
      printf " %c %-*s %5.0f %5d %5d %5d %5.0f %5d %3d %3d %.5f %.5f"
                 (if off then '-' else if fn then '*' else ' ')
                 mname n (t_mem t) (n_mem t) (f_mem t) (r_mem t)
                 ((t_dsk t) / 1024) ((f_dsk t) `div` 1024)
                 (length pl) (length sl)
                 mp dp

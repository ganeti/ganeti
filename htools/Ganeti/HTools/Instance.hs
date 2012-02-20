{-| Module describing an instance.

The instance data type holds very few fields, the algorithm
intelligence is in the "Node" and "Cluster" modules.

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

module Ganeti.HTools.Instance
  ( Instance(..)
  , AssocList
  , List
  , create
  , isRunning
  , isOffline
  , notOffline
  , instanceDown
  , usesSecMem
  , applyIfOnline
  , setIdx
  , setName
  , setAlias
  , setPri
  , setSec
  , setBoth
  , setMovable
  , specOf
  , instBelowISpec
  , instAboveISpec
  , instMatchesPolicy
  , shrinkByType
  , localStorageTemplates
  , hasSecondary
  , requiredNodes
  , allNodes
  , usesLocalStorage
  ) where

import qualified Ganeti.HTools.Types as T
import qualified Ganeti.HTools.Container as Container

import Ganeti.HTools.Utils

-- * Type declarations

-- | The instance type.
data Instance = Instance
  { name         :: String    -- ^ The instance name
  , alias        :: String    -- ^ The shortened name
  , mem          :: Int       -- ^ Memory of the instance
  , dsk          :: Int       -- ^ Disk size of instance
  , vcpus        :: Int       -- ^ Number of VCPUs
  , runSt        :: T.InstanceStatus -- ^ Original run status
  , pNode        :: T.Ndx     -- ^ Original primary node
  , sNode        :: T.Ndx     -- ^ Original secondary node
  , idx          :: T.Idx     -- ^ Internal index
  , util         :: T.DynUtil -- ^ Dynamic resource usage
  , movable      :: Bool      -- ^ Can and should the instance be moved?
  , autoBalance  :: Bool      -- ^ Is the instance auto-balanced?
  , tags         :: [String]  -- ^ List of instance tags
  , diskTemplate :: T.DiskTemplate -- ^ The disk template of the instance
  } deriving (Show, Read, Eq)

instance T.Element Instance where
  nameOf   = name
  idxOf    = idx
  setAlias = setAlias
  setIdx   = setIdx
  allNames n = [name n, alias n]

-- | Check if instance is running.
isRunning :: Instance -> Bool
isRunning (Instance {runSt = T.Running}) = True
isRunning (Instance {runSt = T.ErrorUp}) = True
isRunning _                              = False

-- | Check if instance is offline.
isOffline :: Instance -> Bool
isOffline (Instance {runSt = T.AdminOffline}) = True
isOffline _                                   = False


-- | Helper to check if the instance is not offline.
notOffline :: Instance -> Bool
notOffline = not . isOffline

-- | Check if instance is down.
instanceDown :: Instance -> Bool
instanceDown inst | isRunning inst = False
instanceDown inst | isOffline inst = False
instanceDown _                     = True

-- | Apply the function if the instance is online. Otherwise use
-- the initial value
applyIfOnline :: Instance -> (a -> a) -> a -> a
applyIfOnline = applyIf . notOffline

-- | Helper for determining whether an instance's memory needs to be
-- taken into account for secondary memory reservation.
usesSecMem :: Instance -> Bool
usesSecMem inst = notOffline inst && autoBalance inst

-- | Constant holding the local storage templates.
--
-- /Note:/ Currently Ganeti only exports node total/free disk space
-- for LVM-based storage; file-based storage is ignored in this model,
-- so even though file-based storage uses in reality disk space on the
-- node, in our model it won't affect it and we can't compute whether
-- there is enough disk space for a file-based instance. Therefore we
-- will treat this template as \'foreign\' storage.
localStorageTemplates :: [T.DiskTemplate]
localStorageTemplates = [ T.DTDrbd8, T.DTPlain ]

-- | Constant holding the movable disk templates.
--
-- This only determines the initial 'movable' state of the
-- instance. Further the movable state can be restricted more due to
-- user choices, etc.
movableDiskTemplates :: [T.DiskTemplate]
movableDiskTemplates = [ T.DTDrbd8, T.DTBlock, T.DTSharedFile ]

-- | A simple name for the int, instance association list.
type AssocList = [(T.Idx, Instance)]

-- | A simple name for an instance map.
type List = Container.Container Instance

-- * Initialization

-- | Create an instance.
--
-- Some parameters are not initialized by function, and must be set
-- later (via 'setIdx' for example).
create :: String -> Int -> Int -> Int -> T.InstanceStatus
       -> [String] -> Bool -> T.Ndx -> T.Ndx -> T.DiskTemplate -> Instance
create name_init mem_init dsk_init vcpus_init run_init tags_init
       auto_balance_init pn sn dt =
  Instance { name = name_init
           , alias = name_init
           , mem = mem_init
           , dsk = dsk_init
           , vcpus = vcpus_init
           , runSt = run_init
           , pNode = pn
           , sNode = sn
           , idx = -1
           , util = T.baseUtil
           , tags = tags_init
           , movable = supportsMoves dt
           , autoBalance = auto_balance_init
           , diskTemplate = dt
           }

-- | Changes the index.
--
-- This is used only during the building of the data structures.
setIdx :: Instance -- ^ The original instance
       -> T.Idx    -- ^ New index
       -> Instance -- ^ The modified instance
setIdx t i = t { idx = i }

-- | Changes the name.
--
-- This is used only during the building of the data structures.
setName :: Instance -- ^ The original instance
        -> String   -- ^ New name
        -> Instance -- ^ The modified instance
setName t s = t { name = s, alias = s }

-- | Changes the alias.
--
-- This is used only during the building of the data structures.
setAlias :: Instance -- ^ The original instance
         -> String   -- ^ New alias
         -> Instance -- ^ The modified instance
setAlias t s = t { alias = s }

-- * Update functions

-- | Changes the primary node of the instance.
setPri :: Instance  -- ^ the original instance
        -> T.Ndx    -- ^ the new primary node
        -> Instance -- ^ the modified instance
setPri t p = t { pNode = p }

-- | Changes the secondary node of the instance.
setSec :: Instance  -- ^ the original instance
        -> T.Ndx    -- ^ the new secondary node
        -> Instance -- ^ the modified instance
setSec t s = t { sNode = s }

-- | Changes both nodes of the instance.
setBoth :: Instance  -- ^ the original instance
         -> T.Ndx    -- ^ new primary node index
         -> T.Ndx    -- ^ new secondary node index
         -> Instance -- ^ the modified instance
setBoth t p s = t { pNode = p, sNode = s }

-- | Sets the movable flag on an instance.
setMovable :: Instance -- ^ The original instance
           -> Bool     -- ^ New movable flag
           -> Instance -- ^ The modified instance
setMovable t m = t { movable = m }

-- | Try to shrink the instance based on the reason why we can't
-- allocate it.
shrinkByType :: Instance -> T.FailMode -> T.Result Instance
shrinkByType inst T.FailMem = let v = mem inst - T.unitMem
                              in if v < T.unitMem
                                 then T.Bad "out of memory"
                                 else T.Ok inst { mem = v }
shrinkByType inst T.FailDisk = let v = dsk inst - T.unitDsk
                               in if v < T.unitDsk
                                  then T.Bad "out of disk"
                                  else T.Ok inst { dsk = v }
shrinkByType inst T.FailCPU = let v = vcpus inst - T.unitCpu
                              in if v < T.unitCpu
                                 then T.Bad "out of vcpus"
                                 else T.Ok inst { vcpus = v }
shrinkByType _ f = T.Bad $ "Unhandled failure mode " ++ show f

-- | Return the spec of an instance.
specOf :: Instance -> T.RSpec
specOf Instance { mem = m, dsk = d, vcpus = c } =
  T.RSpec { T.rspecCpu = c, T.rspecMem = m, T.rspecDsk = d }

-- | Checks if an instance is smaller than a given spec. Returns
-- OpGood for a correct spec, otherwise OpFail one of the possible
-- failure modes.
instBelowISpec :: Instance -> T.ISpec -> T.OpResult ()
instBelowISpec inst ispec
  | mem inst > T.iSpecMemorySize ispec = T.OpFail T.FailMem
  | dsk inst > T.iSpecDiskSize ispec   = T.OpFail T.FailDisk
  | vcpus inst > T.iSpecCpuCount ispec = T.OpFail T.FailCPU
  | otherwise = T.OpGood ()

-- | Checks if an instance is bigger than a given spec.
instAboveISpec :: Instance -> T.ISpec -> T.OpResult ()
instAboveISpec inst ispec
  | mem inst < T.iSpecMemorySize ispec = T.OpFail T.FailMem
  | dsk inst < T.iSpecDiskSize ispec   = T.OpFail T.FailDisk
  | vcpus inst < T.iSpecCpuCount ispec = T.OpFail T.FailCPU
  | otherwise = T.OpGood ()

-- | Checks if an instance matches a policy.
instMatchesPolicy :: Instance -> T.IPolicy -> T.OpResult ()
instMatchesPolicy inst ipol = do
  instAboveISpec inst (T.iPolicyMinSpec ipol)
  instBelowISpec inst (T.iPolicyMaxSpec ipol)
  if (diskTemplate inst `elem` T.iPolicyDiskTemplates ipol)
    then T.OpGood ()
    else T.OpFail T.FailDisk

-- | Checks whether the instance uses a secondary node.
--
-- /Note:/ This should be reconciled with @'sNode' ==
-- 'Node.noSecondary'@.
hasSecondary :: Instance -> Bool
hasSecondary = (== T.DTDrbd8) . diskTemplate

-- | Computed the number of nodes for a given disk template.
requiredNodes :: T.DiskTemplate -> Int
requiredNodes T.DTDrbd8 = 2
requiredNodes _         = 1

-- | Computes all nodes of an instance.
allNodes :: Instance -> [T.Ndx]
allNodes inst = case diskTemplate inst of
                  T.DTDrbd8 -> [pNode inst, sNode inst]
                  _ -> [pNode inst]

-- | Checks whether a given disk template uses local storage.
usesLocalStorage :: Instance -> Bool
usesLocalStorage = (`elem` localStorageTemplates) . diskTemplate

-- | Checks whether a given disk template supported moves.
supportsMoves :: T.DiskTemplate -> Bool
supportsMoves = (`elem` movableDiskTemplates)

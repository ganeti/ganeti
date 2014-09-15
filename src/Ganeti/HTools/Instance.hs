{-| Module describing an instance.

The instance data type holds very few fields, the algorithm
intelligence is in the "Node" and "Cluster" modules.

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

module Ganeti.HTools.Instance
  ( Instance(..)
  , Disk(..)
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
  , getTotalSpindles
  , instBelowISpec
  , instAboveISpec
  , instMatchesPolicy
  , shrinkByType
  , localStorageTemplates
  , hasSecondary
  , requiredNodes
  , allNodes
  , usesLocalStorage
  , mirrorType
  ) where

import Control.Monad (liftM2)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Types as T
import qualified Ganeti.HTools.Container as Container
import Ganeti.HTools.Nic (Nic)

import Ganeti.Utils

-- * Type declarations
data Disk = Disk
  { dskSize     :: Int       -- ^ Size in bytes
  , dskSpindles :: Maybe Int -- ^ Number of spindles
  } deriving (Show, Eq)

-- | The instance type.
data Instance = Instance
  { name         :: String    -- ^ The instance name
  , alias        :: String    -- ^ The shortened name
  , mem          :: Int       -- ^ Memory of the instance
  , dsk          :: Int       -- ^ Total disk usage of the instance
  , disks        :: [Disk]    -- ^ Sizes of the individual disks
  , vcpus        :: Int       -- ^ Number of VCPUs
  , runSt        :: T.InstanceStatus -- ^ Original run status
  , pNode        :: T.Ndx     -- ^ Original primary node
  , sNode        :: T.Ndx     -- ^ Original secondary node
  , idx          :: T.Idx     -- ^ Internal index
  , util         :: T.DynUtil -- ^ Dynamic resource usage
  , movable      :: Bool      -- ^ Can and should the instance be moved?
  , autoBalance  :: Bool      -- ^ Is the instance auto-balanced?
  , diskTemplate :: T.DiskTemplate -- ^ The disk template of the instance
  , spindleUse   :: Int       -- ^ The numbers of used spindles
  , allTags      :: [String]  -- ^ List of all instance tags
  , exclTags     :: [String]  -- ^ List of instance exclusion tags
  , arPolicy     :: T.AutoRepairPolicy -- ^ Instance's auto-repair policy
  , nics         :: [Nic]     -- ^ NICs of the instance
  } deriving (Show, Eq)

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
isOffline (Instance {runSt = T.StatusOffline}) = True
isOffline _                                    = False


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
movableDiskTemplates =
  [ T.DTDrbd8
  , T.DTBlock
  , T.DTSharedFile
  , T.DTGluster
  , T.DTRbd
  , T.DTExt
  ]

-- | A simple name for the int, instance association list.
type AssocList = [(T.Idx, Instance)]

-- | A simple name for an instance map.
type List = Container.Container Instance

-- * Initialization

-- | Create an instance.
--
-- Some parameters are not initialized by function, and must be set
-- later (via 'setIdx' for example).
create :: String -> Int -> Int -> [Disk] -> Int -> T.InstanceStatus
       -> [String] -> Bool -> T.Ndx -> T.Ndx -> T.DiskTemplate -> Int
       -> [Nic] -> Instance
create name_init mem_init dsk_init disks_init vcpus_init run_init tags_init
       auto_balance_init pn sn dt su nics_init =
  Instance { name = name_init
           , alias = name_init
           , mem = mem_init
           , dsk = dsk_init
           , disks = disks_init
           , vcpus = vcpus_init
           , runSt = run_init
           , pNode = pn
           , sNode = sn
           , idx = -1
           , util = T.baseUtil
           , movable = supportsMoves dt
           , autoBalance = auto_balance_init
           , diskTemplate = dt
           , spindleUse = su
           , allTags = tags_init
           , exclTags = []
           , arPolicy = T.ArNotEnabled
           , nics = nics_init
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
shrinkByType :: Instance -> T.FailMode -> Result Instance
shrinkByType inst T.FailMem = let v = mem inst - T.unitMem
                              in if v < T.unitMem
                                 then Bad "out of memory"
                                 else Ok inst { mem = v }
shrinkByType inst T.FailDisk =
  let newdisks = [d {dskSize = dskSize d - T.unitDsk}| d <- disks inst]
      v = dsk inst - (length . disks $ inst) * T.unitDsk
  in if any (< T.unitDsk) $ map dskSize newdisks
     then Bad "out of disk"
     else Ok inst { dsk = v, disks = newdisks }
shrinkByType inst T.FailCPU = let v = vcpus inst - T.unitCpu
                              in if v < T.unitCpu
                                 then Bad "out of vcpus"
                                 else Ok inst { vcpus = v }
shrinkByType inst T.FailSpindles =
  case disks inst of
    [Disk ds sp] -> case sp of
                      Nothing -> Bad "No spindles, shouldn't have happened"
                      Just sp' -> let v = sp' - T.unitSpindle
                                  in if v < T.unitSpindle
                                     then Bad "out of spindles"
                                     else Ok inst { disks = [Disk ds (Just v)] }
    d -> Bad $ "Expected one disk, but found " ++ show d
shrinkByType _ f = Bad $ "Unhandled failure mode " ++ show f

-- | Get the number of disk spindles
getTotalSpindles :: Instance -> Maybe Int
getTotalSpindles inst =
  foldr (liftM2 (+) . dskSpindles ) (Just 0) (disks inst)

-- | Return the spec of an instance.
specOf :: Instance -> T.RSpec
specOf Instance { mem = m, dsk = d, vcpus = c, disks = dl } =
  let sp = case dl of
             [Disk _ (Just sp')] -> sp'
             _ -> 0
  in T.RSpec { T.rspecCpu = c, T.rspecMem = m,
               T.rspecDsk = d, T.rspecSpn = sp }

-- | Checks if an instance is smaller/bigger than a given spec. Returns
-- OpGood for a correct spec, otherwise Bad one of the possible
-- failure modes.
instCompareISpec :: Ordering -> Instance-> T.ISpec -> Bool -> T.OpResult ()
instCompareISpec which inst ispec exclstor
  | which == mem inst `compare` T.iSpecMemorySize ispec = Bad T.FailMem
  | which `elem` map ((`compare` T.iSpecDiskSize ispec) . dskSize)
    (disks inst) = Bad T.FailDisk
  | which == vcpus inst `compare` T.iSpecCpuCount ispec = Bad T.FailCPU
  | exclstor &&
    case getTotalSpindles inst of
      Nothing -> True
      Just sp_sum -> which == sp_sum `compare` T.iSpecSpindleUse ispec
    = Bad T.FailSpindles
  | not exclstor && which == spindleUse inst `compare` T.iSpecSpindleUse ispec
    = Bad T.FailSpindles
  | diskTemplate inst /= T.DTDiskless &&
    which == length (disks inst) `compare` T.iSpecDiskCount ispec
    = Bad T.FailDiskCount
  | otherwise = Ok ()

-- | Checks if an instance is smaller than a given spec.
instBelowISpec :: Instance -> T.ISpec -> Bool -> T.OpResult ()
instBelowISpec = instCompareISpec GT

-- | Checks if an instance is bigger than a given spec.
instAboveISpec :: Instance -> T.ISpec -> Bool -> T.OpResult ()
instAboveISpec = instCompareISpec LT

-- | Checks if an instance matches a min/max specs pair
instMatchesMinMaxSpecs :: Instance -> T.MinMaxISpecs -> Bool -> T.OpResult ()
instMatchesMinMaxSpecs inst minmax exclstor = do
  instAboveISpec inst (T.minMaxISpecsMinSpec minmax) exclstor
  instBelowISpec inst (T.minMaxISpecsMaxSpec minmax) exclstor

-- | Checks if an instance matches any specs of a policy
instMatchesSpecs :: Instance -> [T.MinMaxISpecs] -> Bool -> T.OpResult ()
 -- Return Ok for no constraints, though this should never happen
instMatchesSpecs _ [] _ = Ok ()
instMatchesSpecs inst minmaxes exclstor =
  -- The initial "Bad" should be always replaced by a real result
  foldr eithermatch (Bad T.FailInternal) minmaxes
  where eithermatch mm (Bad _) = instMatchesMinMaxSpecs inst mm exclstor
        eithermatch _ y@(Ok ()) = y

-- | Checks if an instance matches a policy.
instMatchesPolicy :: Instance -> T.IPolicy -> Bool -> T.OpResult ()
instMatchesPolicy inst ipol exclstor = do
  instMatchesSpecs inst (T.iPolicyMinMaxISpecs ipol) exclstor
  if diskTemplate inst `elem` T.iPolicyDiskTemplates ipol
    then Ok ()
    else Bad T.FailDisk

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

-- | A simple wrapper over 'T.templateMirrorType'.
mirrorType :: Instance -> T.MirrorType
mirrorType = T.templateMirrorType . diskTemplate

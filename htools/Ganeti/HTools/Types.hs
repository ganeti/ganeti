{-# LANGUAGE TemplateHaskell #-}

{-| Some common types.

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

module Ganeti.HTools.Types
  ( Idx
  , Ndx
  , Gdx
  , NameAssoc
  , Score
  , Weight
  , GroupID
  , defaultGroupID
  , AllocPolicy(..)
  , allocPolicyFromRaw
  , allocPolicyToRaw
  , InstanceStatus(..)
  , instanceStatusFromRaw
  , instanceStatusToRaw
  , RSpec(..)
  , DynUtil(..)
  , zeroUtil
  , baseUtil
  , addUtil
  , subUtil
  , defVcpuRatio
  , defReservedDiskRatio
  , unitMem
  , unitCpu
  , unitDsk
  , unknownField
  , Placement
  , IMove(..)
  , DiskTemplate(..)
  , diskTemplateToRaw
  , diskTemplateFromRaw
  , MoveJob
  , JobSet
  , Result(..)
  , isOk
  , isBad
  , eitherToResult
  , annotateResult
  , Element(..)
  , FailMode(..)
  , FailStats
  , OpResult(..)
  , opToResult
  , connTimeout
  , queryTimeout
  , EvacMode(..)
  , ISpec(..)
  , IPolicy(..)
  , defIPolicy
  ) where

import qualified Data.Map as M
import Text.JSON (makeObj, readJSON, showJSON)

import qualified Ganeti.Constants as C
import qualified Ganeti.THH as THH
import Ganeti.BasicTypes
import Ganeti.HTools.JSON

-- | The instance index type.
type Idx = Int

-- | The node index type.
type Ndx = Int

-- | The group index type.
type Gdx = Int

-- | The type used to hold name-to-idx mappings.
type NameAssoc = M.Map String Int

-- | A separate name for the cluster score type.
type Score = Double

-- | A separate name for a weight metric.
type Weight = Double

-- | The Group UUID type.
type GroupID = String

-- | Default group UUID (just a string, not a real UUID).
defaultGroupID :: GroupID
defaultGroupID = "00000000-0000-0000-0000-000000000000"

-- | The Group allocation policy type.
--
-- Note that the order of constructors is important as the automatic
-- Ord instance will order them in the order they are defined, so when
-- changing this data type be careful about the interaction with the
-- desired sorting order.
$(THH.declareSADT "AllocPolicy"
       [ ("AllocPreferred",   'C.allocPolicyPreferred)
       , ("AllocLastResort",  'C.allocPolicyLastResort)
       , ("AllocUnallocable", 'C.allocPolicyUnallocable)
       ])
$(THH.makeJSONInstance ''AllocPolicy)

-- | The Instance real state type.
$(THH.declareSADT "InstanceStatus"
       [ ("AdminDown", 'C.inststAdmindown)
       , ("AdminOffline", 'C.inststAdminoffline)
       , ("ErrorDown", 'C.inststErrordown)
       , ("ErrorUp", 'C.inststErrorup)
       , ("NodeDown", 'C.inststNodedown)
       , ("NodeOffline", 'C.inststNodeoffline)
       , ("Running", 'C.inststRunning)
       , ("WrongNode", 'C.inststWrongnode)
       ])
$(THH.makeJSONInstance ''InstanceStatus)

-- | The resource spec type.
data RSpec = RSpec
  { rspecCpu  :: Int  -- ^ Requested VCPUs
  , rspecMem  :: Int  -- ^ Requested memory
  , rspecDsk  :: Int  -- ^ Requested disk
  } deriving (Show, Read, Eq)


-- | Instance specification type.
$(THH.buildObject "ISpec" "iSpec"
  [ THH.renameField "MemorySize" $ THH.simpleField "memory-size" [t| Int |]
  , THH.renameField "CpuCount"   $ THH.simpleField "cpu-count"   [t| Int |]
  , THH.renameField "DiskSize"   $ THH.simpleField "disk-size"   [t| Int |]
  , THH.renameField "DiskCount"  $ THH.simpleField "disk-count"  [t| Int |]
  , THH.renameField "NicCount"   $ THH.simpleField "nic-count"   [t| Int |]
  ])

-- | The default minimum ispec.
defMinISpec :: ISpec
defMinISpec = ISpec { iSpecMemorySize = C.ipolicyDefaultsMinMemorySize
                    , iSpecCpuCount   = C.ipolicyDefaultsMinCpuCount
                    , iSpecDiskSize   = C.ipolicyDefaultsMinDiskSize
                    , iSpecDiskCount  = C.ipolicyDefaultsMinDiskCount
                    , iSpecNicCount   = C.ipolicyDefaultsMinNicCount
                    }

-- | The default standard ispec.
defStdISpec :: ISpec
defStdISpec = ISpec { iSpecMemorySize = C.ipolicyDefaultsStdMemorySize
                    , iSpecCpuCount   = C.ipolicyDefaultsStdCpuCount
                    , iSpecDiskSize   = C.ipolicyDefaultsStdDiskSize
                    , iSpecDiskCount  = C.ipolicyDefaultsStdDiskCount
                    , iSpecNicCount   = C.ipolicyDefaultsStdNicCount
                    }

-- | The default max ispec.
defMaxISpec :: ISpec
defMaxISpec = ISpec { iSpecMemorySize = C.ipolicyDefaultsMaxMemorySize
                    , iSpecCpuCount   = C.ipolicyDefaultsMaxCpuCount
                    , iSpecDiskSize   = C.ipolicyDefaultsMaxDiskSize
                    , iSpecDiskCount  = C.ipolicyDefaultsMaxDiskCount
                    , iSpecNicCount   = C.ipolicyDefaultsMaxNicCount
                    }

-- | Instance policy type.
$(THH.buildObject "IPolicy" "iPolicy"
  [ THH.renameField "StdSpec" $ THH.simpleField "std" [t| ISpec |]
  , THH.renameField "MinSpec" $ THH.simpleField "min" [t| ISpec |]
  , THH.renameField "MaxSpec" $ THH.simpleField "max" [t| ISpec |]
  ])

-- | The default instance policy.
defIPolicy :: IPolicy
defIPolicy = IPolicy { iPolicyStdSpec = defStdISpec
                     , iPolicyMinSpec = defMinISpec
                     , iPolicyMaxSpec = defMaxISpec
                     }

-- | The dynamic resource specs of a machine (i.e. load or load
-- capacity, as opposed to size).
data DynUtil = DynUtil
  { cpuWeight :: Weight -- ^ Standardised CPU usage
  , memWeight :: Weight -- ^ Standardised memory load
  , dskWeight :: Weight -- ^ Standardised disk I\/O usage
  , netWeight :: Weight -- ^ Standardised network usage
  } deriving (Show, Read, Eq)

-- | Initial empty utilisation.
zeroUtil :: DynUtil
zeroUtil = DynUtil { cpuWeight = 0, memWeight = 0
                   , dskWeight = 0, netWeight = 0 }

-- | Base utilisation (used when no actual utilisation data is
-- supplied).
baseUtil :: DynUtil
baseUtil = DynUtil { cpuWeight = 1, memWeight = 1
                   , dskWeight = 1, netWeight = 1 }

-- | Sum two utilisation records.
addUtil :: DynUtil -> DynUtil -> DynUtil
addUtil (DynUtil a1 a2 a3 a4) (DynUtil b1 b2 b3 b4) =
  DynUtil (a1+b1) (a2+b2) (a3+b3) (a4+b4)

-- | Substracts one utilisation record from another.
subUtil :: DynUtil -> DynUtil -> DynUtil
subUtil (DynUtil a1 a2 a3 a4) (DynUtil b1 b2 b3 b4) =
  DynUtil (a1-b1) (a2-b2) (a3-b3) (a4-b4)

-- | The description of an instance placement. It contains the
-- instance index, the new primary and secondary node, the move being
-- performed and the score of the cluster after the move.
type Placement = (Idx, Ndx, Ndx, IMove, Score)

-- | An instance move definition.
data IMove = Failover                -- ^ Failover the instance (f)
           | ReplacePrimary Ndx      -- ^ Replace primary (f, r:np, f)
           | ReplaceSecondary Ndx    -- ^ Replace secondary (r:ns)
           | ReplaceAndFailover Ndx  -- ^ Replace secondary, failover (r:np, f)
           | FailoverAndReplace Ndx  -- ^ Failover, replace secondary (f, r:ns)
             deriving (Show, Read)

-- | Instance disk template type.
$(THH.declareSADT "DiskTemplate"
       [ ("DTDiskless",   'C.dtDiskless)
       , ("DTFile",       'C.dtFile)
       , ("DTSharedFile", 'C.dtSharedFile)
       , ("DTPlain",      'C.dtPlain)
       , ("DTBlock",      'C.dtBlock)
       , ("DTDrbd8",      'C.dtDrbd8)
       ])
$(THH.makeJSONInstance ''DiskTemplate)

-- | Formatted solution output for one move (involved nodes and
-- commands.
type MoveJob = ([Ndx], Idx, IMove, [String])

-- | Unknown field in table output.
unknownField :: String
unknownField = "<unknown field>"

-- | A list of command elements.
type JobSet = [MoveJob]

-- | Connection timeout (when using non-file methods).
connTimeout :: Int
connTimeout = 15

-- | The default timeout for queries (when using non-file methods).
queryTimeout :: Int
queryTimeout = 60

-- | Default vcpu-to-pcpu ratio (randomly chosen value).
defVcpuRatio :: Double
defVcpuRatio = 64

-- | Default max disk usage ratio.
defReservedDiskRatio :: Double
defReservedDiskRatio = 0

-- | Base memory unit.
unitMem :: Int
unitMem = 64

-- | Base disk unit.
unitDsk :: Int
unitDsk = 256

-- | Base vcpus unit.
unitCpu :: Int
unitCpu = 1

-- | Reason for an operation's falure.
data FailMode = FailMem  -- ^ Failed due to not enough RAM
              | FailDisk -- ^ Failed due to not enough disk
              | FailCPU  -- ^ Failed due to not enough CPU capacity
              | FailN1   -- ^ Failed due to not passing N1 checks
              | FailTags -- ^ Failed due to tag exclusion
                deriving (Eq, Enum, Bounded, Show, Read)

-- | List with failure statistics.
type FailStats = [(FailMode, Int)]

-- | Either-like data-type customized for our failure modes.
--
-- The failure values for this monad track the specific allocation
-- failures, so this is not a general error-monad (compare with the
-- 'Result' data type). One downside is that this type cannot encode a
-- generic failure mode, hence 'fail' for this monad is not defined
-- and will cause an exception.
data OpResult a = OpFail FailMode -- ^ Failed operation
                | OpGood a        -- ^ Success operation
                  deriving (Show, Read)

instance Monad OpResult where
  (OpGood x) >>= fn = fn x
  (OpFail y) >>= _ = OpFail y
  return = OpGood

-- | Conversion from 'OpResult' to 'Result'.
opToResult :: OpResult a -> Result a
opToResult (OpFail f) = Bad $ show f
opToResult (OpGood v) = Ok v

-- | A generic class for items that have updateable names and indices.
class Element a where
  -- | Returns the name of the element
  nameOf  :: a -> String
  -- | Returns all the known names of the element
  allNames :: a -> [String]
  -- | Returns the index of the element
  idxOf   :: a -> Int
  -- | Updates the alias of the element
  setAlias :: a -> String -> a
  -- | Compute the alias by stripping a given suffix (domain) from
  -- the name
  computeAlias :: String -> a -> a
  computeAlias dom e = setAlias e alias
    where alias = take (length name - length dom) name
          name = nameOf e
  -- | Updates the index of the element
  setIdx  :: a -> Int -> a

-- | The iallocator node-evacuate evac_mode type.
$(THH.declareSADT "EvacMode"
       [ ("ChangePrimary",   'C.iallocatorNevacPri)
       , ("ChangeSecondary", 'C.iallocatorNevacSec)
       , ("ChangeAll",       'C.iallocatorNevacAll)
       ])
$(THH.makeJSONInstance ''EvacMode)

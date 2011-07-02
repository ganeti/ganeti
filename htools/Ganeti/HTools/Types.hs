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
    , AllocPolicy(..)
    , apolFromString
    , apolToString
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
    , dtToString
    , dtFromString
    , MoveJob
    , JobSet
    , Result(..)
    , isOk
    , isBad
    , Element(..)
    , FailMode(..)
    , FailStats
    , OpResult(..)
    , connTimeout
    , queryTimeout
    , EvacMode(..)
    ) where

import qualified Data.Map as M
import qualified Text.JSON as JSON

import qualified Ganeti.Constants as C

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

-- | The Group allocation policy type.
--
-- Note that the order of constructors is important as the automatic
-- Ord instance will order them in the order they are defined, so when
-- changing this data type be careful about the interaction with the
-- desired sorting order.
data AllocPolicy
    = AllocPreferred   -- ^ This is the normal status, the group
                       -- should be used normally during allocations
    | AllocLastResort  -- ^ This group should be used only as
                       -- last-resort, after the preferred groups
    | AllocUnallocable -- ^ This group must not be used for new
                       -- allocations
      deriving (Show, Read, Eq, Ord)

-- | Convert a string to an alloc policy.
apolFromString :: (Monad m) => String -> m AllocPolicy
apolFromString s =
    case () of
      _ | s == C.allocPolicyPreferred -> return AllocPreferred
        | s == C.allocPolicyLastResort -> return AllocLastResort
        | s == C.allocPolicyUnallocable -> return AllocUnallocable
        | otherwise -> fail $ "Invalid alloc policy mode: " ++ s

-- | Convert an alloc policy to the Ganeti string equivalent.
apolToString :: AllocPolicy -> String
apolToString AllocPreferred   = C.allocPolicyPreferred
apolToString AllocLastResort  = C.allocPolicyLastResort
apolToString AllocUnallocable = C.allocPolicyUnallocable

instance JSON.JSON AllocPolicy where
    showJSON = JSON.showJSON . apolToString
    readJSON s = case JSON.readJSON s of
                   JSON.Ok s' -> apolFromString s'
                   JSON.Error e -> JSON.Error $
                                   "Can't parse alloc_policy: " ++ e

-- | The resource spec type.
data RSpec = RSpec
    { rspecCpu  :: Int  -- ^ Requested VCPUs
    , rspecMem  :: Int  -- ^ Requested memory
    , rspecDsk  :: Int  -- ^ Requested disk
    } deriving (Show, Read, Eq)

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

-- | Instance disk template type
data DiskTemplate = DTDiskless
                  | DTFile
                  | DTSharedFile
                  | DTPlain
                  | DTBlock
                  | DTDrbd8
                    deriving (Show, Read, Eq)

-- | Converts a DiskTemplate to String
dtToString :: DiskTemplate -> String
dtToString DTDiskless   = C.dtDiskless
dtToString DTFile       = C.dtFile
dtToString DTSharedFile = C.dtSharedFile
dtToString DTPlain      = C.dtPlain
dtToString DTBlock      = C.dtBlock
dtToString DTDrbd8      = C.dtDrbd8

-- | Converts a DiskTemplate from String
dtFromString :: (Monad m) => String -> m DiskTemplate
dtFromString s =
    case () of
      _ | s == C.dtDiskless   -> return DTDiskless
        | s == C.dtFile       -> return DTFile
        | s == C.dtSharedFile -> return DTSharedFile
        | s == C.dtPlain      -> return DTPlain
        | s == C.dtBlock      -> return DTBlock
        | s == C.dtDrbd8      -> return DTDrbd8
        | otherwise           -> fail $ "Invalid disk template: " ++ s

instance JSON.JSON DiskTemplate where
    showJSON = JSON.showJSON . dtToString
    readJSON s = case JSON.readJSON s of
                   JSON.Ok s' -> dtFromString s'
                   JSON.Error e -> JSON.Error $
                                   "Can't parse disk_template as string: " ++ e

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

{-|

This is similar to the JSON library Result type - /very/ similar, but
we want to use it in multiple places, so we abstract it into a
mini-library here

-}
data Result a
    = Bad String
    | Ok a
    deriving (Show, Read)

instance Monad Result where
    (>>=) (Bad x) _ = Bad x
    (>>=) (Ok x) fn = fn x
    return = Ok
    fail = Bad

-- | Simple checker for whether a 'Result' is OK.
isOk :: Result a -> Bool
isOk (Ok _) = True
isOk _ = False

-- | Simple checker for whether a 'Result' is a failure.
isBad :: Result a  -> Bool
isBad = not . isOk

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
data OpResult a = OpFail FailMode -- ^ Failed operation
                | OpGood a        -- ^ Success operation
                  deriving (Show, Read)

instance Monad OpResult where
    (OpGood x) >>= fn = fn x
    (OpFail y) >>= _ = OpFail y
    return = OpGood

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
data EvacMode = ChangePrimary
              | ChangeSecondary
              | ChangeAll
                deriving (Show, Read)

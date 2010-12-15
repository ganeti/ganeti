{-| Some common types.

-}

{-

Copyright (C) 2009, 2010 Google Inc.

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
    ) where

import qualified Data.Map as M

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
data AllocPolicy = AllocPreferred
                 | AllocLastResort
                 | AllocUnallocable
                   deriving (Show, Eq)

-- | The resource spec type.
data RSpec = RSpec
    { rspecCpu  :: Int  -- ^ Requested VCPUs
    , rspecMem  :: Int  -- ^ Requested memory
    , rspecDsk  :: Int  -- ^ Requested disk
    } deriving (Show, Eq)

-- | The dynamic resource specs of a machine (i.e. load or load
-- capacity, as opposed to size).
data DynUtil = DynUtil
    { cpuWeight :: Weight -- ^ Standardised CPU usage
    , memWeight :: Weight -- ^ Standardised memory load
    , dskWeight :: Weight -- ^ Standardised disk I\/O usage
    , netWeight :: Weight -- ^ Standardised network usage
    } deriving (Show, Eq)

-- | Initial empty utilisation
zeroUtil :: DynUtil
zeroUtil = DynUtil { cpuWeight = 0, memWeight = 0
                   , dskWeight = 0, netWeight = 0 }

baseUtil :: DynUtil
baseUtil = DynUtil { cpuWeight = 1, memWeight = 1
                   , dskWeight = 1, netWeight = 1 }

addUtil :: DynUtil -> DynUtil -> DynUtil
addUtil (DynUtil a1 a2 a3 a4) (DynUtil b1 b2 b3 b4) =
    DynUtil (a1+b1) (a2+b2) (a3+b3) (a4+b4)

subUtil :: DynUtil -> DynUtil -> DynUtil
subUtil (DynUtil a1 a2 a3 a4) (DynUtil b1 b2 b3 b4) =
    DynUtil (a1-b1) (a2-b2) (a3-b3) (a4-b4)

-- | The description of an instance placement. It contains the
-- instance index, the new primary and secondary node, the move being
-- performed and the score of the cluster after the move.
type Placement = (Idx, Ndx, Ndx, IMove, Score)

-- | An instance move definition
data IMove = Failover                -- ^ Failover the instance (f)
           | ReplacePrimary Ndx      -- ^ Replace primary (f, r:np, f)
           | ReplaceSecondary Ndx    -- ^ Replace secondary (r:ns)
           | ReplaceAndFailover Ndx  -- ^ Replace secondary, failover (r:np, f)
           | FailoverAndReplace Ndx  -- ^ Failover, replace secondary (f, r:ns)
             deriving (Show)

-- | Formatted solution output for one move (involved nodes and
-- commands
type MoveJob = ([Ndx], Idx, IMove, [String])

-- | Unknown field in table output
unknownField :: String
unknownField = "<unknown field>"

-- | A list of command elements
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

This is similar to the JSON library Result type - *very* similar, but
we want to use it in multiple places, so we abstract it into a
mini-library here

-}
data Result a
    = Bad String
    | Ok a
    deriving (Show)

instance Monad Result where
    (>>=) (Bad x) _ = Bad x
    (>>=) (Ok x) fn = fn x
    return = Ok
    fail = Bad

-- | Simple checker for whether Result is OK
isOk :: Result a -> Bool
isOk (Ok _) = True
isOk _ = False

-- | Simple checker for whether Result is a failure
isBad :: Result a  -> Bool
isBad = not . isOk

-- | Reason for an operation's falure
data FailMode = FailMem  -- ^ Failed due to not enough RAM
              | FailDisk -- ^ Failed due to not enough disk
              | FailCPU  -- ^ Failed due to not enough CPU capacity
              | FailN1   -- ^ Failed due to not passing N1 checks
              | FailTags -- ^ Failed due to tag exclusion
                deriving (Eq, Enum, Bounded, Show)

-- | List with failure statistics
type FailStats = [(FailMode, Int)]

-- | Either-like data-type customized for our failure modes
data OpResult a = OpFail FailMode -- ^ Failed operation
                | OpGood a        -- ^ Success operation
                  deriving (Show)

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
    -- | the name
    computeAlias :: String -> a -> a
    computeAlias dom e = setAlias e alias
        where alias = take (length name - length dom) name
              name = nameOf e
    -- | Updates the index of the element
    setIdx  :: a -> Int -> a

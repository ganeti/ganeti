{-| ConstantUtils contains the helper functions for constants

This module cannot be merged with 'Ganeti.Utils' because it would
create a circular dependency if imported, for example, from
'Ganeti.Constants'.

-}

{-

Copyright (C) 2013 Google Inc.
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
module Ganeti.ConstantUtils where

import Prelude ()
import Ganeti.Prelude

import Data.Char (ord)
import Data.Set (Set)
import qualified Data.Set as Set (difference, fromList, toList, union)

import Ganeti.PyValue

-- | 'PythonChar' wraps a Python 'char'
newtype PythonChar = PythonChar { unPythonChar :: Char }
  deriving (Show)

instance PyValue PythonChar where
  showValue c = "chr(" ++ show (ord (unPythonChar c)) ++ ")"

-- | 'PythonNone' wraps Python 'None'
data PythonNone = PythonNone

instance PyValue PythonNone where
  showValue _ = "None"

-- | FrozenSet wraps a Haskell 'Set'
--
-- See 'PyValue' instance for 'FrozenSet'.
newtype FrozenSet a = FrozenSet { unFrozenSet :: Set a }
  deriving (Eq, Ord, Show)

instance (Ord a) => Monoid (FrozenSet a) where
  mempty = FrozenSet mempty
  mappend (FrozenSet s) (FrozenSet t) = FrozenSet (mappend s t)

-- | Converts a Haskell 'Set' into a Python 'frozenset'
--
-- This instance was supposed to be for 'Set' instead of 'FrozenSet'.
-- However, 'ghc-6.12.1' seems to be crashing with 'segmentation
-- fault' due to the presence of more than one instance of 'Set',
-- namely, this one and the one in 'Ganeti.OpCodes'.  For this reason,
-- we wrap 'Set' into 'FrozenSet'.
instance PyValue a => PyValue (FrozenSet a) where
  showValue s = "frozenset(" ++ showValue (Set.toList (unFrozenSet s)) ++ ")"

mkSet :: Ord a => [a] -> FrozenSet a
mkSet = FrozenSet . Set.fromList

toList :: FrozenSet a -> [a]
toList = Set.toList . unFrozenSet

union :: Ord a => FrozenSet a -> FrozenSet a -> FrozenSet a
union x y = FrozenSet (unFrozenSet x `Set.union` unFrozenSet y)

difference :: Ord a => FrozenSet a -> FrozenSet a -> FrozenSet a
difference x y = FrozenSet (unFrozenSet x `Set.difference` unFrozenSet y)

-- | 'Protocol' represents the protocols used by the daemons
data Protocol = Tcp | Udp
  deriving (Show)

-- | 'PyValue' instance of 'Protocol'
--
-- This instance is used by the Haskell to Python constants
instance PyValue Protocol where
  showValue Tcp = "\"tcp\""
  showValue Udp = "\"udp\""

-- | Failure exit code
--
-- These are defined here and not in 'Ganeti.Constants' together with
-- the other exit codes in order to avoid a circular dependency
-- between 'Ganeti.Constants' and 'Ganeti.Runtime'
exitFailure :: Int
exitFailure = 1

-- | Console device
--
-- This is defined here and not in 'Ganeti.Constants' order to avoid a
-- circular dependency between 'Ganeti.Constants' and 'Ganeti.Logging'
devConsole :: String
devConsole = "/dev/console"

-- | Random uuid generator
--
-- This is defined here and not in 'Ganeti.Constants' order to avoid a
-- circular dependendy between 'Ganeti.Constants' and 'Ganeti.Types'
randomUuidFile :: String
randomUuidFile = "/proc/sys/kernel/random/uuid"

-- * Priority levels
--
-- This is defined here and not in 'Ganeti.Types' in order to avoid a
-- GHC stage restriction and because there is no suitable 'declareADT'
-- variant that handles integer values directly.

priorityLow :: Int
priorityLow = 10

priorityNormal :: Int
priorityNormal = 0

priorityHigh :: Int
priorityHigh = -10

-- | Calculates int version number from major, minor and revision
-- numbers.
buildVersion :: Int -> Int -> Int -> Int
buildVersion major minor revision =
  1000000 * major + 10000 * minor + 1 * revision

-- | Confd protocol version
--
-- This is defined here in order to avoid a circular dependency
-- between 'Ganeti.Confd.Types' and 'Ganeti.Constants'.
confdProtocolVersion :: Int
confdProtocolVersion = 1

-- * Confd request query fields
--
-- These are defined here and not in 'Ganeti.Types' due to GHC stage
-- restrictions concerning Template Haskell.  They are also not
-- defined in 'Ganeti.Constants' in order to avoid a circular
-- dependency between that module and 'Ganeti.Types'.

confdReqqLink :: String
confdReqqLink = "0"

confdReqqIp :: String
confdReqqIp = "1"

confdReqqIplist :: String
confdReqqIplist = "2"

confdReqqFields :: String
confdReqqFields = "3"

-- * ISpec

ispecMemSize :: String
ispecMemSize = "memory-size"

ispecCpuCount :: String
ispecCpuCount = "cpu-count"

ispecDiskCount :: String
ispecDiskCount = "disk-count"

ispecDiskSize :: String
ispecDiskSize = "disk-size"

ispecNicCount :: String
ispecNicCount = "nic-count"

ispecSpindleUse :: String
ispecSpindleUse = "spindle-use"

ispecsMinmax :: String
ispecsMinmax = "minmax"

ispecsStd :: String
ispecsStd = "std"

ipolicyDts :: String
ipolicyDts = "disk-templates"

ipolicyVcpuRatio :: String
ipolicyVcpuRatio = "vcpu-ratio"

ipolicySpindleRatio :: String
ipolicySpindleRatio = "spindle-ratio"

ipolicyMemoryRatio :: String
ipolicyMemoryRatio = "memory-ratio"

ipolicyDefaultsVcpuRatio :: Double
ipolicyDefaultsVcpuRatio = 4.0

ipolicyDefaultsSpindleRatio :: Double
ipolicyDefaultsSpindleRatio = 32.0

ipolicyDefaultsMemoryRatio :: Double
ipolicyDefaultsMemoryRatio = 1.0

-- * Hypervisor state default parameters

hvstDefaultCpuNode :: Int
hvstDefaultCpuNode = 1

hvstDefaultCpuTotal :: Int
hvstDefaultCpuTotal = 1

hvstDefaultMemoryHv :: Int
hvstDefaultMemoryHv = 1024

hvstDefaultMemoryTotal :: Int
hvstDefaultMemoryTotal = 1024

hvstDefaultMemoryNode :: Int
hvstDefaultMemoryNode = 4096

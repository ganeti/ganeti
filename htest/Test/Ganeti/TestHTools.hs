{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Common functionality for htools-related unittests.

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

module Test.Ganeti.TestHTools where

import qualified Data.Map as Map

import Test.Ganeti.TestCommon

import qualified Ganeti.Constants as C
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Types as Types

-- * Helpers

-- | Null iPolicy, and by null we mean very liberal.
nullIPolicy :: Types.IPolicy
nullIPolicy = Types.IPolicy
  { Types.iPolicyMinSpec = Types.ISpec { Types.iSpecMemorySize = 0
                                       , Types.iSpecCpuCount   = 0
                                       , Types.iSpecDiskSize   = 0
                                       , Types.iSpecDiskCount  = 0
                                       , Types.iSpecNicCount   = 0
                                       , Types.iSpecSpindleUse = 0
                                       }
  , Types.iPolicyMaxSpec = Types.ISpec { Types.iSpecMemorySize = maxBound
                                       , Types.iSpecCpuCount   = maxBound
                                       , Types.iSpecDiskSize   = maxBound
                                       , Types.iSpecDiskCount  = C.maxDisks
                                       , Types.iSpecNicCount   = C.maxNics
                                       , Types.iSpecSpindleUse = maxBound
                                       }
  , Types.iPolicyStdSpec = Types.ISpec { Types.iSpecMemorySize = Types.unitMem
                                       , Types.iSpecCpuCount   = Types.unitCpu
                                       , Types.iSpecDiskSize   = Types.unitDsk
                                       , Types.iSpecDiskCount  = 1
                                       , Types.iSpecNicCount   = 1
                                       , Types.iSpecSpindleUse = 1
                                       }
  , Types.iPolicyDiskTemplates = [minBound..maxBound]
  , Types.iPolicyVcpuRatio = maxVcpuRatio -- somewhat random value, high
                                          -- enough to not impact us
  , Types.iPolicySpindleRatio = maxSpindleRatio
  }

defGroup :: Group.Group
defGroup = flip Group.setIdx 0 $
             Group.create "default" Types.defaultGroupID Types.AllocPreferred
                  nullIPolicy []

defGroupList :: Group.List
defGroupList = Container.fromList [(Group.idx defGroup, defGroup)]

defGroupAssoc :: Map.Map String Types.Gdx
defGroupAssoc = Map.singleton (Group.uuid defGroup) (Group.idx defGroup)

-- | Create an instance given its spec.
createInstance :: Int -> Int -> Int -> Instance.Instance
createInstance mem dsk vcpus =
  Instance.create "inst-unnamed" mem dsk vcpus Types.Running [] True (-1) (-1)
    Types.DTDrbd8 1

-- | Create a small cluster by repeating a node spec.
makeSmallCluster :: Node.Node -> Int -> Node.List
makeSmallCluster node count =
  let origname = Node.name node
      origalias = Node.alias node
      nodes = map (\idx -> node { Node.name = origname ++ "-" ++ show idx
                                , Node.alias = origalias ++ "-" ++ show idx })
              [1..count]
      fn = flip Node.buildPeers Container.empty
      namelst = map (\n -> (Node.name n, fn n)) nodes
      (_, nlst) = Loader.assignIndices namelst
  in nlst

-- | Update an instance to be smaller than a node.
setInstanceSmallerThanNode :: Node.Node
                           -> Instance.Instance -> Instance.Instance
setInstanceSmallerThanNode node inst =
  inst { Instance.mem = Node.availMem node `div` 2
       , Instance.dsk = Node.availDisk node `div` 2
       , Instance.vcpus = Node.availCpu node `div` 2
       }

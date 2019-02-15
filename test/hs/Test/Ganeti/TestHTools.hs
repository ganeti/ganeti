{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Common functionality for htools-related unittests.

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

module Test.Ganeti.TestHTools
  ( nullIPolicy
  , nullISpec
  , defGroup
  , defGroupList
  , defGroupAssoc
  , createInstance
  , makeSmallCluster
  , setInstanceSmallerThanNode
  ) where

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

-- | An ISpec with 0 resources.
nullISpec :: Types.ISpec
nullISpec = Types.ISpec { Types.iSpecMemorySize = 0
                        , Types.iSpecCpuCount   = 0
                        , Types.iSpecDiskSize   = 0
                        , Types.iSpecDiskCount  = 0
                        , Types.iSpecNicCount   = 0
                        , Types.iSpecSpindleUse = 0
                        }

-- | Null iPolicy, and by null we mean very liberal.
nullIPolicy :: Types.IPolicy
nullIPolicy = Types.IPolicy
  { Types.iPolicyMinMaxISpecs = [Types.MinMaxISpecs
    { Types.minMaxISpecsMinSpec = nullISpec
    , Types.minMaxISpecsMaxSpec = Types.ISpec
      { Types.iSpecMemorySize = maxBound
      , Types.iSpecCpuCount   = maxBound
      , Types.iSpecDiskSize   = maxBound
      , Types.iSpecDiskCount  = C.maxDisks
      , Types.iSpecNicCount   = C.maxNics
      , Types.iSpecSpindleUse = maxBound
      }
    }]
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

-- | Default group definition.
defGroup :: Group.Group
defGroup = flip Group.setIdx 0 $
             Group.create "default" Types.defaultGroupID Types.AllocPreferred
                  [] nullIPolicy []

-- | Default group, as a (singleton) 'Group.List'.
defGroupList :: Group.List
defGroupList = Container.fromList [(Group.idx defGroup, defGroup)]

-- | Default group, as a string map.
defGroupAssoc :: Map.Map String Types.Gdx
defGroupAssoc = Map.singleton (Group.uuid defGroup) (Group.idx defGroup)

-- | Create an instance given its spec.
createInstance :: Int -> Int -> Int -> Instance.Instance
createInstance mem dsk vcpus =
  Instance.create "inst-unnamed" mem dsk [Instance.Disk dsk Nothing] vcpus
    Types.Running [] True (-1) (-1) Types.DTDrbd8 1 [] False

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
  let new_dsk = Node.availDisk node `div` 2
  in inst { Instance.mem = Node.availMem node `div` 2
          , Instance.dsk = new_dsk
          , Instance.vcpus = Node.availCpu node `div` 2
          , Instance.disks = [Instance.Disk new_dsk
                              (if Node.exclStorage node
                               then Just $ Node.fSpindlesForth node `div` 2
                               else Nothing)]
          }

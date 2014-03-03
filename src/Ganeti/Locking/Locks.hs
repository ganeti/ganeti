{-# LANGUAGE ViewPatterns #-}

{-| Ganeti lock structure

-}

{-

Copyright (C) 2014 Google Inc.

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

module Ganeti.Locking.Locks
  ( GanetiLocks(..)
  , GanetiLockAllocation
  , loadLockAllocation
  ) where

import Control.Monad ((>=>))
import Data.List (stripPrefix)
import qualified Text.JSON as J


import Ganeti.BasicTypes
import Ganeti.Errors (ResultG)
import Ganeti.JSON (readEitherString, fromJResultE)
import Ganeti.Locking.Allocation
import Ganeti.Locking.Types
import Ganeti.Types

-- | The type of Locks available in Ganeti. The order of this type
-- is the lock oder.
data GanetiLocks = BGL
                 | ClusterLockSet
                 | InstanceLockSet
                 | Instance String
                 | NodeGroupLockSet
                 | NodeGroup String
                 | NodeAllocLockSet
                 | NAL
                 | NodeResLockSet
                 | NodeRes String
                 | NodeLockSet
                 | Node String
                 deriving (Ord, Eq, Show)

-- | Provide teh String representation of a lock
lockName :: GanetiLocks -> String
lockName BGL = "cluster/BGL"
lockName ClusterLockSet = "cluster/[lockset]"
lockName InstanceLockSet = "instance/[lockset]"
lockName (Instance uuid) = "instance/" ++ uuid
lockName NodeGroupLockSet = "nodegroup/[lockset]"
lockName (NodeGroup uuid) = "nodegroup/" ++ uuid
lockName NodeAllocLockSet = "node-alloc/[lockset]"
lockName NAL = "node-alloc/NAL"
lockName NodeResLockSet = "node-res/[lockset]"
lockName (NodeRes uuid) = "node-res/" ++ uuid
lockName NodeLockSet = "node/[lockset]"
lockName (Node uuid) = "node/" ++ uuid

-- | Obtain a lock from its name.
lockFromName :: String -> J.Result GanetiLocks
lockFromName "cluster/BGL" = return BGL
lockFromName "cluster/[lockset]" = return ClusterLockSet
lockFromName "instance/[lockset]" = return InstanceLockSet
lockFromName (stripPrefix "instance/" -> Just uuid) = return $ Instance uuid
lockFromName "nodegroup/[lockset]" = return NodeGroupLockSet
lockFromName (stripPrefix "nodegroup/" -> Just uuid) = return $ NodeGroup uuid
lockFromName "node-alloc/[lockset]" = return NodeAllocLockSet
lockFromName "node-alloc/NAL" = return NAL
lockFromName "node-res/[lockset]" = return NodeResLockSet
lockFromName (stripPrefix "node-res/" -> Just uuid) = return $ NodeRes uuid
lockFromName "node/[lockset]" = return NodeLockSet
lockFromName (stripPrefix "node/" -> Just uuid) = return $ Node uuid
lockFromName n = fail $ "Unknown lock name '" ++ n ++ "'"

instance J.JSON GanetiLocks where
  showJSON = J.JSString . J.toJSString . lockName
  readJSON = readEitherString >=> lockFromName


instance Lock GanetiLocks where
  lockImplications BGL = []
  lockImplications (Instance _) = [InstanceLockSet, BGL]
  lockImplications (NodeGroup _) = [NodeGroupLockSet, BGL]
  lockImplications NAL = [NodeAllocLockSet, BGL]
  lockImplications (NodeRes _) = [NodeResLockSet, BGL]
  lockImplications (Node _) = [NodeLockSet, BGL]
  lockImplications _ = [BGL]

-- | The type of lock Allocations in Ganeti. In Ganeti, the owner of
-- locks are jobs.
type GanetiLockAllocation = LockAllocation GanetiLocks (JobId, FilePath)

-- | Load a lock allocation from disk.
loadLockAllocation :: FilePath -> ResultG GanetiLockAllocation
loadLockAllocation =
  liftIO . readFile
  >=> fromJResultE "parsing lock allocation" . J.decodeStrict

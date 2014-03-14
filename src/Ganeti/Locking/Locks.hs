{-# LANGUAGE ViewPatterns, FlexibleContexts #-}

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
  , ClientId(..)
  , GanetiLockAllocation
  , loadLockAllocation
  , writeLocksAsyncTask
  , LockLevel(..)
  , lockLevel
  ) where

import Control.Monad ((>=>), liftM)
import Control.Monad.Base (MonadBase, liftBase)
import Control.Monad.Error (MonadError, catchError)
import Data.List (stripPrefix)
import qualified Text.JSON as J


import Ganeti.BasicTypes
import Ganeti.Errors (ResultG, GanetiException)
import Ganeti.JSON (readEitherString, fromJResultE, MaybeForJSON(..))
import Ganeti.Locking.Allocation
import Ganeti.Locking.Types
import Ganeti.Logging.Lifted (MonadLog, logDebug, logEmergency)
import Ganeti.Types
import Ganeti.Utils.Atomic
import Ganeti.Utils.AsyncWorker

-- | The type of Locks available in Ganeti. The order of this type
-- is the lock oder.
data GanetiLocks = ClusterLockSet
                 | BGL
                 | InstanceLockSet
                 | Instance String
                 | NodeAllocLockSet
                 | NAL
                 | NodeGroupLockSet
                 | NodeGroup String
                 | NodeLockSet
                 | Node String
                 | NodeResLockSet
                 | NodeRes String
                 | NetworkLockSet
                 | Network String
                 deriving (Ord, Eq, Show)

-- | Provide the String representation of a lock
lockName :: GanetiLocks -> String
lockName BGL = "cluster/BGL"
lockName ClusterLockSet = "cluster/[lockset]"
lockName InstanceLockSet = "instance/[lockset]"
lockName NodeAllocLockSet = "node-alloc/[lockset]"
lockName NAL = "node-alloc/NAL"
lockName (Instance uuid) = "instance/" ++ uuid
lockName NodeGroupLockSet = "nodegroup/[lockset]"
lockName (NodeGroup uuid) = "nodegroup/" ++ uuid
lockName NodeLockSet = "node/[lockset]"
lockName (Node uuid) = "node/" ++ uuid
lockName NodeResLockSet = "node-res/[lockset]"
lockName (NodeRes uuid) = "node-res/" ++ uuid
lockName NetworkLockSet = "network/[lockset]"
lockName (Network uuid) = "network/" ++ uuid

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
lockFromName "network/[lockset]" = return NetworkLockSet
lockFromName (stripPrefix "network/" -> Just uuid) = return $ Network uuid
lockFromName n = fail $ "Unknown lock name '" ++ n ++ "'"

instance J.JSON GanetiLocks where
  showJSON = J.JSString . J.toJSString . lockName
  readJSON = readEitherString >=> lockFromName

-- | The levels, the locks belong to.
data LockLevel = LevelCluster
               | LevelInstance
               | LevelNodeAlloc
               | LevelNodeGroup
               | LevelNode
               | LevelNodeRes
               | LevelNetwork
               deriving (Eq, Show, Enum)

-- | Provide the names of the lock levels.
lockLevelName :: LockLevel -> String
lockLevelName LevelCluster = "cluster"
lockLevelName LevelInstance = "instance"
lockLevelName LevelNodeAlloc = "node-alloc"
lockLevelName LevelNodeGroup = "nodegroup"
lockLevelName LevelNode = "node"
lockLevelName LevelNodeRes = "node-res"
lockLevelName LevelNetwork = "network"

-- | Obtain a lock level from its name/
lockLevelFromName :: String -> J.Result LockLevel
lockLevelFromName "cluster" = return LevelCluster
lockLevelFromName "instance" = return LevelInstance
lockLevelFromName "node-alloc" = return LevelNodeAlloc
lockLevelFromName "nodegroup" = return LevelNodeGroup
lockLevelFromName "node" = return LevelNode
lockLevelFromName "node-res" = return LevelNodeRes
lockLevelFromName "network" = return LevelNetwork
lockLevelFromName n = fail $ "Unknown lock-level name '" ++ n ++ "'"

instance J.JSON LockLevel where
  showJSON = J.JSString . J.toJSString . lockLevelName
  readJSON = readEitherString >=> lockLevelFromName

-- | For a lock, provide its level.
lockLevel :: GanetiLocks -> LockLevel
lockLevel BGL = LevelCluster
lockLevel ClusterLockSet = LevelCluster
lockLevel InstanceLockSet = LevelInstance
lockLevel NodeAllocLockSet = LevelNodeAlloc
lockLevel NAL = LevelNodeAlloc
lockLevel (Instance _) = LevelInstance
lockLevel NodeGroupLockSet = LevelNodeGroup
lockLevel (NodeGroup _) = LevelNodeGroup
lockLevel NodeLockSet = LevelNode
lockLevel (Node _) = LevelNode
lockLevel NodeResLockSet = LevelNodeRes
lockLevel (NodeRes _) = LevelNodeRes
lockLevel NetworkLockSet = LevelNetwork
lockLevel (Network _) = LevelNetwork

instance Lock GanetiLocks where
  lockImplications BGL = [ClusterLockSet]
  lockImplications (Instance _) = [InstanceLockSet]
  lockImplications (NodeGroup _) = [NodeGroupLockSet]
  lockImplications NAL = [NodeAllocLockSet]
  lockImplications (NodeRes _) = [NodeResLockSet]
  lockImplications (Node _) = [NodeLockSet]
  lockImplications (Network _) = [NetworkLockSet]
  lockImplications _ = []

-- | A client is identified as a job id, thread id and path to its process
-- identifier file.
--
-- The JobId isn't enough to identify a client as the master daemon
-- also handles RPC calls that aren't jobs, but which use the configuration.
-- Therefore it's needed to include the identification for threads.
-- An alternative would be to use something like @Either JobId RpcCallId@.
--
-- FIXME: Python threads are only unique wrt running threads, so it's possible
-- that a new thread will get a thread id that has been used before by another
-- finished thread. Since we rely on threads releasing their locks anyway,
-- this isn't a big issue, but in the future it'd be better to have a unique
-- identifier for each operation.
data ClientId = ClientId
  { ciJobId :: Maybe JobId
  , ciThreadId :: Integer
  , ciLockFile :: FilePath
  }
  deriving (Ord, Eq, Show)

instance J.JSON ClientId where
  showJSON (ClientId jid tid lf) = J.showJSON (MaybeForJSON jid, tid, lf)
  readJSON = liftM (\(MaybeForJSON jid, tid, lf) -> ClientId jid tid lf)
             . J.readJSON

-- | The type of lock Allocations in Ganeti. In Ganeti, the owner of
-- locks are jobs.
type GanetiLockAllocation = LockAllocation GanetiLocks ClientId

-- | Load a lock allocation from disk.
loadLockAllocation :: FilePath -> ResultG GanetiLockAllocation
loadLockAllocation =
  liftIO . readFile
  >=> fromJResultE "parsing lock allocation" . J.decodeStrict

-- | Write lock allocation to disk, overwriting any previously lock
-- allocation stored there.
writeLocks :: (MonadBase IO m, MonadError GanetiException m, MonadLog m)
           => FilePath -> GanetiLockAllocation -> m ()
writeLocks fpath lockAlloc = do
  logDebug "Async. lock allocation writer: Starting write"
  toErrorBase . liftIO . atomicWriteFile fpath $ J.encode lockAlloc
  logDebug "Async. lock allocation writer: written"

-- | Construct an asynchronous worker whose action is to save the
-- current state of the lock allocation.
-- The worker's action reads the lock allocation using the given @IO@
-- action. Any inbetween changes to the file are tacitly ignored.
writeLocksAsyncTask :: FilePath -- ^ Path to the lock file
                    -> IO GanetiLockAllocation -- ^ An action to read the
                                               -- current lock allocation
                    -> ResultG (AsyncWorker ())
writeLocksAsyncTask fpath lockAllocAction = mkAsyncWorker $
  catchError (do
    locks <- liftBase lockAllocAction
    writeLocks fpath locks
  ) (logEmergency . (++) "Can't write lock allocation status: " . show)

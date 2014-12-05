{-# LANGUAGE ViewPatterns, FlexibleContexts #-}

{-| Ganeti lock structure

-}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.Locking.Locks
  ( GanetiLocks(..)
  , lockName
  , ClientType(..)
  , ClientId(..)
  , GanetiLockWaiting
  , LockLevel(..)
  , lockLevel
  ) where

import Control.Applicative ((<$>), (<*>), pure)
import Control.Monad ((>=>), liftM)
import Data.List (stripPrefix)
import System.Posix.Types (ProcessID)
import qualified Text.JSON as J

import Ganeti.JSON (readEitherString)
import Ganeti.Locking.Types
import Ganeti.Locking.Waiting
import Ganeti.Types

-- | The type of Locks available in Ganeti. The order of this type
-- is the lock oder.
data GanetiLocks = ClusterLockSet
                 | BGL
                 | InstanceLockSet
                 | Instance String
                 | NodeGroupLockSet
                 | NodeGroup String
                 | NodeLockSet
                 | Node String
                 | NodeResLockSet
                 | NodeRes String
                 | NetworkLockSet
                 | Network String
                 -- | A lock used for a transitional period when WConfd
                 -- keeps the state of the configuration, but all the
                 -- operations are still performed on the Python side.
                 | ConfigLock
                 deriving (Ord, Eq, Show)

-- | Provide the String representation of a lock
lockName :: GanetiLocks -> String
lockName BGL = "cluster/BGL"
lockName ClusterLockSet = "cluster/[lockset]"
lockName InstanceLockSet = "instance/[lockset]"
lockName (Instance uuid) = "instance/" ++ uuid
lockName NodeGroupLockSet = "nodegroup/[lockset]"
lockName (NodeGroup uuid) = "nodegroup/" ++ uuid
lockName NodeLockSet = "node/[lockset]"
lockName (Node uuid) = "node/" ++ uuid
lockName NodeResLockSet = "node-res/[lockset]"
lockName (NodeRes uuid) = "node-res/" ++ uuid
lockName NetworkLockSet = "network/[lockset]"
lockName (Network uuid) = "network/" ++ uuid
lockName ConfigLock = "cluster/config"

-- | Obtain a lock from its name.
lockFromName :: String -> J.Result GanetiLocks
lockFromName "cluster/BGL" = return BGL
lockFromName "cluster/[lockset]" = return ClusterLockSet
lockFromName "instance/[lockset]" = return InstanceLockSet
lockFromName (stripPrefix "instance/" -> Just uuid) = return $ Instance uuid
lockFromName "nodegroup/[lockset]" = return NodeGroupLockSet
lockFromName (stripPrefix "nodegroup/" -> Just uuid) = return $ NodeGroup uuid
lockFromName "node-res/[lockset]" = return NodeResLockSet
lockFromName (stripPrefix "node-res/" -> Just uuid) = return $ NodeRes uuid
lockFromName "node/[lockset]" = return NodeLockSet
lockFromName (stripPrefix "node/" -> Just uuid) = return $ Node uuid
lockFromName "network/[lockset]" = return NetworkLockSet
lockFromName (stripPrefix "network/" -> Just uuid) = return $ Network uuid
lockFromName "cluster/config" = return ConfigLock
lockFromName n = fail $ "Unknown lock name '" ++ n ++ "'"

instance J.JSON GanetiLocks where
  showJSON = J.JSString . J.toJSString . lockName
  readJSON = readEitherString >=> lockFromName

-- | The levels, the locks belong to.
data LockLevel = LevelCluster
               | LevelInstance
               | LevelNodeGroup
               | LevelNode
               | LevelNodeRes
               | LevelNetwork
               -- | A transitional level for internal configuration locks
               | LevelConfig
               deriving (Eq, Show, Enum)

-- | Provide the names of the lock levels.
lockLevelName :: LockLevel -> String
lockLevelName LevelCluster = "cluster"
lockLevelName LevelInstance = "instance"
lockLevelName LevelNodeGroup = "nodegroup"
lockLevelName LevelNode = "node"
lockLevelName LevelNodeRes = "node-res"
lockLevelName LevelNetwork = "network"
lockLevelName LevelConfig = "config"

-- | Obtain a lock level from its name/
lockLevelFromName :: String -> J.Result LockLevel
lockLevelFromName "cluster" = return LevelCluster
lockLevelFromName "instance" = return LevelInstance
lockLevelFromName "nodegroup" = return LevelNodeGroup
lockLevelFromName "node" = return LevelNode
lockLevelFromName "node-res" = return LevelNodeRes
lockLevelFromName "network" = return LevelNetwork
lockLevelFromName "config" = return LevelConfig
lockLevelFromName n = fail $ "Unknown lock-level name '" ++ n ++ "'"

instance J.JSON LockLevel where
  showJSON = J.JSString . J.toJSString . lockLevelName
  readJSON = readEitherString >=> lockLevelFromName

-- | For a lock, provide its level.
lockLevel :: GanetiLocks -> LockLevel
lockLevel BGL = LevelCluster
lockLevel ClusterLockSet = LevelCluster
lockLevel InstanceLockSet = LevelInstance
lockLevel (Instance _) = LevelInstance
lockLevel NodeGroupLockSet = LevelNodeGroup
lockLevel (NodeGroup _) = LevelNodeGroup
lockLevel NodeLockSet = LevelNode
lockLevel (Node _) = LevelNode
lockLevel NodeResLockSet = LevelNodeRes
lockLevel (NodeRes _) = LevelNodeRes
lockLevel NetworkLockSet = LevelNetwork
lockLevel (Network _) = LevelNetwork
lockLevel ConfigLock = LevelConfig

instance Lock GanetiLocks where
  lockImplications BGL = [ClusterLockSet]
  lockImplications (Instance _) = [InstanceLockSet]
  lockImplications (NodeGroup _) = [NodeGroupLockSet]
  lockImplications (NodeRes _) = [NodeResLockSet]
  lockImplications (Node _) = [NodeLockSet]
  lockImplications (Network _) = [NetworkLockSet]
  -- the ConfigLock is idependent of everything, it only synchronizes
  -- access to the configuration
  lockImplications ConfigLock = []
  lockImplications _ = []

-- | Type of entities capable of owning locks. Usually, locks are owned
-- by jobs. However, occassionally other tasks need locks (currently, e.g.,
-- to lock the configuration). These are identified by a unique name,
-- reported to WConfD as a strig.
data ClientType = ClientOther String
                | ClientJob JobId
                deriving (Ord, Eq, Show)

instance J.JSON ClientType where
  showJSON (ClientOther s) = J.showJSON s
  showJSON (ClientJob jid) = J.showJSON jid
  readJSON (J.JSString s) = J.Ok . ClientOther $ J.fromJSString s
  readJSON jids = J.readJSON jids >>= \jid -> J.Ok (ClientJob jid)

-- | A client is identified as a job id, thread id, a path to its process
-- identifier file, and its process id.
--
-- The JobId isn't enough to identify a client as the master daemon
-- also handles client calls that aren't jobs, but which use the configuration.
-- These taks are identified by a unique name, reported to WConfD as a string.
data ClientId = ClientId
  { ciIdentifier :: ClientType
  , ciLockFile :: FilePath
  , ciPid :: ProcessID
  }
  deriving (Ord, Eq, Show)

-- | Obtain the ClientID from its JSON representation.
clientIdFromJSON :: J.JSValue -> J.Result ClientId
clientIdFromJSON (J.JSArray [clienttp, J.JSString lf, pid]) =
  ClientId <$> J.readJSON clienttp <*> pure (J.fromJSString lf)
           <*> liftM fromIntegral (J.readJSON pid :: J.Result Integer)
clientIdFromJSON x = J.Error $ "malformed client id: " ++ show x

instance J.JSON ClientId where
  showJSON (ClientId client lf pid)
    = J.showJSON (client, lf, fromIntegral pid :: Integer)
  readJSON = clientIdFromJSON

-- | The type of lock Allocations in Ganeti. In Ganeti, the owner of
-- locks are jobs.
type GanetiLockWaiting = LockWaiting GanetiLocks ClientId Integer

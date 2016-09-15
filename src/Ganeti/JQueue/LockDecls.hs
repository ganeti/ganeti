{-| Job-specific static lock declarations.

-}

{-

Copyright (C) 2016 Google Inc.
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

module Ganeti.JQueue.LockDecls
    (staticWeight) where

import Data.List (foldl')
import Data.Maybe (isNothing, fromMaybe, catMaybes, isJust, fromJust)
import Data.Map (Map)
import qualified Data.Map as Map
import Data.Set (Set)
import qualified Data.Set as Set

import Ganeti.BasicTypes
import Ganeti.Config (getInstance, getNode, getGroup, instNodes)
import qualified Ganeti.Constants as C
import Ganeti.Errors
import Ganeti.Objects (ConfigData, nodeName, instName, groupName)
import qualified Ganeti.Objects.Instance as ObjInst
import Ganeti.OpCodes
import Ganeti.Types

-- | The different levels for locks to be acquired at.
data StaticLockLevel = Cluster
                     | NodeGroup
                     | Instance
                     | Node
                     | NodeRes
                     | Network
                     deriving (Show, Ord, Eq)

-- | The different types of locks that can be acquired.
data StaticLockType = None
                    | Shared (Set String)
                    | UnknownShared
                    | AllShared
                    | Exclusive (Set String)
                    | UnknownExclusive
                    | AllExclusive
                    deriving (Show, Eq, Ord)

-- | Record containing the state of locks for each level, when possible.
data StaticLocks = StaticLocks { sNodeGroupLock :: Maybe StaticLockType
                               , sInstanceLock :: Maybe StaticLockType
                               , sNodeLock :: Maybe StaticLockType
                               , sNodeResLock :: Maybe StaticLockType
                               , sNetworkLock :: Maybe StaticLockType
                               }

emptyLocks :: StaticLocks
emptyLocks = StaticLocks { sNodeGroupLock = Just None
                         , sInstanceLock = Just None
                         , sNodeLock = Just None
                         , sNodeResLock = Just None
                         , sNetworkLock = Just None
                         }

-- | Merge two lock types together in ascending order, in case of Exclusive or
-- Shared lock conflict, merge the two resources.
mergeLocks :: StaticLockType -> StaticLockType -> StaticLockType
mergeLocks x y
  | Exclusive ex1 <- x,
    Exclusive ex2 <- y = Exclusive (Set.union ex1 ex2)
  | Shared sh1 <- x,
    Shared sh2 <- y = Shared (Set.union sh1 sh2)
  | x > y = x
  | otherwise = y

-- | Assign a severity arbitrary weight to each lock type union.
computeLocks :: StaticLockType -> StaticLockType -> Double
computeLocks None _ = C.staticLockNoWeight
computeLocks (Shared _) None = C.staticLockDegradeWeight
computeLocks (Shared xs) (Exclusive ys)
  | Set.null $ Set.intersection xs ys = C.staticLockDegradeWeight
  | otherwise = C.staticLockSureBlockWeight
computeLocks (Shared _) UnknownExclusive = C.staticLockMaybeBlockWeight
computeLocks (Shared _) AllExclusive = C.staticLockSureBlockWeight
computeLocks (Shared _) _ = C.staticLockNoWeight
computeLocks UnknownShared (Exclusive _) = C.staticLockMaybeBlockWeight
computeLocks UnknownShared UnknownExclusive = C.staticLockMaybeBlockWeight
computeLocks UnknownShared AllExclusive = C.staticLockSureBlockWeight
computeLocks UnknownShared _ = C.staticLockDegradeWeight
computeLocks AllShared (Exclusive _) = C.staticLockSureBlockWeight
computeLocks AllShared UnknownExclusive = C.staticLockSureBlockWeight
computeLocks AllShared AllExclusive = C.staticLockSureBlockWeight
computeLocks AllShared _ = C.staticLockDegradeWeight
computeLocks (Exclusive _) None = C.staticLockHeavyDegradeWeight
computeLocks (Exclusive _) UnknownShared = C.staticLockMaybeBlockWeight
computeLocks (Exclusive _) UnknownExclusive = C.staticLockMaybeBlockWeight
computeLocks (Exclusive _) AllShared = C.staticLockSureBlockWeight
computeLocks (Exclusive _) AllExclusive = C.staticLockSureBlockWeight
computeLocks (Exclusive xs) (Shared ys)
  | Set.null $ Set.intersection xs ys = C.staticLockHeavyDegradeWeight
  | otherwise = C.staticLockSureBlockWeight
computeLocks (Exclusive xs) (Exclusive ys)
  | Set.null $ Set.intersection xs ys = C.staticLockHeavyDegradeWeight
  | otherwise = C.staticLockSureBlockWeight
computeLocks UnknownExclusive None = C.staticLockHeavyDegradeWeight
computeLocks UnknownExclusive AllShared = C.staticLockSureBlockWeight
computeLocks UnknownExclusive AllExclusive = C.staticLockSureBlockWeight
computeLocks UnknownExclusive _ = C.staticLockMaybeBlockWeight
computeLocks AllExclusive None = C.staticLockHeavyDegradeWeight
computeLocks AllExclusive _ = C.staticLockSureBlockWeight

-- | Check if the opcode type requires the Big Ganeti Lock or not.
hasBGL :: OpCode -> Bool
hasBGL OpNodeAdd{} = True
hasBGL OpNodeRemove{} = True
hasBGL OpClusterActivateMasterIp{} = True
hasBGL OpClusterDeactivateMasterIp{} = True
hasBGL OpClusterDestroy{} = True
hasBGL OpClusterPostInit{} = True
hasBGL OpClusterRename{} = True
hasBGL OpTestAllocator{} = True
hasBGL _ = False

-- | Convert a TagKind to a StaticLockLevel type.
tagKindToStaticLockLevel :: TagKind -> StaticLockLevel
tagKindToStaticLockLevel TagKindCluster = Cluster
tagKindToStaticLockLevel TagKindGroup = NodeGroup
tagKindToStaticLockLevel TagKindInstance = Instance
tagKindToStaticLockLevel TagKindNode = Node
tagKindToStaticLockLevel TagKindNetwork = Network


-- | The three to<resource>Lock functions are wrappers used to acquire a
-- common resource parameter (instance, node, or group name) and convert it to
-- the appropriate LockType using maybeKnownLock as a common utility function.
-- The function is called with either UnknownShared or UnknownExclusive
-- LockTypes, which are converted respectively to their Shared or Exclusive
-- lock declaration. If the resource data is missing due to config errors,
-- then we assume the worst case scenario of an Unknown lock being requested
-- instead.

-- | Convert an ErrorResult to the appropriate StaticLockType if possible.
maybeKnownLock :: StaticLockType -> ErrorResult String -> StaticLockType
maybeKnownLock UnknownShared (Ok x) = Shared (Set.singleton x)
maybeKnownLock UnknownExclusive (Ok x) = Exclusive (Set.singleton x)
maybeKnownLock lockType _ = lockType

-- | Convert an instance resource name to its appropriate lock.
toInstanceLock :: ConfigData -> StaticLockType -> String -> StaticLockType
toInstanceLock cfg lock = maybeKnownLock lock
                          . instNameWrapper
                          . getInstance cfg
  where instNameWrapper :: ErrorResult ObjInst.Instance -> ErrorResult String
        instNameWrapper (Ok inst) = maybeToError "Instance name not found"
                                    . instName $ inst
        instNameWrapper (Bad x) = Bad x

-- | Convert a node resource name to its appropriate lock.
toNodeLock :: ConfigData -> StaticLockType -> NonEmptyString -> StaticLockType
toNodeLock cfg lock = maybeKnownLock lock
                      . fmap nodeName
                      . getNode cfg
                      . fromNonEmpty

-- | Convert a node group resource name to its appropriate lock.
toGroupLock :: ConfigData -> StaticLockType -> NonEmptyString -> StaticLockType
toGroupLock cfg lock = maybeKnownLock lock
                       . fmap groupName
                       . getGroup cfg
                       . fromNonEmpty

-- | Obtain the node set (primary and secondaries) from an opcode's instance.
toInstanceNodeSet :: ConfigData -> OpCode -> Set String
toInstanceNodeSet cfg = toNodes
                        . fmap (instNodes cfg)
                        . getInstance cfg
                        . opInstanceName
  where toNodes :: ErrorResult (Set String) -> Set String
        toNodes (Ok nodes) = nodes
        toNodes (Bad _) = Set.empty

-- | Wrapper function for Tag opcode lock declarations.
tagLocks :: ConfigData
         -> OpCode
         -> StaticLockType
         -> StaticLocks
         -> StaticLocks
tagLocks cfg op lock currLocks =
  let resource = tagKindToStaticLockLevel $ opKind op
      tagName = fromMaybe "" $ opTagsGetName op
      groupLock = (toGroupLock cfg lock) . fromJust . mkNonEmpty $ tagName
      instanceLock = toInstanceLock cfg lock tagName
      nodeLock = (toNodeLock cfg lock) . fromJust . mkNonEmpty $ tagName
      locks
        | resource == NodeGroup = currLocks { sNodeGroupLock = Just groupLock
                                            , sInstanceLock = Just None
                                            , sNodeLock = Just None
                                            , sNetworkLock = Just None
                                            }
        | resource == Instance = currLocks { sNodeGroupLock = Just None
                                           , sInstanceLock = Just instanceLock
                                           , sNodeLock = Just None
                                           , sNetworkLock = Just None
                                           }
        | resource == Node = currLocks { sNodeGroupLock = Just None
                                       , sInstanceLock = Just None
                                       , sNodeLock = Just nodeLock
                                       , sNetworkLock = Just None
                                       }
        | resource == Network = currLocks { sNodeGroupLock = Just None
                                          , sInstanceLock = Just None
                                          , sNodeLock = Just None
                                          , sNetworkLock = Just lock
                                          }
        | otherwise = emptyLocks
      in locks

-- | Check if the given opcode has the iallocator parameter enabled.
hasIAllocator :: OpCode -> Bool
hasIAllocator = isJust . opIallocator

-- | Declare the instance level locks for the given opcode.
instanceLocks :: ConfigData -> OpCode -> StaticLocks -> StaticLocks
instanceLocks cfg op s =
  let instanceLock = toInstanceLock cfg
      iName = opInstanceName op
      mkLock st l = st { sInstanceLock = Just l }
      defaultExclusive = instanceLock UnknownExclusive iName
  in case op of
       OpInstanceCreate{} -> mkLock s defaultExclusive
       OpInstanceRecreateDisks{} -> mkLock s defaultExclusive
       OpInstanceGrowDisk{} -> mkLock s defaultExclusive
       OpInstanceActivateDisks{} -> mkLock s defaultExclusive
       OpInstanceRemove{} -> mkLock s defaultExclusive
       OpInstanceMove{} -> mkLock s defaultExclusive
       OpInstanceChangeGroup{} -> mkLock s defaultExclusive
       OpInstanceSetParams{} -> mkLock s defaultExclusive
       OpBackupPrepare{} -> mkLock s defaultExclusive
       OpBackupExport{} -> mkLock s defaultExclusive
       OpInstanceStartup{} -> mkLock s defaultExclusive
       OpInstanceShutdown{} -> mkLock s defaultExclusive
       OpInstanceReboot{} -> mkLock s defaultExclusive
       OpInstanceFailover{} -> mkLock s defaultExclusive
       OpInstanceMigrate{} -> mkLock s defaultExclusive
       OpInstanceReplaceDisks{} -> mkLock s defaultExclusive
       OpInstanceRename{} -> let newName = fromNonEmpty $ opNewName op
                                 newLock = Exclusive $ Set.singleton newName
                             in mkLock s $ mergeLocks newLock defaultExclusive
       OpNodeSetParams{} -> if isNothing $ opSecondaryIp op
                               then mkLock s None
                               else mkLock s UnknownShared
       OpClusterRepairDiskSizes{} ->
         let instanceList = map fromNonEmpty $ opInstances op
             lock
               | null instanceList = AllExclusive
               | otherwise = foldl' mergeLocks None
                           . map (instanceLock UnknownExclusive) $ instanceList
         in mkLock s lock
       OpInstanceConsole{} -> mkLock s . instanceLock UnknownShared $ iName
       _ -> s


-- | Declare the node and node-res level locks for the given opcode.
nodeLocks :: ConfigData -> OpCode -> StaticLocks -> StaticLocks
nodeLocks cfg op s =
  let nName = opNodeName op
      nodeLock = toNodeLock cfg
      nodeLockList lockType = foldl' mergeLocks None . map (nodeLock lockType)
      mkNodeLock st l = st { sNodeLock = Just l }
      mkNodeResLock st l = st { sNodeResLock = Just l }
      mkBothLocks st l = mkNodeResLock (mkNodeLock st l) l
      defaultExclusive = nodeLock UnknownExclusive nName
      isOpportunistic = opOpportunisticLocking op
      instNodeSet = toInstanceNodeSet cfg op
      migrateLock
        | hasIAllocator op = UnknownExclusive
        | Set.null instNodeSet = AllExclusive
        | otherwise = Exclusive (fromMaybe instNodeSet
                                 . fmap ((flip Set.insert) instNodeSet
                                         . fromNonEmpty)
                                 . opTargetNode $ op)
      mergeLockList x y
        | null y = AllShared
        | otherwise = foldl' mergeLocks None $ map x y
      mergeNodeLocks = mergeLockList (nodeLock UnknownShared) $ opNodes op
  in case op of
       OpGroupAssignNodes{} -> mkNodeLock s . nodeLockList UnknownExclusive $
                               opReqNodes op
       OpRestrictedCommand{} -> mkNodeLock s . nodeLockList UnknownShared $
                                opReqNodes op
       OpRepairCommand{} -> mkNodeLock s defaultExclusive
       OpNodeModifyStorage{} -> mkNodeLock s defaultExclusive
       OpRepairNodeStorage{} -> mkNodeLock s defaultExclusive
       OpInstanceMigrate{} -> mkBothLocks s migrateLock
       OpInstanceFailover{} -> mkBothLocks s migrateLock
       OpInstanceMultiAlloc{} ->
         let lock
               | hasIAllocator op && (not isOpportunistic) = AllShared
               | otherwise = UnknownShared
         in mkBothLocks s lock
       OpInstanceCreate{} ->
         let nodeList = catMaybes [opPnode op, opSnode op]
             lock
               | not . null $ nodeList = nodeLockList UnknownExclusive nodeList
               | hasIAllocator op && (not isOpportunistic) = AllExclusive
               | otherwise = UnknownExclusive
         in mkBothLocks s lock
       OpNodeSetParams{} ->
         let mightDemote =
               Just True `elem` [(fmap not) . opMasterCandidate $ op,
                                 opOffline op, opDrained op,
                                 (fmap not) . opMasterCapable $ op]
             lock
               | opAutoPromote op && mightDemote = AllExclusive
               | otherwise = defaultExclusive
         in mkBothLocks s lock
       OpNodeMigrate{} -> mkNodeLock s . nodeLock UnknownShared $ nName
       OpNodeQueryvols{} -> mkNodeLock s mergeNodeLocks
       OpNodeQueryStorage{} -> mkNodeLock s mergeNodeLocks
       OpClusterRepairDiskSizes{} ->
         let instanceList = map fromNonEmpty $ opInstances op
             lock
               | null instanceList = AllShared
               | otherwise = UnknownShared
         in mkNodeResLock s lock
       _ -> s

-- | Declare the group level locks for the given opcode.
groupLocks :: ConfigData -> OpCode -> StaticLocks -> StaticLocks
groupLocks cfg op s =
  let gName = opGroupName op
      groupLock = toGroupLock cfg
      mkLock st l = st { sNodeGroupLock = Just l }
      defaultExclusive = groupLock UnknownExclusive gName
      defaultShared = groupLock UnknownShared gName
  in case op of
       OpGroupAdd{} -> mkLock s defaultExclusive
       OpGroupSetParams{} -> mkLock s defaultExclusive
       OpGroupRemove{} -> mkLock s defaultExclusive
       OpGroupRename{} -> mkLock s defaultExclusive
       OpNetworkDisconnect{} -> mkLock s defaultExclusive
       OpNetworkConnect{} -> mkLock s defaultShared
       OpClusterVerifyGroup{} -> mkLock s defaultShared
       OpInstanceReplaceDisks{} -> if hasIAllocator op
                                      then mkLock s UnknownShared
                                      else mkLock s None
       OpInstanceCreate{} ->
         let gLock
              | sNodeLock s == Just AllExclusive = AllShared
              | otherwise = UnknownShared
         in mkLock s gLock
       OpClusterVerifyDisks{} ->
         let maybeGroupLock =
               maybe AllShared (groupLock UnknownShared) (opOptGroupName op)
         in mkLock s maybeGroupLock
       _ -> s

-- | Declare the network level locks for the given opcode.
networkLocks :: OpCode -> StaticLocks -> StaticLocks
networkLocks op s =
  let exclusiveLock =
        Exclusive (Set.singleton . fromNonEmpty . opNetworkName $ op)
      sharedLock =
        Shared (Set.singleton . fromNonEmpty . opNetworkName $ op)
      mkLock st l = st { sNetworkLock = Just l }
  in case op of
       OpNetworkAdd{} -> mkLock s exclusiveLock
       OpNetworkRemove{} -> mkLock s exclusiveLock
       OpNetworkSetParams{} -> mkLock s exclusiveLock
       OpNetworkConnect{} -> mkLock s sharedLock
       _ -> s


-- | Function calculating the complete lock declaration for each opcode type.
staticLocks :: ConfigData -> OpCode -> Map StaticLockLevel StaticLockType
staticLocks cfg op =
  let lmap = lockDecl op
      locks =
        case op of
          OpTagsGet{ opUseLocking = True } -> tagLocks cfg op UnknownShared lmap
          OpTagsSet{} -> tagLocks cfg op UnknownExclusive lmap
          OpTagsDel{} -> tagLocks cfg op UnknownExclusive lmap
          OpInstanceQueryData{ opUseLocking = False
                             , opStatic = True
                             } -> emptyLocks
          _ -> groupLocks cfg op . nodeLocks cfg op . instanceLocks cfg op
               . networkLocks op $ lmap
  in staticLocksToMap locks

staticLocksToMap :: StaticLocks -> Map StaticLockLevel StaticLockType
staticLocksToMap locks =
  Map.fromList [(NodeGroup, getLock . sNodeGroupLock $ locks)
               ,(Instance, getLock . sInstanceLock $ locks)
               ,(Node, getLock . sNodeLock $ locks)
               ,(NodeRes, getLock . sNodeResLock $ locks)
               ,(Network, getLock . sNetworkLock $ locks)
               ]
  where getLock :: Maybe StaticLockType -> StaticLockType
        getLock (Just x) = x
        getLock Nothing = AllExclusive


-- | Static declaration of locks for each opcode. In case of an empty value
-- that needs to be filled dynamically at runtime by the staticLocks function,
-- we use a Nothing.
lockDecl :: OpCode -> StaticLocks
lockDecl op =
  let noLockExcept = emptyLocks
      lockA = noLockExcept { sNodeGroupLock = Nothing
                           , sInstanceLock = Just UnknownExclusive
                           }
      lockB = noLockExcept { sNodeGroupLock = Just AllShared
                           , sInstanceLock = Just UnknownShared
                           , sNodeLock = Just UnknownShared
                           }
      lockC = noLockExcept { sNodeGroupLock = Nothing
                           , sInstanceLock = Nothing
                           , sNodeLock = Nothing
                           , sNetworkLock = Nothing
                           }
      lockD = noLockExcept { sNodeGroupLock = Just UnknownShared
                           , sInstanceLock = Nothing
                           , sNodeLock = Just UnknownExclusive
                           , sNodeResLock = Just UnknownExclusive
                           }
      lockE = noLockExcept { sInstanceLock = Nothing
                           , sNodeLock = Just UnknownExclusive
                           , sNodeResLock = Just UnknownExclusive
                           }
      lockF = noLockExcept { sInstanceLock = Nothing
                           , sNodeLock = Just UnknownExclusive
                           }
      lockG = noLockExcept { sNodeGroupLock = Just AllShared
                           , sNetworkLock = Nothing
                           }
      lockH = noLockExcept { sInstanceLock = Nothing
                           , sNodeLock = Nothing
                           , sNodeResLock = Nothing
                           }
  in case op of
       OpGroupAdd{} -> noLockExcept { sNodeGroupLock = Nothing }
       OpGroupRename{} -> noLockExcept { sNodeGroupLock = Nothing }
       OpGroupRemove{} -> noLockExcept { sNodeGroupLock = Nothing }
       OpClusterVerifyDisks{} -> noLockExcept { sNodeGroupLock = Nothing }
       OpGroupAssignNodes{} ->
         noLockExcept { sNodeGroupLock = Just UnknownExclusive
                      , sNodeLock = Nothing
                      }
       OpGroupSetParams{} -> lockA
       OpNetworkDisconnect{} -> lockA
       OpGroupEvacuate{} -> lockB
       OpGroupVerifyDisks{} -> lockB
       OpInstanceCreate{} -> noLockExcept { sNodeGroupLock = Nothing
                                          , sInstanceLock = Nothing
                                          , sNodeLock = Nothing
                                          , sNodeResLock = Nothing
                                          }
       OpTagsGet{} -> lockC
       OpTagsSet{} -> lockC
       OpTagsDel{} -> lockC
       OpInstanceRecreateDisks{} -> lockD
       OpInstanceSetParams{} -> lockD
       OpInstanceGrowDisk{} -> lockE
       OpInstanceRemove{} -> lockE
       OpInstanceMultiAlloc{} -> noLockExcept { sNodeLock = Nothing
                                              , sNodeResLock = Nothing
                                              }
       OpInstanceReplaceDisks{} ->
         noLockExcept { sNodeGroupLock = Nothing
                      , sInstanceLock = Nothing
                      , sNodeLock = Just UnknownExclusive
                      , sNodeResLock = Just UnknownExclusive
                      }
       OpInstanceActivateDisks{} -> lockF
       OpInstanceDeactivateDisks{} -> lockF
       OpInstanceMove{} -> noLockExcept { sInstanceLock = Nothing
                                        , sNodeLock = Just AllShared
                                        , sNodeResLock = Just AllShared
                                        }
       OpInstanceChangeGroup{} ->
         noLockExcept { sNodeGroupLock = Just AllExclusive
                      , sInstanceLock = Nothing
                      , sNodeLock = Just AllExclusive
                      }
       OpNetworkAdd{} -> lockG
       OpNetworkRemove{} -> lockG
       OpNetworkSetParams{} -> noLockExcept { sNetworkLock = Nothing }
       OpNetworkConnect{} ->
         noLockExcept { sNodeGroupLock = Nothing
                      , sInstanceLock = Just UnknownShared
                      , sNetworkLock = Nothing
                      }
       OpInstanceQueryData{} ->
         noLockExcept { sNodeGroupLock = Just UnknownShared
                      , sInstanceLock = Just AllShared
                      , sNodeLock = Just UnknownShared
                      , sNodeResLock = Just UnknownShared
                      }
       OpRestrictedCommand{} -> noLockExcept { sNodeLock = Nothing }
       OpRepairCommand{} -> noLockExcept { sNodeLock = Nothing }
       OpNodeModifyStorage{} -> noLockExcept { sNodeLock = Nothing }
       OpNodeQueryvols{} -> noLockExcept { sNodeLock = Nothing }
       OpNodeQueryStorage{} -> noLockExcept { sNodeLock = Nothing }
       OpRepairNodeStorage{} -> noLockExcept { sNodeLock = Nothing }
       OpNodeMigrate{} -> noLockExcept { sNodeLock = Nothing }
       OpInstanceFailover{} -> lockH
       OpInstanceMigrate{} -> lockH
       OpNodeSetParams{} -> lockH
       OpNodeEvacuate{} -> noLockExcept { sNodeGroupLock = Just UnknownShared
                                        , sInstanceLock = Just UnknownShared
                                        , sNodeLock = Just UnknownShared
                                        }
       OpBackupPrepare{} -> noLockExcept { sInstanceLock = Nothing }
       OpBackupExport{} -> noLockExcept { sInstanceLock = Nothing
                                        , sNodeLock = Just AllExclusive
                                        }
       OpBackupRemove{} -> noLockExcept { sNodeLock = Just AllExclusive }
       OpClusterRenewCrypto{} -> noLockExcept { sNodeLock = Just AllExclusive }
       OpOobCommand{} -> noLockExcept { sNodeLock = Just AllExclusive }
       OpTestDelay{} -> noLockExcept { sNodeLock = Just UnknownExclusive }
       OpTestJqueue{} -> noLockExcept { sNodeLock = Just UnknownExclusive }
       OpClusterRedistConf{} -> noLockExcept { sNodeLock = Just AllShared }
       OpClusterRepairDiskSizes{} -> noLockExcept { sInstanceLock = Nothing
                                                  , sNodeResLock = Nothing
                                                  }
       OpClusterSetParams{} -> noLockExcept { sNodeGroupLock = Just AllShared
                                            , sInstanceLock = Just AllShared
                                            , sNodeLock = Just AllShared
                                            }
       OpClusterVerifyConfig{} -> noLockExcept { sNodeGroupLock = Just AllShared
                                               , sInstanceLock = Just AllShared
                                               , sNodeLock = Just AllShared
                                               , sNodeResLock = Just AllShared
                                               , sNetworkLock = Just AllShared
                                               }
       OpClusterVerifyGroup{} ->
         noLockExcept { sNodeGroupLock = Nothing
                      , sInstanceLock = Just UnknownShared
                      , sNodeLock = Just UnknownShared
                      }
       OpInstanceStartup{} ->
         noLockExcept { sInstanceLock = Nothing
                      , sNodeResLock = Just UnknownExclusive
                      }
       OpInstanceShutdown{} -> noLockExcept { sInstanceLock = Nothing }
       OpInstanceReboot{} -> noLockExcept { sInstanceLock = Nothing }
       OpInstanceConsole{} -> noLockExcept { sInstanceLock = Nothing }
       OpInstanceRename{} -> noLockExcept { sInstanceLock = Nothing }
       _ -> emptyLocks

-- | Calculate the static weight of a job's locks in relation to the runtime
-- list of jobs.
staticWeight :: ConfigData -> Maybe OpCode -> [OpCode] -> Double
staticWeight cfg op runningOps
  | isNothing op || (hasBGL . fromJust $ op) = maxValue + base
  | otherwise = -- For each level in the StaticLocks dictionary, we fold
                -- and sum over the greatest lock values with the given opcode.
      Map.foldlWithKey' (\acc k v -> acc + sumLocks k v) base opWeight
  where sumLocks x y = foldl' max C.staticLockNoWeight $
                       map (computeLocks y . mLookup x . staticLocks cfg)
                       runningOps
        mLookup k v = fromMaybe None (Map.lookup k v)
        opWeight = staticLocks cfg (fromJust op)
        base = C.staticLockBaseWeight
        maxValue = C.staticLockSureBlockWeight * 5 -- Worst case scenario
                                                   -- multiplied by all 5 lock
                                                   -- levels

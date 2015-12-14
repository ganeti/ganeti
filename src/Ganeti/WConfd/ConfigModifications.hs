{-# LANGUAGE TemplateHaskell, NoMonomorphismRestriction, FlexibleContexts #-}

{-|  The WConfd functions for direct configuration manipulation

This module contains the client functions exported by WConfD for
specific configuration manipulation.

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

module Ganeti.WConfd.ConfigModifications where

import Control.Applicative ((<$>))
import Control.Lens (_2)
import Control.Lens.Getter ((^.))
import Control.Lens.Setter ((.~), (%~))
import qualified Data.ByteString.UTF8 as UTF8
import Control.Lens.Traversal (mapMOf)
import Control.Monad (unless, when, forM_, foldM, liftM2)
import Control.Monad.Error (throwError, MonadError)
import Control.Monad.IO.Class (liftIO)
import Control.Monad.Trans.State (StateT, get, put, modify,
                                  runStateT, execStateT)
import Data.Foldable (fold, foldMap)
import Data.List (elemIndex)
import Data.Maybe (isJust, maybeToList, fromMaybe, fromJust)
import Language.Haskell.TH (Name)
import System.Time (getClockTime, ClockTime)
import Text.Printf (printf)
import qualified Data.Map as M
import qualified Data.Set as S

import Ganeti.BasicTypes (GenericResult(..), genericResult, toError)
import Ganeti.Constants (lastDrbdPort)
import Ganeti.Errors (GanetiException(..))
import Ganeti.JSON (Container, GenericContainer(..), alterContainerL
                   , lookupContainer, MaybeForJSON(..), TimeAsDoubleJSON(..))
import Ganeti.Locking.Locks (ClientId, ciIdentifier)
import Ganeti.Logging.Lifted (logDebug, logInfo)
import Ganeti.Objects
import Ganeti.Objects.Lens
import Ganeti.Types (AdminState, AdminStateSource)
import Ganeti.WConfd.ConfigState (ConfigState, csConfigData, csConfigDataL)
import Ganeti.WConfd.Monad (WConfdMonad, modifyConfigWithLock
                           , modifyConfigAndReturnWithLock)
import qualified Ganeti.WConfd.TempRes as T

type DiskUUID = String
type InstanceUUID = String
type NodeUUID = String

-- * accessor functions

getInstanceByUUID :: ConfigState
                  -> InstanceUUID
                  -> GenericResult GanetiException Instance
getInstanceByUUID cs uuid = lookupContainer
  (Bad . ConfigurationError $
    printf "Could not find instance with UUID %s" uuid)
  (UTF8.fromString uuid)
  (configInstances . csConfigData $ cs)

-- * getters

-- | Gets all logical volumes in the cluster
getAllLVs :: ConfigState -> S.Set String
getAllLVs = S.fromList . concatMap getLVsOfDisk . M.elems
          . fromContainer . configDisks  . csConfigData
  where convert (LogicalVolume lvG lvV) = lvG ++ "/" ++ lvV
        getDiskLV :: Disk -> Maybe String
        getDiskLV disk = case diskLogicalId disk of
          Just (LIDPlain lv) -> Just (convert lv)
          _ -> Nothing
        getLVsOfDisk :: Disk -> [String]
        getLVsOfDisk disk = maybeToList (getDiskLV disk)
                          ++ concatMap getLVsOfDisk (diskChildren disk)

-- | Gets the ids of nodes, instances, node groups,
--   networks, disks, nics, and the cluster itself.
getAllIDs :: ConfigState -> S.Set String
getAllIDs cs =
  let lvs = getAllLVs cs
      keysFromC :: GenericContainer a b -> [a]
      keysFromC = M.keys . fromContainer

      valuesFromC :: GenericContainer a b -> [b]
      valuesFromC = M.elems . fromContainer

      instKeys = keysFromC . configInstances . csConfigData $ cs
      nodeKeys = keysFromC . configNodes . csConfigData $ cs
      
      instValues = map uuidOf . valuesFromC
                 . configInstances . csConfigData $ cs
      nodeValues = map uuidOf . valuesFromC . configNodes . csConfigData $ cs
      nodeGroupValues = map uuidOf . valuesFromC
                      . configNodegroups . csConfigData $ cs
      networkValues = map uuidOf . valuesFromC
                    . configNetworks . csConfigData $ cs
      disksValues = map uuidOf . valuesFromC . configDisks . csConfigData $ cs

      nics = map nicUuid . concatMap instNics
           . valuesFromC . configInstances . csConfigData $ cs

      cluster = uuidOf . configCluster . csConfigData $ cs
  in S.union lvs . S.fromList $ map UTF8.toString instKeys
       ++ map UTF8.toString nodeKeys
       ++ instValues
       ++ nodeValues
       ++ nodeGroupValues
       ++ networkValues
       ++ disksValues
       ++ map UTF8.toString nics ++ [cluster]

getAllMACs :: ConfigState -> S.Set String
getAllMACs = S.fromList . map nicMac . concatMap instNics . M.elems
           . fromContainer . configInstances . csConfigData

-- | Checks if the two objects are equal,
-- excluding timestamps. The serial number of
-- current must be one greater than that of target.
--
-- If this is true, it implies that the update RPC
-- updated the config, but did not successfully return.
isIdentical :: (Eq a, SerialNoObjectL a, TimeStampObjectL a)
            => ClockTime
            -> a
            -> a
            -> Bool
isIdentical now target current = (mTimeL .~ now $ current) ==
  ((serialL %~ (+1)) . (mTimeL .~ now) $ target)

-- | Checks if the two objects given have the same serial number
checkSerial :: SerialNoObject a => a -> a -> GenericResult GanetiException ()
checkSerial target current = if serialOf target == serialOf current
  then Ok ()
  else Bad . ConfigurationError $ printf
    "Configuration object updated since it has been read: %d != %d"
    (serialOf current) (serialOf target)

-- | Updates an object present in a container.
-- The presence of the object in the container
-- is determined by the uuid of the object.
--
-- A check that serial number of the
-- object is consistent with the serial number
-- of the object in the container is performed.
--
-- If the check passes, the object's serial number
-- is incremented, and modification time is updated,
-- and then is inserted into the container.
replaceIn :: (UuidObject a, TimeStampObjectL a, SerialNoObjectL a)
          => ClockTime
          -> a
          -> Container a
          -> GenericResult GanetiException (Container a)
replaceIn now target = alterContainerL (UTF8.fromString (uuidOf target)) extract
  where extract Nothing = Bad $ ConfigurationError
          "Configuration object unknown"
        extract (Just current) = do
          checkSerial target current
          return . Just . (serialL %~ (+1)) . (mTimeL .~ now) $ target

-- | Utility fuction that combines the two
-- possible actions that could be taken when
-- given a target.
--
-- If the target is identical to the current
-- value, we return the modification time of
-- the current value, and not change the config.
--
-- If not, we update the config.
updateConfigIfNecessary :: (Monad m, MonadError GanetiException m, Eq a,
                            UuidObject a, SerialNoObjectL a, TimeStampObjectL a)
                        => ClockTime
                        -> a
                        -> (ConfigState -> Container a)
                        -> (ConfigState
                           -> m ((Int, ClockTime), ConfigState))
                        -> ConfigState
                        -> m ((Int, ClockTime), ConfigState)
updateConfigIfNecessary now target getContainer f cs = do
  let container = getContainer cs
  current <- lookupContainer (toError . Bad . ConfigurationError $
    "Configuraton object unknown")
    (UTF8.fromString (uuidOf target))
    container
  if isIdentical now target current
    then return ((serialOf current, mTimeOf current), cs)
    else f cs

-- * UUID config checks

-- | Checks if the config has the given UUID
checkUUIDpresent :: UuidObject a
                 => ConfigState
                 -> a
                 -> Bool
checkUUIDpresent cs a = uuidOf a `S.member` getAllIDs cs

-- | Checks if the given UUID is new (i.e., no in the config)
checkUniqueUUID :: UuidObject a
                => ConfigState
                -> a
                -> Bool
checkUniqueUUID cs a = not $ checkUUIDpresent cs a

-- * RPC checks

-- | Verifications done before adding an instance.
-- Currently confirms that the instance's macs are not
-- in use, and that the instance's UUID being
-- present (or not present) in the config based on
-- weather the instance is being replaced (or not).
--
-- TODO: add more verifications to this call;
-- the client should have a lock on the name of the instance.
addInstanceChecks :: Instance
                  -> Bool
                  -> ConfigState
                  -> GenericResult GanetiException ()
addInstanceChecks inst replace cs = do
  let macsInUse = S.fromList (map nicMac (instNics inst))
                  `S.intersection` getAllMACs cs
  unless (S.null macsInUse) . Bad . ConfigurationError $ printf
    "Cannot add instance %s; MAC addresses %s already in use"
    (show $ instName inst) (show macsInUse)
  if replace
    then do
      let check = checkUUIDpresent cs inst
      unless check . Bad . ConfigurationError $ printf
             "Cannot add %s: UUID %s already in use"
             (show $ instName inst) (UTF8.toString (instUuid inst))
    else do
      let check = checkUniqueUUID cs inst
      unless check . Bad . ConfigurationError $ printf
             "Cannot replace %s: UUID %s not present"
             (show $ instName inst) (UTF8.toString (instUuid inst))

addDiskChecks :: Disk
              -> Bool
              -> ConfigState
              -> GenericResult GanetiException ()
addDiskChecks disk replace cs =
  if replace
    then
      unless (checkUUIDpresent cs disk) . Bad . ConfigurationError $ printf
             "Cannot add %s: UUID %s already in use"
             (show $ diskName disk) (UTF8.toString (diskUuid disk))
    else
      unless (checkUniqueUUID cs disk) . Bad . ConfigurationError $ printf
             "Cannot replace %s: UUID %s not present"
             (show $ diskName disk) (UTF8.toString (diskUuid disk))

attachInstanceDiskChecks :: InstanceUUID
                         -> DiskUUID
                         -> MaybeForJSON Int
                         -> ConfigState
                         -> GenericResult GanetiException ()
attachInstanceDiskChecks uuidInst uuidDisk idx' cs = do
  let diskPresent = elem uuidDisk . map (UTF8.toString . diskUuid) . M.elems
                  . fromContainer . configDisks . csConfigData $ cs
  unless diskPresent . Bad . ConfigurationError $ printf
    "Disk %s doesn't exist" uuidDisk

  inst <- getInstanceByUUID cs uuidInst
  let numDisks = length $ instDisks inst
      idx = fromMaybe numDisks (unMaybeForJSON idx')

  when (idx < 0) . Bad . GenericError $
    "Not accepting negative indices"
  when (idx > numDisks) . Bad . GenericError $ printf
    "Got disk index %d, but there are only %d" idx numDisks

  let insts = M.elems . fromContainer . configInstances . csConfigData $ cs
  forM_ insts (\inst' -> when (uuidDisk `elem` instDisks inst') . Bad
    . ReservationError $ printf "Disk %s already attached to instance %s"
        uuidDisk (show . fromMaybe "" $ instName inst'))

-- * Pure config modifications functions

attachInstanceDisk' :: InstanceUUID
                    -> DiskUUID
                    -> MaybeForJSON Int
                    -> ClockTime
                    -> ConfigState
                    -> ConfigState
attachInstanceDisk' iUuid dUuid idx' ct cs =
  let inst = genericResult (error "impossible") id (getInstanceByUUID cs iUuid)
      numDisks = length $ instDisks inst
      idx = fromMaybe numDisks (unMaybeForJSON idx')

      insert = instDisksL %~ (\ds -> take idx ds ++ [dUuid] ++ drop idx ds)
      incr = instSerialL %~ (+ 1)
      time = instMtimeL .~ ct

      inst' = time . incr . insert $ inst
      disks = updateIvNames idx inst' (configDisks . csConfigData $ cs)

      ri = csConfigDataL . configInstancesL
         . alterContainerL (UTF8.fromString iUuid) .~ Just inst'
      rds = csConfigDataL . configDisksL .~ disks
  in rds . ri $ cs
    where updateIvNames :: Int -> Instance -> Container Disk -> Container Disk
          updateIvNames idx inst (GenericContainer m) =
            let dUuids = drop idx (instDisks inst)
                upgradeIv m' (idx'', dUuid') =
                  M.adjust (diskIvNameL .~ "disk/" ++ show idx'') dUuid' m'
            in GenericContainer $ foldl upgradeIv m
                (zip [idx..] (fmap UTF8.fromString dUuids))

-- * Monadic config modification functions which can return errors

detachInstanceDisk' :: MonadError GanetiException m
                    => InstanceUUID
                    -> DiskUUID
                    -> ClockTime
                    -> ConfigState
                    -> m ConfigState
detachInstanceDisk' iUuid dUuid ct cs =
  let resetIv :: MonadError GanetiException m
              => Int
              -> [DiskUUID]
              -> ConfigState
              -> m ConfigState
      resetIv startIdx disks = mapMOf (csConfigDataL . configDisksL)
        (\cd -> foldM (\c (idx, dUuid') -> mapMOf (alterContainerL dUuid')
          (\md -> case md of
            Nothing -> throwError . ConfigurationError $
              printf "Could not find disk with UUID %s" (UTF8.toString dUuid')
            Just disk -> return
                       . Just
                       . (diskIvNameL .~ ("disk/" ++ show idx))
                       $ disk) c)
          cd (zip [startIdx..] (fmap UTF8.fromString disks)))
      iL = csConfigDataL . configInstancesL . alterContainerL
           (UTF8.fromString iUuid)
  in case cs ^. iL of
    Nothing -> throwError . ConfigurationError $
      printf "Could not find instance with UUID %s" iUuid
    Just ist -> case elemIndex dUuid (instDisks ist) of
      Nothing -> return cs
      Just idx ->
        let ist' = (instDisksL %~ filter (/= dUuid))
                 . (instSerialL %~ (+1))
                 . (instMtimeL .~ ct)
                 $ ist
            cs' = iL .~ Just ist' $ cs
            dks = drop (idx + 1) (instDisks ist)
        in resetIv idx dks cs'

removeInstanceDisk' :: MonadError GanetiException m
                    => InstanceUUID
                    -> DiskUUID
                    -> ClockTime
                    -> ConfigState
                    -> m ConfigState
removeInstanceDisk' iUuid dUuid ct =
  let f cs
        | elem dUuid
          . fold
          . fmap instDisks
          . configInstances
          . csConfigData
          $ cs
        = throwError . ProgrammerError $
        printf "Cannot remove disk %s. Disk is attached to an instance" dUuid
        | elem dUuid
          . foldMap (:[])
          . fmap (UTF8.toString . diskUuid)
          . configDisks
          . csConfigData
          $ cs
        = return
         . ((csConfigDataL . configDisksL . alterContainerL
            (UTF8.fromString dUuid)) .~ Nothing)
         . ((csConfigDataL . configClusterL . clusterSerialL) %~ (+1))
         . ((csConfigDataL . configClusterL . clusterMtimeL) .~ ct)
         $ cs
        | otherwise = return cs
  in (f =<<) . detachInstanceDisk' iUuid dUuid ct

-- * RPCs

-- | Add a new instance to the configuration, release DRBD minors,
-- and commit temporary IPs, all while temporarily holding the config
-- lock. Return True upon success and False if the config lock was not
-- available and the client should retry.
addInstance :: Instance -> ClientId -> Bool -> WConfdMonad Bool
addInstance inst cid replace = do
  ct <- liftIO getClockTime
  logDebug $ "AddInstance: client " ++ show (ciIdentifier cid)
             ++ " adding instance " ++ uuidOf inst
             ++ " with name " ++ show (instName inst)
  let setCtime = instCtimeL .~ ct
      setMtime = instMtimeL .~ ct
      addInst i = csConfigDataL . configInstancesL
                  . alterContainerL (UTF8.fromString $ uuidOf i)
                     .~ Just i
      commitRes tr = mapMOf csConfigDataL $ T.commitReservedIps cid tr
  r <- modifyConfigWithLock
         (\tr cs -> do
           toError $ addInstanceChecks inst replace cs
           commitRes tr $ addInst (setMtime . setCtime $ inst) cs)
         . T.releaseDRBDMinors . UTF8.fromString $ uuidOf inst
  logDebug $ "AddInstance: result of config modification is " ++ show r
  return $ isJust r

addInstanceDisk :: InstanceUUID
                -> Disk
                -> MaybeForJSON Int
                -> Bool
                -> WConfdMonad Bool
addInstanceDisk iUuid disk idx replace = do
  logInfo $ printf "Adding disk %s to configuration"
            (UTF8.toString (diskUuid disk))
  ct <- liftIO getClockTime
  let addD = csConfigDataL . configDisksL . alterContainerL
             (UTF8.fromString (uuidOf disk))
               .~ Just disk
      incrSerialNo = csConfigDataL . configSerialL %~ (+1)
  r <- modifyConfigWithLock (\_ cs -> do
           toError $ addDiskChecks disk replace cs
           let cs' = incrSerialNo . addD $ cs
           toError $ attachInstanceDiskChecks iUuid
               (UTF8.toString (diskUuid disk)) idx cs'
           return $ attachInstanceDisk' iUuid
               (UTF8.toString (diskUuid disk)) idx ct cs')
       . T.releaseDRBDMinors $ UTF8.fromString (uuidOf disk)
  return $ isJust r

attachInstanceDisk :: InstanceUUID
                   -> DiskUUID
                   -> MaybeForJSON Int
                   -> WConfdMonad Bool
attachInstanceDisk iUuid dUuid idx = do
  ct <- liftIO getClockTime
  r <- modifyConfigWithLock (\_ cs -> do
           toError $ attachInstanceDiskChecks iUuid dUuid idx cs
           return $ attachInstanceDisk' iUuid dUuid idx ct cs)
       (return ())
  return $ isJust r

-- | Detach a disk from an instance.
detachInstanceDisk :: InstanceUUID -> DiskUUID -> WConfdMonad Bool
detachInstanceDisk iUuid dUuid = do
  ct <- liftIO getClockTime
  isJust <$> modifyConfigWithLock
    (const $ detachInstanceDisk' iUuid dUuid ct) (return ())

-- | Detach a disk from an instance and
-- remove it from the config.
removeInstanceDisk :: InstanceUUID -> DiskUUID -> WConfdMonad Bool
removeInstanceDisk iUuid dUuid = do
  ct <- liftIO getClockTime
  isJust <$> modifyConfigWithLock
    (const $ removeInstanceDisk' iUuid dUuid ct) (return ())

-- | Remove the instance from the configuration.
removeInstance :: InstanceUUID -> WConfdMonad Bool
removeInstance iUuid = do
  ct <- liftIO getClockTime
  let iL = csConfigDataL . configInstancesL . alterContainerL
           (UTF8.fromString iUuid)
      pL = csConfigDataL . configClusterL . clusterTcpudpPortPoolL
      sL = csConfigDataL . configClusterL . clusterSerialL
      mL = csConfigDataL . configClusterL . clusterMtimeL

      -- Add the instances' network port to the cluster pool
      f :: Monad m => StateT ConfigState m ()
      f = get >>= (maybe
        (return ())
        (maybe
          (return ())
          (modify . (pL %~) . (:))
          . instNetworkPort)
        . (^. iL))

      -- Release all IP addresses to the pool
      g :: (MonadError GanetiException m, Functor m) => StateT ConfigState m ()
      g = get >>= (maybe
        (return ())
        (mapM_ (\nic ->
          when ((isJust . nicNetwork $ nic) && (isJust . nicIp $ nic)) $ do
            let network = fromJust . nicNetwork $ nic
            ip <- readIp4Address (fromJust . nicIp $ nic)
            get >>= mapMOf csConfigDataL (T.commitReleaseIp
                                          (UTF8.fromString network) ip) >>= put)
          . instNics)
        . (^. iL))

      -- Remove the instance and update cluster serial num, and mtime
      h :: Monad m => StateT ConfigState m ()
      h = modify $ (iL .~ Nothing) . (sL %~ (+1)) . (mL .~ ct)
  isJust <$> modifyConfigWithLock (const $ execStateT (f >> g >> h)) (return ())

-- | Allocate a port.
-- The port will be taken from the available port pool or from the
-- default port range (and in this case we increase
-- highest_used_port).
allocatePort :: WConfdMonad (MaybeForJSON Int)
allocatePort = do
  maybePort <- modifyConfigAndReturnWithLock (\_ cs ->
    let portPoolL = csConfigDataL . configClusterL . clusterTcpudpPortPoolL
        hupL = csConfigDataL . configClusterL . clusterHighestUsedPortL
    in case cs ^. portPoolL of
      [] -> if cs ^. hupL >= lastDrbdPort
        then throwError . ConfigurationError $ printf
          "The highest used port is greater than %s. Aborting." lastDrbdPort
        else return (cs ^. hupL + 1, hupL %~ (+1) $ cs)
      (p:ps) -> return (p, portPoolL .~ ps $ cs))
    (return ())
  return . MaybeForJSON $ maybePort

-- | Adds a new port to the available port pool.
addTcpUdpPort :: Int -> WConfdMonad Bool
addTcpUdpPort port =
  let pL = csConfigDataL . configClusterL . clusterTcpudpPortPoolL
      f :: Monad m => ConfigState -> m ConfigState
      f = mapMOf pL (return . (port:) . filter (/= port))
  in isJust <$> modifyConfigWithLock (const f) (return ())

-- | Set the instances' status to a given value.
setInstanceStatus :: InstanceUUID
                  -> MaybeForJSON AdminState
                  -> MaybeForJSON Bool
                  -> MaybeForJSON AdminStateSource
                  -> WConfdMonad (MaybeForJSON Instance)
setInstanceStatus iUuid m1 m2 m3 = do
  ct <- liftIO getClockTime
  let modifyInstance = maybe id (instAdminStateL .~) (unMaybeForJSON m1)
                     . maybe id (instDisksActiveL .~) (unMaybeForJSON m2)
                     . maybe id (instAdminStateSourceL .~) (unMaybeForJSON m3)
      reviseInstance = (instSerialL %~ (+1))
                     . (instMtimeL .~ ct)

      g :: Instance -> Instance
      g i = if modifyInstance i == i
              then i
              else reviseInstance . modifyInstance $ i

      iL = csConfigDataL . configInstancesL . alterContainerL
             (UTF8.fromString iUuid)

      f :: MonadError GanetiException m => StateT ConfigState m Instance
      f = get >>= (maybe
        (throwError . ConfigurationError $
          printf "Could not find instance with UUID %s" iUuid)
        (liftM2 (>>)
          (modify . (iL .~) . Just)
          return . g)
        . (^. iL))
  MaybeForJSON <$> modifyConfigAndReturnWithLock
    (const $ runStateT f) (return ())

-- | Sets the primary node of an existing instance
setInstancePrimaryNode :: InstanceUUID -> NodeUUID -> WConfdMonad Bool
setInstancePrimaryNode iUuid nUuid = isJust <$> modifyConfigWithLock
  (\_ -> mapMOf (csConfigDataL . configInstancesL . alterContainerL
      (UTF8.fromString iUuid))
    (\mi -> case mi of
      Nothing -> throwError . ConfigurationError $
        printf "Could not find instance with UUID %s" iUuid
      Just ist -> return . Just $ (instPrimaryNodeL .~ nUuid) ist))
  (return ())

-- | The configuration is updated by the provided cluster
updateCluster :: Cluster -> WConfdMonad (MaybeForJSON (Int, TimeAsDoubleJSON))
updateCluster cluster = do
  ct <- liftIO getClockTime
  r <- modifyConfigAndReturnWithLock (\_ cs -> do
    let currentCluster = configCluster . csConfigData $ cs
    if isIdentical ct cluster currentCluster
      then return ((serialOf currentCluster, mTimeOf currentCluster), cs)
      else do
        toError $ checkSerial cluster currentCluster
        let updateC = (clusterSerialL %~ (+1)) . (clusterMtimeL .~ ct)
        return ((serialOf cluster + 1, ct)
               , csConfigDataL . configClusterL .~ updateC cluster $ cs))
    (return ())
  return . MaybeForJSON $ fmap (_2 %~ TimeAsDoubleJSON) r

-- | The configuration is updated by the provided node
updateNode :: Node -> WConfdMonad (MaybeForJSON (Int, TimeAsDoubleJSON))
updateNode node = do
  ct <- liftIO getClockTime
  let nL = csConfigDataL . configNodesL
      updateC = (clusterSerialL %~ (+1)) . (clusterMtimeL .~ ct)
  r <- modifyConfigAndReturnWithLock (\_ -> updateConfigIfNecessary ct node
    (^. nL) (\cs -> do
      nC <- toError $ replaceIn ct node (cs ^. nL)
      return ((serialOf node + 1, ct), (nL .~ nC)
                . (csConfigDataL . configClusterL %~ updateC)
                $ cs)))
    (return ())
  return . MaybeForJSON $ fmap (_2 %~ TimeAsDoubleJSON) r

-- | The configuration is updated by the provided instance
updateInstance :: Instance -> WConfdMonad (MaybeForJSON (Int, TimeAsDoubleJSON))
updateInstance inst = do
  ct <- liftIO getClockTime
  let iL = csConfigDataL . configInstancesL
  r <- modifyConfigAndReturnWithLock (\_ -> updateConfigIfNecessary ct inst
    (^. iL) (\cs -> do
      iC <- toError $ replaceIn ct inst (cs ^. iL)
      return ((serialOf inst + 1, ct), (iL .~ iC) cs)))
    (return ())
  return . MaybeForJSON $ fmap (_2 %~ TimeAsDoubleJSON) r

-- | The configuration is updated by the provided nodegroup
updateNodeGroup :: NodeGroup
                -> WConfdMonad (MaybeForJSON (Int, TimeAsDoubleJSON))
updateNodeGroup ng = do
  ct <- liftIO getClockTime
  let ngL = csConfigDataL . configNodegroupsL
  r <- modifyConfigAndReturnWithLock (\_ -> updateConfigIfNecessary ct ng
    (^. ngL) (\cs -> do
      ngC <- toError $ replaceIn ct ng (cs ^. ngL)
      return ((serialOf ng + 1, ct), (ngL .~ ngC) cs)))
    (return ())
  return . MaybeForJSON $ fmap (_2 %~ TimeAsDoubleJSON) r

-- | The configuration is updated by the provided network
updateNetwork :: Network -> WConfdMonad (MaybeForJSON (Int, TimeAsDoubleJSON))
updateNetwork net = do
  ct <- liftIO getClockTime
  let nL = csConfigDataL . configNetworksL
  r <- modifyConfigAndReturnWithLock (\_ -> updateConfigIfNecessary ct net
    (^. nL) (\cs -> do
      nC <- toError $ replaceIn ct net (cs ^. nL)
      return ((serialOf net + 1, ct), (nL .~ nC) cs)))
    (return ())
  return . MaybeForJSON $ fmap (_2 %~ TimeAsDoubleJSON) r

-- | The configuration is updated by the provided disk
updateDisk :: Disk -> WConfdMonad (MaybeForJSON (Int, TimeAsDoubleJSON))
updateDisk disk = do
  ct <- liftIO getClockTime
  let dL = csConfigDataL . configDisksL
  r <- modifyConfigAndReturnWithLock (\_ -> updateConfigIfNecessary ct disk
    (^. dL) (\cs -> do
      dC <- toError $ replaceIn ct disk (cs ^. dL)
      return ((serialOf disk + 1, ct), (dL .~ dC) cs)))
    . T.releaseDRBDMinors . UTF8.fromString $ uuidOf disk
  return . MaybeForJSON $ fmap (_2 %~ TimeAsDoubleJSON) r

-- * The list of functions exported to RPC.

exportedFunctions :: [Name]
exportedFunctions = [ 'addInstance
                    , 'addInstanceDisk
                    , 'addTcpUdpPort
                    , 'allocatePort
                    , 'attachInstanceDisk
                    , 'detachInstanceDisk
                    , 'removeInstance
                    , 'removeInstanceDisk
                    , 'setInstancePrimaryNode
                    , 'setInstanceStatus
                    , 'updateCluster
                    , 'updateDisk
                    , 'updateInstance
                    , 'updateNetwork
                    , 'updateNode
                    , 'updateNodeGroup
                    ]

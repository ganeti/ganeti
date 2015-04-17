{-# LANGUAGE TemplateHaskell #-}

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

import Control.Lens.Setter ((.~))
import Control.Lens.Traversal (mapMOf)
import Control.Monad (unless)
import Control.Monad.IO.Class (liftIO)
import Data.Maybe (isJust, maybeToList)
import Language.Haskell.TH (Name)
import System.Time (getClockTime)
import Text.Printf (printf)
import qualified Data.Map as M
import qualified Data.Set as S

import Ganeti.BasicTypes (GenericResult(..), toError)
import Ganeti.Errors (GanetiException(..))
import Ganeti.JSON (GenericContainer(..), alterContainerL)
import Ganeti.Locking.Locks (ClientId, ciIdentifier)
import Ganeti.Logging.Lifted (logDebug)
import Ganeti.Objects
import Ganeti.Objects.Lens
import Ganeti.WConfd.ConfigState (ConfigState, csConfigData, csConfigDataL)
import Ganeti.WConfd.Monad (WConfdMonad, modifyConfigWithLock)
import qualified Ganeti.WConfd.TempRes as T

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
--   networks, disks, nics, and the custer itself.
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
  in S.union lvs . S.fromList $ instKeys ++ nodeKeys ++ instValues ++ nodeValues
         ++ nodeGroupValues ++ networkValues ++ disksValues ++ nics ++ [cluster]

getAllMACs :: ConfigState -> S.Set String
getAllMACs = S.fromList . map nicMac . concatMap instNics . M.elems
           . fromContainer . configInstances . csConfigData

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
             (show $ instName inst) (instUuid inst)
    else do
      let check = checkUniqueUUID cs inst
      unless check . Bad . ConfigurationError $ printf
             "Cannot replace %s: UUID %s not present"
             (show $ instName inst) (instUuid inst)

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
      addInst i = csConfigDataL . configInstancesL . alterContainerL (uuidOf i)
                  .~ Just i
      commitRes tr = mapMOf csConfigDataL $ T.commitReservedIps cid tr
  r <- modifyConfigWithLock
         (\tr cs -> do
           toError $ addInstanceChecks inst replace cs
           commitRes tr $ addInst (setMtime . setCtime $ inst) cs)
         . T.releaseDRBDMinors $ uuidOf inst
  logDebug $ "AddInstance: result of config modification is " ++ show r
  return $ isJust r

-- * The list of functions exported to RPC.

exportedFunctions :: [Name]
exportedFunctions = [ 'addInstance
                    ]

{-# LANGUAGE FlexibleContexts #-}

{-| Implementation of functions specific to configuration management.

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

module Ganeti.WConfd.ConfigVerify
  ( verifyConfig
  , verifyConfigErr
  ) where

import Control.Monad.Error
import qualified Data.Foldable as F
import qualified Data.Map as M
import qualified Data.Set as S

import Ganeti.Errors
import Ganeti.JSON (GenericContainer(..), Container)
import Ganeti.Objects
import Ganeti.Types
import Ganeti.Utils
import Ganeti.Utils.Validate

-- * Configuration checks

-- | A helper function that returns the key set of a container.
keysSet :: (Ord k) => GenericContainer k v -> S.Set k
keysSet = M.keysSet . fromContainer

-- | Checks that all objects are indexed by their proper UUID.
checkUUIDKeys :: (UuidObject a, Show a)
              => String -> Container a -> ValidationMonad ()
checkUUIDKeys what = mapM_ check . M.toList . fromContainer
  where
    check (uuid, x) = reportIf (uuid /= uuidOf x)
                      $ what ++ " '" ++ show x
                        ++ "' is indexed by wrong UUID '" ++ uuid ++ "'"

-- | Checks that all linked UUID of given objects exist.
checkUUIDRefs :: (UuidObject a, Show a, F.Foldable f)
              => String -> String
              -> (a -> [String]) -> f a -> Container b
              -> ValidationMonad ()
checkUUIDRefs whatObj whatTarget linkf xs targets = F.mapM_ check xs
  where
    uuids = keysSet targets
    check x = forM_ (linkf x) $ \uuid ->
                reportIf (not $ S.member uuid uuids)
                $ whatObj ++ " '" ++ show x ++ "' references a non-existing "
                  ++ whatTarget ++ " UUID '" ++ uuid ++ "'"

-- | Checks consistency of a given configuration.
--
-- TODO: Currently this implements only some very basic checks.
-- Evenually all checks from Python ConfigWriter need to be moved here
-- (see issue #759).
verifyConfig :: ConfigData -> ValidationMonad ()
verifyConfig cd = do
    let cluster = configCluster cd
        nodes = configNodes cd
        nodegroups = configNodegroups cd
        instances = configInstances cd
        networks = configNetworks cd
        disks = configDisks cd

    -- global cluster checks
    let enabledHvs = clusterEnabledHypervisors cluster
        hvParams = clusterHvparams cluster
    reportIf (null enabledHvs)
         "enabled hypervisors list doesn't have any entries"
    -- we don't need to check for invalid HVS as they would fail to parse
    let missingHvp = S.fromList (map hypervisorToRaw enabledHvs)
                      S.\\ keysSet hvParams
    reportIf (not $ S.null missingHvp)
           $ "hypervisor parameters missing for the enabled hypervisor(s) "
             ++ (commaJoin . S.toList $ missingHvp)

    let enabledDiskTemplates = clusterEnabledDiskTemplates cluster
    reportIf (null enabledDiskTemplates)
           "enabled disk templates list doesn't have any entries"
    -- we don't need to check for invalid templates as they wouldn't parse

    let masterNodeName = clusterMasterNode cluster
    reportIf (not $ masterNodeName `S.member` keysSet (configNodes cd))
           $ "cluster has invalid primary node " ++ masterNodeName

    -- UUIDs
    checkUUIDKeys "node" nodes
    checkUUIDKeys "nodegroup" nodegroups
    checkUUIDKeys "instances" instances
    checkUUIDKeys "network" networks
    checkUUIDKeys "disk" disks
    -- UUID references
    checkUUIDRefs "node" "nodegroup" (return . nodeGroup) nodes nodegroups
    checkUUIDRefs "instance" "primary node" (return . instPrimaryNode)
                                            instances nodes
    checkUUIDRefs "instance" "disks" instDisks instances disks

-- | Checks consistency of a given configuration.
-- If there is an error, throw 'ConfigVerifyError'.
verifyConfigErr :: (MonadError GanetiException m) => ConfigData -> m ()
verifyConfigErr cd =
  case runValidate $ verifyConfig cd of
    (_, []) -> return ()
    (_, es) -> throwError $ ConfigVerifyError "Validation failed" es

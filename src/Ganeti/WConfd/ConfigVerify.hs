{-# LANGUAGE FlexibleContexts #-}

{-| Implementation of functions specific to configuration management.

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

module Ganeti.WConfd.ConfigVerify
  ( verifyConfig
  , verifyConfigErr
  ) where

import Control.Monad.Error
import qualified Data.ByteString.UTF8 as UTF8
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
    check (uuid, x) = reportIf (uuid /= UTF8.fromString (uuidOf x))
                      $ what ++ " '" ++ show x
                        ++ "' is indexed by wrong UUID '"
                        ++ UTF8.toString uuid ++ "'"

-- | Checks that all linked UUID of given objects exist.
checkUUIDRefs :: (UuidObject a, Show a, F.Foldable f)
              => String -> String
              -> (a -> [String]) -> f a -> Container b
              -> ValidationMonad ()
checkUUIDRefs whatObj whatTarget linkf xs targets = F.mapM_ check xs
  where
    uuids = keysSet targets
    check x = forM_ (linkf x) $ \uuid ->
                reportIf (not $ S.member (UTF8.fromString uuid) uuids)
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
    let missingHvp = S.fromList enabledHvs S.\\ keysSet hvParams
    reportIf (not $ S.null missingHvp)
           $ "hypervisor parameters missing for the enabled hypervisor(s) "
             ++ (commaJoin . map hypervisorToRaw . S.toList $ missingHvp)

    let enabledDiskTemplates = clusterEnabledDiskTemplates cluster
    reportIf (null enabledDiskTemplates)
           "enabled disk templates list doesn't have any entries"
    -- we don't need to check for invalid templates as they wouldn't parse

    let masterNodeName = clusterMasterNode cluster
    reportIf (not $ UTF8.fromString masterNodeName
                       `S.member` keysSet (configNodes cd))
           $ "cluster has invalid primary node " ++ masterNodeName

    -- UUIDs
    checkUUIDKeys "node" nodes
    checkUUIDKeys "nodegroup" nodegroups
    checkUUIDKeys "instances" instances
    checkUUIDKeys "network" networks
    checkUUIDKeys "disk" disks
    -- UUID references
    checkUUIDRefs "node" "nodegroup" (return . nodeGroup) nodes nodegroups
    checkUUIDRefs "instance" "primary node" (maybe [] return . instPrimaryNode)
                                            instances nodes
    checkUUIDRefs "instance" "disks" instDisks instances disks

-- | Checks consistency of a given configuration.
-- If there is an error, throw 'ConfigVerifyError'.
verifyConfigErr :: (MonadError GanetiException m) => ConfigData -> m ()
verifyConfigErr cd =
  case runValidate $ verifyConfig cd of
    (_, []) -> return ()
    (_, es) -> throwError $ ConfigVerifyError "Validation failed" es

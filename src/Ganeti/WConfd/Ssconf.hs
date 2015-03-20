{-| Converts a configuration state into a Ssconf map.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

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

module Ganeti.WConfd.Ssconf
  ( SSConf(..)
  , emptySSConf
  , mkSSConf
  ) where

import Control.Arrow ((&&&))
import Data.Foldable (Foldable(..), toList)
import Data.List (partition)
import qualified Data.Map as M

import Ganeti.BasicTypes
import Ganeti.Config
import Ganeti.Constants
import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Ssconf
import Ganeti.Utils
import Ganeti.Types

mkSSConf :: ConfigData -> SSConf
mkSSConf cdata = SSConf $ M.fromList
    [ (SSClusterName, return $ clusterClusterName cluster)
    , (SSClusterTags, toList $ tagsOf cluster)
    , (SSFileStorageDir, return $ clusterFileStorageDir cluster)
    , (SSSharedFileStorageDir, return $ clusterSharedFileStorageDir cluster)
    , (SSGlusterStorageDir, return $ clusterGlusterStorageDir cluster)
    , (SSMasterCandidates, mapLines nodeName mcs)
    , (SSMasterCandidatesIps, mapLines nodePrimaryIp mcs)
    , (SSMasterCandidatesCerts, mapLines eqPair . toPairs
                                . clusterCandidateCerts $ cluster)
    , (SSMasterIp, return $ clusterMasterIp cluster)
    , (SSMasterNetdev, return $ clusterMasterNetdev cluster)
    , (SSMasterNetmask, return . show $ clusterMasterNetmask cluster)
    , (SSMasterNode, return
                     . genericResult (const "NO MASTER") nodeName
                     . getNode cdata $ clusterMasterNode cluster)
    , (SSNodeList, mapLines nodeName nodes)
    , (SSNodePrimaryIps, mapLines (spcPair . (nodeName &&& nodePrimaryIp))
                                  nodes )
    , (SSNodeSecondaryIps, mapLines (spcPair . (nodeName &&& nodeSecondaryIp))
                                    nodes )
    , (SSNodeVmCapable,  mapLines (eqPair . (nodeName &&& show . nodeVmCapable))
                                  nodes)
    , (SSOfflineNodes, mapLines nodeName offline )
    , (SSOnlineNodes, mapLines nodeName online )
    , (SSPrimaryIpFamily, return . show . ipFamilyToRaw
                          . clusterPrimaryIpFamily $ cluster)
    , (SSInstanceList, niceSort . map instName
                       . toList . configInstances $ cdata)
    , (SSReleaseVersion, return releaseVersion)
    , (SSHypervisorList, mapLines hypervisorToRaw
                         . clusterEnabledHypervisors $ cluster)
    , (SSMaintainNodeHealth, return . show . clusterMaintainNodeHealth
                             $ cluster)
    , (SSUidPool, mapLines formatUidRange . clusterUidPool $ cluster)
    , (SSNodegroups, mapLines (spcPair . (groupUuid &&& groupName))
                     nodeGroups)
    , (SSNetworks, mapLines (spcPair . (networkUuid
                                        &&& (fromNonEmpty . networkName)))
                   . configNetworks $ cdata)
    , (SSEnabledUserShutdown, return . show . clusterEnabledUserShutdown
                              $ cluster)
    ]
  where
    mapLines :: (Foldable f) => (a -> String) -> f a -> [String]
    mapLines f = map f . toList
    eqPair (x, y) = x ++ "=" ++ y
    spcPair (x, y) = x ++ " " ++ y
    toPairs = M.assocs . fromContainer

    cluster = configCluster cdata
    mcs = getMasterOrCandidates cdata
    nodes = niceSortKey nodeName . toList $ configNodes cdata
    (offline, online) = partition nodeOffline nodes
    nodeGroups = niceSortKey groupName . toList $ configNodegroups cdata

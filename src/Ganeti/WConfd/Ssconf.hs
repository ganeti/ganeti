{-| Converts a configuration state into a Ssconf map.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

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
                     . genericResult (error "Master node not found") nodeName
                     . getNode cdata $ clusterMasterNode cluster)
    , (SSNodeList, mapLines nodeName nodes)
    , (SSNodePrimaryIps, mapLines (spcPair . (nodeName &&& nodePrimaryIp))
                                  nodes )
    , (SSNodeSecondaryIps, mapLines (spcPair . (nodeName &&& nodeSecondaryIp))
                                    nodes )
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

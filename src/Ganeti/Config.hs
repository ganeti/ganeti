{-| Implementation of the Ganeti configuration database.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.Config
    ( LinkIpMap
    , NdParamObject(..)
    , loadConfig
    , getNodeInstances
    , getNodeRole
    , getNodeNdParams
    , getDefaultNicLink
    , getDefaultHypervisor
    , getInstancesIpByLink
    , getMasterCandidates
    , getNode
    , getInstance
    , getGroup
    , getGroupNdParams
    , getGroupIpolicy
    , getGroupDiskParams
    , getGroupNodes
    , getGroupInstances
    , getGroupOfNode
    , getInstPrimaryNode
    , getInstMinorsForNode
    , getInstAllNodes
    , getFilledInstHvParams
    , getFilledInstBeParams
    , getFilledInstOsParams
    , getNetwork
    , buildLinkIpInstnameMap
    , instNodes
    ) where

import Control.Monad (liftM)
import Control.Monad.IO.Class (liftIO)
import Data.List (foldl', nub)
import qualified Data.Map as M
import qualified Data.Set as S
import qualified Text.JSON as J

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Errors
import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Types

-- | Type alias for the link and ip map.
type LinkIpMap = M.Map String (M.Map String String)

-- | Type class denoting objects which have node parameters.
class NdParamObject a where
  getNdParamsOf :: ConfigData -> a -> Maybe FilledNDParams

-- | Reads the config file.
readConfig :: FilePath -> IO (Result String)
readConfig = runResultT . liftIO . readFile

-- | Parses the configuration file.
parseConfig :: String -> Result ConfigData
parseConfig = fromJResult "parsing configuration" . J.decodeStrict

-- | Wrapper over 'readConfig' and 'parseConfig'.
loadConfig :: FilePath -> IO (Result ConfigData)
loadConfig = fmap (>>= parseConfig) . readConfig

-- * Query functions

-- | Computes the nodes covered by a disk.
computeDiskNodes :: Disk -> S.Set String
computeDiskNodes dsk =
  case diskLogicalId dsk of
    LIDDrbd8 nodeA nodeB _ _ _ _ -> S.fromList [nodeA, nodeB]
    _ -> S.empty

-- | Computes all disk-related nodes of an instance. For non-DRBD,
-- this will be empty, for DRBD it will contain both the primary and
-- the secondaries.
instDiskNodes :: Instance -> S.Set String
instDiskNodes = S.unions . map computeDiskNodes . instDisks

-- | Computes all nodes of an instance.
instNodes :: Instance -> S.Set String
instNodes inst = instPrimaryNode inst `S.insert` instDiskNodes inst

-- | Computes the secondary nodes of an instance. Since this is valid
-- only for DRBD, we call directly 'instDiskNodes', skipping over the
-- extra primary insert.
instSecondaryNodes :: Instance -> S.Set String
instSecondaryNodes inst =
  instPrimaryNode inst `S.delete` instDiskNodes inst

-- | Get instances of a given node.
-- The node is specified through its UUID.
getNodeInstances :: ConfigData -> String -> ([Instance], [Instance])
getNodeInstances cfg nname =
    let all_inst = M.elems . fromContainer . configInstances $ cfg
        pri_inst = filter ((== nname) . instPrimaryNode) all_inst
        sec_inst = filter ((nname `S.member`) . instSecondaryNodes) all_inst
    in (pri_inst, sec_inst)

-- | Computes the role of a node.
getNodeRole :: ConfigData -> Node -> NodeRole
getNodeRole cfg node
  | nodeUuid node == clusterMasterNode (configCluster cfg) = NRMaster
  | nodeMasterCandidate node = NRCandidate
  | nodeDrained node = NRDrained
  | nodeOffline node = NROffline
  | otherwise = NRRegular

-- | Get the list of master candidates.
getMasterCandidates :: ConfigData -> [Node]
getMasterCandidates cfg = 
  filter ((==) NRCandidate . getNodeRole cfg)
    (map snd . M.toList . fromContainer . configNodes $ cfg)

-- | Returns the default cluster link.
getDefaultNicLink :: ConfigData -> String
getDefaultNicLink =
  nicpLink . (M.! C.ppDefault) . fromContainer .
  clusterNicparams . configCluster

-- | Returns the default cluster hypervisor.
getDefaultHypervisor :: ConfigData -> Hypervisor
getDefaultHypervisor cfg =
  case clusterEnabledHypervisors $ configCluster cfg of
    -- FIXME: this case shouldn't happen (configuration broken), but
    -- for now we handle it here because we're not authoritative for
    -- the config
    []  -> XenPvm
    x:_ -> x

-- | Returns instances of a given link.
getInstancesIpByLink :: LinkIpMap -> String -> [String]
getInstancesIpByLink linkipmap link =
  M.keys $ M.findWithDefault M.empty link linkipmap

-- | Generic lookup function that converts from a possible abbreviated
-- name to a full name.
getItem :: String -> String -> M.Map String a -> ErrorResult a
getItem kind name allitems = do
  let lresult = lookupName (M.keys allitems) name
      err msg = Bad $ OpPrereqError (kind ++ " name " ++ name ++ " " ++ msg)
                        ECodeNoEnt
  fullname <- case lrMatchPriority lresult of
                PartialMatch -> Ok $ lrContent lresult
                ExactMatch -> Ok $ lrContent lresult
                MultipleMatch -> err "has multiple matches"
                FailMatch -> err "not found"
  maybe (err "not found after successfull match?!") Ok $
        M.lookup fullname allitems

-- | Looks up a node by name or uuid.
getNode :: ConfigData -> String -> ErrorResult Node
getNode cfg name =
  let nodes = fromContainer (configNodes cfg)
  in case getItem "Node" name nodes of
       -- if not found by uuid, we need to look it up by name
       Ok node -> Ok node
       Bad _ -> let by_name = M.mapKeys
                              (nodeName . (M.!) nodes) nodes
                in getItem "Node" name by_name

-- | Looks up an instance by name or uuid.
getInstance :: ConfigData -> String -> ErrorResult Instance
getInstance cfg name =
  let instances = fromContainer (configInstances cfg)
  in case getItem "Instance" name instances of
       -- if not found by uuid, we need to look it up by name
       Ok inst -> Ok inst
       Bad _ -> let by_name = M.mapKeys
                              (instName . (M.!) instances) instances
                in getItem "Instance" name by_name

-- | Looks up a node group by name or uuid.
getGroup :: ConfigData -> String -> ErrorResult NodeGroup
getGroup cfg name =
  let groups = fromContainer (configNodegroups cfg)
  in case getItem "NodeGroup" name groups of
       -- if not found by uuid, we need to look it up by name, slow
       Ok grp -> Ok grp
       Bad _ -> let by_name = M.mapKeys
                              (groupName . (M.!) groups) groups
                in getItem "NodeGroup" name by_name

-- | Computes a node group's node params.
getGroupNdParams :: ConfigData -> NodeGroup -> FilledNDParams
getGroupNdParams cfg ng =
  fillNDParams (clusterNdparams $ configCluster cfg) (groupNdparams ng)

-- | Computes a node group's ipolicy.
getGroupIpolicy :: ConfigData -> NodeGroup -> FilledIPolicy
getGroupIpolicy cfg ng =
  fillIPolicy (clusterIpolicy $ configCluster cfg) (groupIpolicy ng)

-- | Computes a group\'s (merged) disk params.
getGroupDiskParams :: ConfigData -> NodeGroup -> DiskParams
getGroupDiskParams cfg ng =
  GenericContainer $
  fillDict (fromContainer . clusterDiskparams $ configCluster cfg)
           (fromContainer $ groupDiskparams ng) []

-- | Get nodes of a given node group.
getGroupNodes :: ConfigData -> String -> [Node]
getGroupNodes cfg gname =
  let all_nodes = M.elems . fromContainer . configNodes $ cfg in
  filter ((==gname) . nodeGroup) all_nodes

-- | Get (primary, secondary) instances of a given node group.
getGroupInstances :: ConfigData -> String -> ([Instance], [Instance])
getGroupInstances cfg gname =
  let gnodes = map nodeUuid (getGroupNodes cfg gname)
      ginsts = map (getNodeInstances cfg) gnodes in
  (concatMap fst ginsts, concatMap snd ginsts)

-- | Looks up a network. If looking up by uuid fails, we look up
-- by name.
getNetwork :: ConfigData -> String -> ErrorResult Network
getNetwork cfg name =
  let networks = fromContainer (configNetworks cfg)
  in case getItem "Network" name networks of
       Ok net -> Ok net
       Bad _ -> let by_name = M.mapKeys
                              (fromNonEmpty . networkName . (M.!) networks)
                              networks
                in getItem "Network" name by_name

-- | Retrieves the instance hypervisor params, missing values filled with
-- cluster defaults.
getFilledInstHvParams :: [String] -> ConfigData -> Instance -> HvParams
getFilledInstHvParams globals cfg inst =
  -- First get the defaults of the parent
  let hvName = hypervisorToRaw . instHypervisor $ inst
      hvParamMap = fromContainer . clusterHvparams $ configCluster cfg
      parentHvParams = maybe M.empty fromContainer $ M.lookup hvName hvParamMap
  -- Then the os defaults for the given hypervisor
      osName = instOs inst
      osParamMap = fromContainer . clusterOsHvp $ configCluster cfg
      osHvParamMap = maybe M.empty fromContainer $ M.lookup osName osParamMap
      osHvParams = maybe M.empty fromContainer $ M.lookup hvName osHvParamMap
  -- Then the child
      childHvParams = fromContainer . instHvparams $ inst
  -- Helper function
      fillFn con val = fillDict con val globals
  in GenericContainer $ fillFn (fillFn parentHvParams osHvParams) childHvParams

-- | Retrieves the instance backend params, missing values filled with cluster
-- defaults.
getFilledInstBeParams :: ConfigData -> Instance -> ErrorResult FilledBeParams
getFilledInstBeParams cfg inst = do
  let beParamMap = fromContainer . clusterBeparams . configCluster $ cfg
  parentParams <- getItem "FilledBeParams" C.ppDefault beParamMap
  return $ fillBeParams parentParams (instBeparams inst)

-- | Retrieves the instance os params, missing values filled with cluster
-- defaults. This does NOT include private and secret parameters.
getFilledInstOsParams :: ConfigData -> Instance -> OsParams
getFilledInstOsParams cfg inst =
  let osLookupName = takeWhile (/= '+') (instOs inst)
      osParamMap = fromContainer . clusterOsparams $ configCluster cfg
      childOsParams = instOsparams inst
  in case getItem "OsParams" osLookupName osParamMap of
       Ok parentOsParams -> GenericContainer $
                              fillDict (fromContainer parentOsParams)
                                       (fromContainer childOsParams) []
       Bad _             -> childOsParams

-- | Looks up an instance's primary node.
getInstPrimaryNode :: ConfigData -> String -> ErrorResult Node
getInstPrimaryNode cfg name =
  liftM instPrimaryNode (getInstance cfg name) >>= getNode cfg

-- | Retrieves all nodes hosting a DRBD disk
getDrbdDiskNodes :: ConfigData -> Disk -> [Node]
getDrbdDiskNodes cfg disk =
  let retrieved = case diskLogicalId disk of
                    LIDDrbd8 nodeA nodeB _ _ _ _ ->
                      justOk [getNode cfg nodeA, getNode cfg nodeB]
                    _                            -> []
  in retrieved ++ concatMap (getDrbdDiskNodes cfg) (diskChildren disk)

-- | Retrieves all the nodes of the instance.
--
-- As instances not using DRBD can be sent as a parameter as well,
-- the primary node has to be appended to the results.
getInstAllNodes :: ConfigData -> String -> ErrorResult [Node]
getInstAllNodes cfg name = do
  inst <- getInstance cfg name
  let diskNodes = concatMap (getDrbdDiskNodes cfg) $ instDisks inst
  pNode <- getInstPrimaryNode cfg name
  return . nub $ pNode:diskNodes

-- | Filters DRBD minors for a given node.
getDrbdMinorsForNode :: String -> Disk -> [(Int, String)]
getDrbdMinorsForNode node disk =
  let child_minors = concatMap (getDrbdMinorsForNode node) (diskChildren disk)
      this_minors =
        case diskLogicalId disk of
          LIDDrbd8 nodeA nodeB _ minorA minorB _
            | nodeA == node -> [(minorA, nodeB)]
            | nodeB == node -> [(minorB, nodeA)]
          _ -> []
  in this_minors ++ child_minors

-- | String for primary role.
rolePrimary :: String
rolePrimary = "primary"

-- | String for secondary role.
roleSecondary :: String
roleSecondary = "secondary"

-- | Gets the list of DRBD minors for an instance that are related to
-- a given node.
getInstMinorsForNode :: String -> Instance
                     -> [(String, Int, String, String, String, String)]
getInstMinorsForNode node inst =
  let role = if node == instPrimaryNode inst
               then rolePrimary
               else roleSecondary
      iname = instName inst
  -- FIXME: the disk/ build there is hack-ish; unify this in a
  -- separate place, or reuse the iv_name (but that is deprecated on
  -- the Python side)
  in concatMap (\(idx, dsk) ->
            [(node, minor, iname, "disk/" ++ show idx, role, peer)
               | (minor, peer) <- getDrbdMinorsForNode node dsk]) .
     zip [(0::Int)..] . instDisks $ inst

-- | Builds link -> ip -> instname map.
--
-- TODO: improve this by splitting it into multiple independent functions:
--
-- * abstract the \"fetch instance with filled params\" functionality
--
-- * abstsract the [instance] -> [(nic, instance_name)] part
--
-- * etc.
buildLinkIpInstnameMap :: ConfigData -> LinkIpMap
buildLinkIpInstnameMap cfg =
  let cluster = configCluster cfg
      instances = M.elems . fromContainer . configInstances $ cfg
      defparams = (M.!) (fromContainer $ clusterNicparams cluster) C.ppDefault
      nics = concatMap (\i -> [(instName i, nic) | nic <- instNics i])
             instances
  in foldl' (\accum (iname, nic) ->
               let pparams = nicNicparams nic
                   fparams = fillNicParams defparams pparams
                   link = nicpLink fparams
               in case nicIp nic of
                    Nothing -> accum
                    Just ip -> let oldipmap = M.findWithDefault M.empty
                                              link accum
                                   newipmap = M.insert ip iname oldipmap
                               in M.insert link newipmap accum
            ) M.empty nics


-- | Returns a node's group, with optional failure if we can't find it
-- (configuration corrupt).
getGroupOfNode :: ConfigData -> Node -> Maybe NodeGroup
getGroupOfNode cfg node =
  M.lookup (nodeGroup node) (fromContainer . configNodegroups $ cfg)

-- | Returns a node's ndparams, filled.
getNodeNdParams :: ConfigData -> Node -> Maybe FilledNDParams
getNodeNdParams cfg node = do
  group <- getGroupOfNode cfg node
  let gparams = getGroupNdParams cfg group
  return $ fillNDParams gparams (nodeNdparams node)

instance NdParamObject Node where
  getNdParamsOf = getNodeNdParams

instance NdParamObject NodeGroup where
  getNdParamsOf cfg = Just . getGroupNdParams cfg

instance NdParamObject Cluster where
  getNdParamsOf _ = Just . clusterNdparams

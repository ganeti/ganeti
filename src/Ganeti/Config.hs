{-# LANGUAGE ViewPatterns #-}

{-| Implementation of the Ganeti configuration database.

-}

{-

Copyright (C) 2011, 2012 Google Inc.
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

module Ganeti.Config
    ( LinkIpMap
    , NdParamObject(..)
    , loadConfig
    , saveConfig
    , getNodeInstances
    , getNodeRole
    , getNodeNdParams
    , getDefaultNicLink
    , getDefaultHypervisor
    , getInstancesIpByLink
    , getMasterNodes
    , getMasterCandidates
    , getMasterOrCandidates
    , getMasterNetworkParameters
    , getOnlineNodes
    , getNode
    , getInstance
    , getDisk
    , getFilterRule
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
    , getInstDisks
    , getInstDisksFromObj
    , getDrbdMinorsForDisk
    , getDrbdMinorsForInstance
    , getFilledInstHvParams
    , getFilledInstBeParams
    , getFilledInstOsParams
    , getNetwork
    , MAC
    , getAllMACs
    , getAllDrbdSecrets
    , NodeLVsMap
    , getInstanceLVsByNode
    , getAllLVs
    , buildLinkIpInstnameMap
    , instNodes
    ) where

import Control.Applicative
import Control.Arrow ((&&&))
import Control.Monad
import Control.Monad.State
import qualified Data.ByteString as BS
import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.Foldable as F
import Data.List (foldl', nub)
import Data.Maybe (fromMaybe, mapMaybe)
import Data.Monoid
import qualified Data.Map as M
import qualified Data.Set as S
import qualified Text.JSON as J
import System.IO

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Errors
import Ganeti.JSON (fromJResult, fromContainer, GenericContainer(..))
import Ganeti.Objects
import Ganeti.Types
import qualified Ganeti.Utils.MultiMap as MM

-- | Type alias for the link and ip map.
type LinkIpMap = M.Map String (M.Map String String)

-- * Operations on the whole configuration

-- | Reads the config file.
readConfig :: FilePath -> IO (Result String)
readConfig = runResultT . liftIO . readFile

-- | Parses the configuration file.
parseConfig :: String -> Result ConfigData
parseConfig = fromJResult "parsing configuration" . J.decodeStrict

-- | Encodes the configuration file.
encodeConfig :: ConfigData -> String
encodeConfig = J.encodeStrict

-- | Wrapper over 'readConfig' and 'parseConfig'.
loadConfig :: FilePath -> IO (Result ConfigData)
loadConfig = fmap (>>= parseConfig) . readConfig

-- | Wrapper over 'hPutStr' and 'encodeConfig'.
saveConfig :: Handle -> ConfigData -> IO ()
saveConfig fh = hPutStr fh . encodeConfig

-- * Query functions

-- | Annotate Nothing as missing parameter and apply the given
-- transformation otherwise
withMissingParam :: String -> (a -> ErrorResult b) -> Maybe a -> ErrorResult b
withMissingParam = maybe . Bad . ParameterError

-- | Computes the nodes covered by a disk.
computeDiskNodes :: Disk -> S.Set String
computeDiskNodes dsk =
  case diskLogicalId dsk of
    Just (LIDDrbd8 nodeA nodeB _ _ _ _) -> S.fromList [nodeA, nodeB]
    _ -> S.empty

-- | Computes all disk-related nodes of an instance. For non-DRBD,
-- this will be empty, for DRBD it will contain both the primary and
-- the secondaries.
instDiskNodes :: ConfigData -> Instance -> S.Set String
instDiskNodes cfg inst =
  case getInstDisksFromObj cfg inst of
    Ok disks -> S.unions $ map computeDiskNodes disks
    Bad _ -> S.empty

-- | Computes all nodes of an instance.
instNodes :: ConfigData -> Instance -> S.Set String
instNodes cfg inst = maybe id S.insert (instPrimaryNode inst)
                      $ instDiskNodes cfg inst

-- | Computes the secondary node UUID for a DRBD disk
computeDiskSecondaryNode :: Disk -> String -> Maybe String
computeDiskSecondaryNode dsk primary =
  case diskLogicalId dsk of
    Just (LIDDrbd8 a b _ _ _ _) -> Just $ if primary == a then b else a
    _ -> Nothing

-- | Get instances of a given node.
-- The node is specified through its UUID.
-- The secondary calculation is expensive and frequently called, so optimise
-- this to allocate fewer temporary values
getNodeInstances :: ConfigData -> String -> ([Instance], [Instance])
getNodeInstances cfg nname =
    let all_insts = M.elems . fromContainer . configInstances $ cfg
        all_disks = fromContainer . configDisks $ cfg

        pri_inst = filter ((== Just nname) . instPrimaryNode) all_insts

        find_disk :: String -> Maybe Disk
        find_disk d_uuid = M.lookup (UTF8.fromString d_uuid) all_disks

        inst_disks :: [(Instance, [Disk])]
        inst_disks = [(i, mapMaybe find_disk $ instDisks i) | i <- all_insts]

        sec_insts :: [Instance]
        sec_insts = [inst |
          (inst, disks) <- inst_disks,
          s_uuid <- mapMaybe (\d -> (instPrimaryNode inst) >>= (computeDiskSecondaryNode d)) disks,
          s_uuid == nname]
    in (pri_inst, sec_insts)

-- | Computes the role of a node.
getNodeRole :: ConfigData -> Node -> NodeRole
getNodeRole cfg node
  | uuidOf node == clusterMasterNode (configCluster cfg) = NRMaster
  | nodeMasterCandidate node = NRCandidate
  | nodeDrained node = NRDrained
  | nodeOffline node = NROffline
  | otherwise = NRRegular

-- | Get the list of the master nodes (usually one).
getMasterNodes :: ConfigData -> [Node]
getMasterNodes cfg =
  filter ((==) NRMaster . getNodeRole cfg) . F.toList . configNodes $ cfg

-- | Get the list of master candidates, /not including/ the master itself.
getMasterCandidates :: ConfigData -> [Node]
getMasterCandidates cfg =
  filter ((==) NRCandidate . getNodeRole cfg) . F.toList . configNodes $ cfg

-- | Get the list of master candidates, /including/ the master.
getMasterOrCandidates :: ConfigData -> [Node]
getMasterOrCandidates cfg =
  let isMC r = (r == NRCandidate) || (r == NRMaster)
  in filter (isMC . getNodeRole cfg) . F.toList . configNodes $ cfg

-- | Get the network parameters for the master IP address.
getMasterNetworkParameters :: ConfigData -> MasterNetworkParameters
getMasterNetworkParameters cfg =
  let cluster = configCluster cfg
  in MasterNetworkParameters
      { masterNetworkParametersUuid = clusterMasterNode cluster
      , masterNetworkParametersIp = clusterMasterIp cluster
      , masterNetworkParametersNetmask = clusterMasterNetmask cluster
      , masterNetworkParametersNetdev = clusterMasterNetdev cluster
      , masterNetworkParametersIpFamily = clusterPrimaryIpFamily cluster
      }

-- | Get the list of online nodes.
getOnlineNodes :: ConfigData -> [Node]
getOnlineNodes = filter (not . nodeOffline) . F.toList . configNodes

-- | Returns the default cluster link.
getDefaultNicLink :: ConfigData -> String
getDefaultNicLink =
  let ppDefault = UTF8.fromString C.ppDefault
  in nicpLink . (M.! ppDefault) . fromContainer
     . clusterNicparams . configCluster

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

-- | Simple lookup function, insisting on exact matches and using
-- byte strings.
getItem' :: String -> String -> M.Map BS.ByteString a -> ErrorResult a
getItem' kind name allitems =
  let name' = UTF8.fromString name
      err = Bad $ OpPrereqError (kind ++ " uuid " ++ name ++ " not found")
                    ECodeNoEnt
  in maybe err Ok $ M.lookup name' allitems

-- | Looks up a node by name or uuid.
getNode :: ConfigData -> String -> ErrorResult Node
getNode cfg name =
  let nodes = fromContainer (configNodes cfg)
  in case getItem' "Node" name nodes of
       -- if not found by uuid, we need to look it up by name
       Ok node -> Ok node
       Bad _ -> let by_name = M.mapKeys
                              (nodeName . (M.!) nodes) nodes
                in getItem "Node" name by_name

-- | Looks up an instance by name or uuid.
getInstance :: ConfigData -> String -> ErrorResult Instance
getInstance cfg name =
  let instances = fromContainer (configInstances cfg)
  in case getItem' "Instance" name instances of
       -- if not found by uuid, we need to look it up by name
       Ok inst -> Ok inst
       Bad _ -> let by_name =
                      M.delete ""
                      . M.mapKeys (fromMaybe "" . instName . (M.!) instances)
                      $ instances
                in getItem "Instance" name by_name

-- | Looks up an instance by exact name match
getInstanceByName :: ConfigData -> String -> ErrorResult Instance
getInstanceByName cfg name =
  let instances = M.elems . fromContainer . configInstances $ cfg
      matching = F.find (maybe False (== name) . instName) instances
  in case matching of
      Just inst -> Ok inst
      Nothing   -> Bad $ OpPrereqError
                   ("Instance name " ++ name ++ " not found")
                   ECodeNoEnt

-- | Looks up a disk by uuid.
getDisk :: ConfigData -> String -> ErrorResult Disk
getDisk cfg name =
  let disks = fromContainer (configDisks cfg)
  in getItem' "Disk" name disks

-- | Looks up a filter by uuid.
getFilterRule :: ConfigData -> String -> ErrorResult FilterRule
getFilterRule cfg name =
  let filters = fromContainer (configFilters cfg)
  in getItem' "Filter" name filters

-- | Looks up a node group by name or uuid.
getGroup :: ConfigData -> String -> ErrorResult NodeGroup
getGroup cfg name =
  let groups = fromContainer (configNodegroups cfg)
  in case getItem' "NodeGroup" name groups of
       -- if not found by uuid, we need to look it up by name, slow
       Ok grp -> Ok grp
       Bad _ -> let by_name = M.mapKeys
                              (groupName . (M.!) groups) groups
                in getItem "NodeGroup" name by_name

-- | Computes a node group's node params.
getGroupNdParams :: ConfigData -> NodeGroup -> FilledNDParams
getGroupNdParams cfg ng =
  fillParams (clusterNdparams $ configCluster cfg) (groupNdparams ng)

-- | Computes a node group's ipolicy.
getGroupIpolicy :: ConfigData -> NodeGroup -> FilledIPolicy
getGroupIpolicy cfg ng =
  fillParams (clusterIpolicy $ configCluster cfg) (groupIpolicy ng)

-- | Computes a group\'s (merged) disk params.
getGroupDiskParams :: ConfigData -> NodeGroup -> GroupDiskParams
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
  let gnodes = map uuidOf (getGroupNodes cfg gname)
      ginsts = map (getNodeInstances cfg) gnodes in
  (concatMap fst ginsts, concatMap snd ginsts)

-- | Retrieves the instance hypervisor params, missing values filled with
-- cluster defaults.
getFilledInstHvParams :: [String] -> ConfigData -> Instance -> HvParams
getFilledInstHvParams globals cfg inst =
  -- First get the defaults of the parent
  let maybeHvName = instHypervisor inst
      hvParamMap = fromContainer . clusterHvparams $ configCluster cfg
      parentHvParams =
        maybe M.empty fromContainer (maybeHvName >>= flip M.lookup hvParamMap)
  -- Then the os defaults for the given hypervisor
      maybeOsName = UTF8.fromString <$> instOs inst
      osParamMap = fromContainer . clusterOsHvp $ configCluster cfg
      osHvParamMap =
        maybe M.empty (maybe M.empty fromContainer . flip M.lookup osParamMap)
          maybeOsName
      osHvParams =
        maybe M.empty (maybe M.empty fromContainer . flip M.lookup osHvParamMap)
          maybeHvName
  -- Then the child
      childHvParams = fromContainer . instHvparams $ inst
  -- Helper function
      fillFn con val = fillDict con val $ fmap UTF8.fromString globals
  in GenericContainer $ fillFn (fillFn parentHvParams osHvParams) childHvParams

-- | Retrieves the instance backend params, missing values filled with cluster
-- defaults.
getFilledInstBeParams :: ConfigData -> Instance -> ErrorResult FilledBeParams
getFilledInstBeParams cfg inst = do
  let beParamMap = fromContainer . clusterBeparams . configCluster $ cfg
  parentParams <- getItem' "FilledBeParams" C.ppDefault beParamMap
  return $ fillParams parentParams (instBeparams inst)

-- | Retrieves the instance os params, missing values filled with cluster
-- defaults. This does NOT include private and secret parameters.
getFilledInstOsParams :: ConfigData -> Instance -> OsParams
getFilledInstOsParams cfg inst =
  let maybeOsLookupName = liftM (takeWhile (/= '+')) (instOs inst)
      osParamMap = fromContainer . clusterOsparams $ configCluster cfg
      childOsParams = instOsparams inst
  in case withMissingParam "Instance without OS"
            (flip (getItem' "OsParams") osParamMap)
            maybeOsLookupName of
       Ok parentOsParams -> GenericContainer $
                              fillDict (fromContainer parentOsParams)
                                       (fromContainer childOsParams) []
       Bad _             -> childOsParams

-- | Looks up an instance's primary node.
getInstPrimaryNode :: ConfigData -> String -> ErrorResult Node
getInstPrimaryNode cfg name =
  getInstanceByName cfg name
  >>= withMissingParam "Instance without primary node" return . instPrimaryNode
  >>= getNode cfg

-- | Retrieves all nodes hosting a DRBD disk
getDrbdDiskNodes :: ConfigData -> Disk -> [Node]
getDrbdDiskNodes cfg disk =
  let retrieved = case diskLogicalId disk of
                    Just (LIDDrbd8 nodeA nodeB _ _ _ _) ->
                      justOk [getNode cfg nodeA, getNode cfg nodeB]
                    _                            -> []
  in retrieved ++ concatMap (getDrbdDiskNodes cfg) (diskChildren disk)

-- | Retrieves all the nodes of the instance.
--
-- As instances not using DRBD can be sent as a parameter as well,
-- the primary node has to be appended to the results.
getInstAllNodes :: ConfigData -> String -> ErrorResult [Node]
getInstAllNodes cfg name = do
  inst <- getInstanceByName cfg name
  inst_disks <- getInstDisksFromObj cfg inst
  let disk_nodes = concatMap (getDrbdDiskNodes cfg) inst_disks
  pNode <- getInstPrimaryNode cfg name
  return . nub $ pNode:disk_nodes

-- | Get disks for a given instance.
-- The instance is specified by name or uuid.
getInstDisks :: ConfigData -> String -> ErrorResult [Disk]
getInstDisks cfg iname =
  getInstance cfg iname >>= mapM (getDisk cfg) . instDisks

-- | Get disks for a given instance object.
getInstDisksFromObj :: ConfigData -> Instance -> ErrorResult [Disk]
getInstDisksFromObj cfg =
  getInstDisks cfg . uuidOf

-- | Collects a value for all DRBD disks
collectFromDrbdDisks
  :: (Monoid a)
  => (String -> String -> Int -> Int -> Int -> Private DRBDSecret -> a)
  -- ^ NodeA, NodeB, Port, MinorA, MinorB, Secret
  -> Disk -> a
collectFromDrbdDisks f = col
  where
    col (diskLogicalId &&& diskChildren ->
           (Just (LIDDrbd8 nA nB port mA mB secret), ch)) =
             f nA nB port mA mB secret <> F.foldMap col ch
    col d = F.foldMap col (diskChildren d)

-- | Returns the DRBD secrets of a given 'Disk'
getDrbdSecretsForDisk :: Disk -> [DRBDSecret]
getDrbdSecretsForDisk = collectFromDrbdDisks
                          (\_ _ _ _ _ (Private secret) -> [secret])

-- | Returns the DRBD minors of a given 'Disk'
getDrbdMinorsForDisk :: Disk -> [(Int, String)]
getDrbdMinorsForDisk =
  collectFromDrbdDisks (\nA nB _ mnA mnB _ -> [(mnA, nA), (mnB, nB)])

-- | Filters DRBD minors for a given node.
getDrbdMinorsForNode :: String -> Disk -> [(Int, String)]
getDrbdMinorsForNode node disk =
  let child_minors = concatMap (getDrbdMinorsForNode node) (diskChildren disk)
      this_minors =
        case diskLogicalId disk of
          Just (LIDDrbd8 nodeA nodeB _ minorA minorB _)
            | nodeA == node -> [(minorA, nodeB)]
            | nodeB == node -> [(minorB, nodeA)]
          _ -> []
  in this_minors ++ child_minors

-- | Returns the DRBD minors of a given instance
getDrbdMinorsForInstance :: ConfigData -> Instance
                         -> ErrorResult [(Int, String)]
getDrbdMinorsForInstance cfg =
  liftM (concatMap getDrbdMinorsForDisk) . getInstDisksFromObj cfg

-- | String for primary role.
rolePrimary :: String
rolePrimary = "primary"

-- | String for secondary role.
roleSecondary :: String
roleSecondary = "secondary"

-- | Gets the list of DRBD minors for an instance that are related to
-- a given node.
getInstMinorsForNode :: ConfigData
                     -> String -- ^ The UUID of a node.
                     -> Instance
                     -> [(String, Int, String, String, String, String)]
getInstMinorsForNode cfg node inst =
  let nrole = if Just node == instPrimaryNode inst
                then rolePrimary
                else roleSecondary
      iname = fromMaybe "" $ instName inst
      inst_disks = case getInstDisksFromObj cfg inst of
                     Ok disks -> disks
                     Bad _ -> []
  -- FIXME: the disk/ build there is hack-ish; unify this in a
  -- separate place, or reuse the iv_name (but that is deprecated on
  -- the Python side)
  in concatMap (\(idx, dsk) ->
            [(node, minor, iname, "disk/" ++ show idx, nrole, peer)
               | (minor, peer) <- getDrbdMinorsForNode node dsk]) .
     zip [(0::Int)..] $ inst_disks

-- | Builds link -> ip -> instname map.
-- For instances without a name, we insert the uuid instead.
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
      defparams = (M.!) (fromContainer $ clusterNicparams cluster)
                    $ UTF8.fromString C.ppDefault
      nics = concatMap (\i -> [(fromMaybe (uuidOf i) $ instName i, nic)
                                | nic <- instNics i])
             instances
  in foldl' (\accum (iname, nic) ->
               let pparams = nicNicparams nic
                   fparams = fillParams defparams pparams
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
  M.lookup (UTF8.fromString $ nodeGroup node)
    (fromContainer . configNodegroups $ cfg)

-- | Returns a node's ndparams, filled.
getNodeNdParams :: ConfigData -> Node -> Maybe FilledNDParams
getNodeNdParams cfg node = do
  group <- getGroupOfNode cfg node
  let gparams = getGroupNdParams cfg group
  return $ fillParams gparams (nodeNdparams node)

-- * Network

-- | Looks up a network. If looking up by uuid fails, we look up
-- by name.
getNetwork :: ConfigData -> String -> ErrorResult Network
getNetwork cfg name =
  let networks = fromContainer (configNetworks cfg)
  in case getItem' "Network" name networks of
       Ok net -> Ok net
       Bad _ -> let by_name = M.mapKeys
                              (fromNonEmpty . networkName . (M.!) networks)
                              networks
                in getItem "Network" name by_name

-- ** MACs

type MAC = String

-- | Returns all MAC addresses used in the cluster.
getAllMACs :: ConfigData -> [MAC]
getAllMACs = F.foldMap (map nicMac . instNics) . configInstances

-- ** DRBD secrets

getAllDrbdSecrets :: ConfigData -> [DRBDSecret]
getAllDrbdSecrets = F.foldMap getDrbdSecretsForDisk . configDisks

-- ** LVs

-- | A map from node UUIDs to
--
-- FIXME: After adding designated types for UUIDs,
-- use them to replace 'String' here.
type NodeLVsMap = MM.MultiMap String LogicalVolume

getInstanceLVsByNode :: ConfigData -> Instance -> ErrorResult NodeLVsMap
getInstanceLVsByNode cd inst =
    withMissingParam "Instance without Primary Node"
      (\i -> return $ MM.fromList . lvsByNode i)
      (instPrimaryNode inst)
    <*> getInstDisksFromObj cd inst
  where
    lvsByNode :: String -> [Disk] -> [(String, LogicalVolume)]
    lvsByNode node = concatMap (lvsByNode1 node)
    lvsByNode1 :: String -> Disk -> [(String, LogicalVolume)]
    lvsByNode1 _ (diskLogicalId &&& diskChildren
                   -> (Just (LIDDrbd8 nA nB _ _ _ _), ch)) =
                         lvsByNode nA ch ++ lvsByNode nB ch
    lvsByNode1 node (diskLogicalId -> (Just (LIDPlain lv))) =
                         [(node, lv)]
    lvsByNode1 node (diskChildren -> ch) = lvsByNode node ch

getAllLVs :: ConfigData -> ErrorResult (S.Set LogicalVolume)
getAllLVs cd = mconcat <$> mapM (liftM MM.values . getInstanceLVsByNode cd)
                                (F.toList $ configInstances cd)

-- * ND params

-- | Type class denoting objects which have node parameters.
class NdParamObject a where
  getNdParamsOf :: ConfigData -> a -> Maybe FilledNDParams

instance NdParamObject Node where
  getNdParamsOf = getNodeNdParams

instance NdParamObject NodeGroup where
  getNdParamsOf cfg = Just . getGroupNdParams cfg

instance NdParamObject Cluster where
  getNdParamsOf _ = Just . clusterNdparams

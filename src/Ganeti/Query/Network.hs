{-| Implementation of the Ganeti Query2 node group queries.

 -}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.Query.Network
  ( NetworkRuntime(..)
  , networkFieldsMap
  ) where

import qualified Data.Map as Map
import Data.Maybe (fromMaybe, mapMaybe)

import Ganeti.JSON
import Ganeti.Network
import Ganeti.Objects
import Ganeti.Query.Language
import Ganeti.Query.Common
import Ganeti.Query.Types
import Ganeti.Types

data NetworkRuntime = NetworkRuntime

networkFields :: FieldList Network NetworkRuntime
networkFields =
  [ (FieldDefinition "name" "Name" QFTText "Network name",
     FieldSimple (rsNormal . networkName), QffNormal)
  , (FieldDefinition "network" "Subnet" QFTText "IPv4 subnet",
     FieldSimple (rsNormal . networkNetwork), QffNormal)
  , (FieldDefinition "gateway" "Gateway" QFTOther "IPv4 gateway",
     FieldSimple (rsMaybeUnavail . networkGateway), QffNormal)
  , (FieldDefinition "network6" "IPv6Subnet" QFTOther "IPv6 subnet",
     FieldSimple (rsMaybeUnavail . networkNetwork6), QffNormal)
  , (FieldDefinition "gateway6" "IPv6Gateway" QFTOther "IPv6 gateway",
     FieldSimple (rsMaybeUnavail . networkGateway6), QffNormal)
  , (FieldDefinition "mac_prefix" "MacPrefix" QFTOther "MAC address prefix",
     FieldSimple (rsMaybeUnavail . networkMacPrefix), QffNormal)
  , (FieldDefinition "network_type" "NetworkType" QFTOther "Network type",
     FieldSimple (rsMaybeUnavail . networkNetworkType), QffNormal)
  , (FieldDefinition "free_count" "FreeCount" QFTOther "Number of free IPs",
     FieldSimple (rsMaybeNoData . fmap getFreeCount . createAddressPool),
     QffNormal)
  , (FieldDefinition "map" "Map" QFTText "Map of the network's reserved IPs",
     FieldSimple (rsMaybeNoData . fmap getMap . createAddressPool),
     QffNormal)
  , (FieldDefinition "reserved_count" "ReservedCount" QFTOther
       "Number of reserved IPs",
     FieldSimple (rsMaybeNoData . fmap getReservedCount . createAddressPool),
     QffNormal)
  , (FieldDefinition "group_list" "GroupList" QFTOther "List of node groups",
     FieldConfig (\cfg -> rsNormal . getGroupConnections cfg . networkUuid),
     QffNormal)
  , (FieldDefinition "group_cnt" "GroupCount" QFTOther "Number of node groups",
     FieldConfig (\cfg -> rsNormal . length . getGroupConnections cfg
       . networkUuid), QffNormal)
  , (FieldDefinition "inst_list" "InstanceList" QFTOther "List of instances",
     FieldConfig (\cfg -> rsNormal . getInstances cfg . networkUuid),
     QffNormal)
  , (FieldDefinition "inst_cnt" "InstanceCount" QFTOther "Number of instances",
     FieldConfig (\cfg -> rsNormal . length . getInstances cfg
       . networkUuid), QffNormal)
  ] ++
  uuidFields "Network" ++
  serialFields "Network" ++
  tagsFields

-- | The group fields map.
networkFieldsMap :: FieldMap Network NetworkRuntime
networkFieldsMap =
  Map.fromList $ map (\v@(f, _, _) -> (fdefName f, v)) networkFields

-- TODO: the following fields are not implemented yet: external_reservations,
-- inst_cnt, inst_list

-- | Given a network's UUID, this function lists all connections from
-- the network to nodegroups including the respective mode and links.
getGroupConnections :: ConfigData -> String -> [(String, String, String)]
getGroupConnections cfg network_uuid =
  mapMaybe (getGroupConnection network_uuid)
  ((Map.elems . fromContainer . configNodegroups) cfg)

-- | Given a network's UUID and a node group, this function assembles
-- a tuple of the group's name, the mode and the link by which the
-- network is connected to the group. Returns 'Nothing' if the network
-- is not connected to the group.
getGroupConnection :: String -> NodeGroup -> Maybe (String, String, String)
getGroupConnection network_uuid group =
  let networks = fromContainer . groupNetworks $ group
  in case Map.lookup network_uuid networks of
    Nothing -> Nothing
    Just net ->
      Just (groupName group, getNicMode net, getNicLink net)

-- | Retrieves the network's mode and formats it human-readable,
-- also in case it is not available.
getNicMode :: PartialNicParams -> String
getNicMode nic_params =
  maybe "-" nICModeToRaw $ nicpModeP nic_params

-- | Retrieves the network's link and formats it human-readable, also in
-- case it it not available.
getNicLink :: PartialNicParams -> String
getNicLink nic_params = fromMaybe "-" (nicpLinkP nic_params)

-- | Retrieves the network's instances' names.
getInstances :: ConfigData -> String -> [String]
getInstances cfg network_uuid =
  map instName (filter (instIsConnected network_uuid)
    ((Map.elems . fromContainer . configInstances) cfg))

-- | Helper function that checks if an instance is linked to the given network.
instIsConnected :: String -> Instance -> Bool
instIsConnected network_uuid inst =
  network_uuid `elem` map networkUuid (mapMaybe nicNetwork (instNics inst))

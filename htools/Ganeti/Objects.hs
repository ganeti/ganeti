{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti config objects.

Some object fields are not implemented yet, and as such they are
commented out below.

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

module Ganeti.Objects
  ( NICMode(..)
  , PartialNICParams(..)
  , FilledNICParams(..)
  , fillNICParams
  , PartialNIC(..)
  , DiskMode(..)
  , DiskType(..)
  , Disk(..)
  , DiskTemplate(..)
  , PartialBEParams(..)
  , FilledBEParams(..)
  , fillBEParams
  , Instance(..)
  , toDictInstance
  , PartialNDParams(..)
  , FilledNDParams(..)
  , fillNDParams
  , Node(..)
  , AllocPolicy(..)
  , NodeGroup(..)
  , Cluster(..)
  , ConfigData(..)
  ) where

import Data.Maybe
import Text.JSON (makeObj, showJSON, readJSON)

import qualified Ganeti.Constants as C
import Ganeti.HTools.JSON

import Ganeti.THH

-- * NIC definitions

$(declareSADT "NICMode"
  [ ("NMBridged", 'C.nicModeBridged)
  , ("NMRouted",  'C.nicModeRouted)
  ])
$(makeJSONInstance ''NICMode)

$(buildParam "NIC" "nicp"
  [ simpleField "mode" [t| NICMode |]
  , simpleField "link" [t| String  |]
  ])

$(buildObject "PartialNIC" "nic"
  [ simpleField "mac" [t| String |]
  , optionalField $ simpleField "ip" [t| String |]
  , simpleField "nicparams" [t| PartialNICParams |]
  ])

-- * Disk definitions

$(declareSADT "DiskMode"
  [ ("DiskRdOnly", 'C.diskRdonly)
  , ("DiskRdWr",   'C.diskRdwr)
  ])
$(makeJSONInstance ''DiskMode)

$(declareSADT "DiskType"
  [ ("LD_LV",       'C.ldLv)
  , ("LD_DRBD8",    'C.ldDrbd8)
  , ("LD_FILE",     'C.ldFile)
  , ("LD_BLOCKDEV", 'C.ldBlockdev)
  ])
$(makeJSONInstance ''DiskType)

-- | Disk data structure.
--
-- This is declared manually as it's a recursive structure, and our TH
-- code currently can't build it.
data Disk = Disk
  { diskDevType    :: DiskType
--  , diskLogicalId  :: String
--  , diskPhysicalId :: String
  , diskChildren   :: [Disk]
  , diskIvName     :: String
  , diskSize       :: Int
  , diskMode       :: DiskMode
  } deriving (Read, Show, Eq)

$(buildObjectSerialisation "Disk"
  [ simpleField "dev_type"      [t| DiskMode |]
--  , simpleField "logical_id"  [t| String   |]
--  , simpleField "physical_id" [t| String   |]
  , defaultField  [| [] |] $ simpleField "children" [t| [Disk] |]
  , defaultField [| "" |] $ simpleField "iv_name" [t| String |]
  , simpleField "size" [t| Int |]
  , defaultField [| DiskRdWr |] $ simpleField "mode" [t| DiskMode |]
  ])

-- * Instance definitions

-- | Instance disk template type. **Copied from HTools/Types.hs**
$(declareSADT "DiskTemplate"
  [ ("DTDiskless",   'C.dtDiskless)
  , ("DTFile",       'C.dtFile)
  , ("DTSharedFile", 'C.dtSharedFile)
  , ("DTPlain",      'C.dtPlain)
  , ("DTBlock",      'C.dtBlock)
  , ("DTDrbd8",      'C.dtDrbd8)
  ])
$(makeJSONInstance ''DiskTemplate)

$(declareSADT "AdminState"
  [ ("AdminOffline", 'C.adminstOffline)
  , ("AdminDown",    'C.adminstDown)
  , ("AdminUp",      'C.adminstUp)
  ])
$(makeJSONInstance ''AdminState)

$(buildParam "BE" "bep" $
  [ simpleField "minmem"       [t| Int  |]
  , simpleField "maxmem"       [t| Int  |]
  , simpleField "vcpus"        [t| Int  |]
  , simpleField "auto_balance" [t| Bool |]
  ])

$(buildObject "Instance" "inst" $
  [ simpleField "name"           [t| String             |]
  , simpleField "primary_node"   [t| String             |]
  , simpleField "os"             [t| String             |]
  , simpleField "hypervisor"     [t| String             |]
--  , simpleField "hvparams"     [t| [(String, String)] |]
  , simpleField "beparams"       [t| PartialBEParams |]
--  , simpleField "osparams"     [t| [(String, String)] |]
  , simpleField "admin_state"    [t| AdminState         |]
  , simpleField "nics"           [t| [PartialNIC]              |]
  , simpleField "disks"          [t| [Disk]             |]
  , simpleField "disk_template"  [t| DiskTemplate       |]
  , optionalField $ simpleField "network_port" [t| Int |]
  ]
  ++ timeStampFields
  ++ uuidFields
  ++ serialFields)

-- * Node definitions

$(buildParam "ND" "ndp" $
  [ simpleField "oob_program" [t| String |]
  ])

$(buildObject "Node" "node" $
  [ simpleField "name"             [t| String |]
  , simpleField "primary_ip"       [t| String |]
  , simpleField "secondary_ip"     [t| String |]
  , simpleField "master_candidate" [t| Bool   |]
  , simpleField "offline"          [t| Bool   |]
  , simpleField "drained"          [t| Bool   |]
  , simpleField "group"            [t| String |]
  , simpleField "master_capable"   [t| Bool   |]
  , simpleField "vm_capable"       [t| Bool   |]
--  , simpleField "ndparams"       [t| PartialNDParams |]
  , simpleField "powered"          [t| Bool   |]
  ]
  ++ timeStampFields
  ++ uuidFields
  ++ serialFields)

-- * NodeGroup definitions

-- | The Group allocation policy type.
--
-- Note that the order of constructors is important as the automatic
-- Ord instance will order them in the order they are defined, so when
-- changing this data type be careful about the interaction with the
-- desired sorting order.
--
-- FIXME: COPIED from Types.hs; we need to eliminate this duplication later
$(declareSADT "AllocPolicy"
  [ ("AllocPreferred",   'C.allocPolicyPreferred)
  , ("AllocLastResort",  'C.allocPolicyLastResort)
  , ("AllocUnallocable", 'C.allocPolicyUnallocable)
  ])
$(makeJSONInstance ''AllocPolicy)

$(buildObject "NodeGroup" "group" $
  [ simpleField "name"         [t| String |]
  , defaultField  [| [] |] $ simpleField "members" [t| [String] |]
--  , simpleField "ndparams"   [t| PartialNDParams |]
  , simpleField "alloc_policy" [t| AllocPolicy |]
  ]
  ++ timeStampFields
  ++ uuidFields
  ++ serialFields)

-- * Cluster definitions
$(buildObject "Cluster" "cluster" $
  [ simpleField "rsahostkeypub"             [t| String   |]
  , simpleField "highest_used_port"         [t| Int      |]
  , simpleField "tcpudp_port_pool"          [t| [Int]    |]
  , simpleField "mac_prefix"                [t| String   |]
  , simpleField "volume_group_name"         [t| String   |]
  , simpleField "reserved_lvs"              [t| [String] |]
--  , simpleField "drbd_usermode_helper"      [t| String   |]
-- , simpleField "default_bridge"          [t| String   |]
-- , simpleField "default_hypervisor"      [t| String   |]
  , simpleField "master_node"               [t| String   |]
  , simpleField "master_ip"                 [t| String   |]
  , simpleField "master_netdev"             [t| String   |]
-- , simpleField "master_netmask"          [t| String   |]
  , simpleField "cluster_name"              [t| String   |]
  , simpleField "file_storage_dir"          [t| String   |]
-- , simpleField "shared_file_storage_dir" [t| String   |]
  , simpleField "enabled_hypervisors"       [t| [String] |]
-- , simpleField "hvparams"                [t| [(String, [(String, String)])] |]
-- , simpleField "os_hvp"                  [t| [(String, String)] |]
  , containerField $ simpleField "beparams" [t| FilledBEParams |]
-- , simpleField "osparams"                [t| [(String, String)] |]
  , containerField $ simpleField "nicparams" [t| FilledNICParams    |]
--  , simpleField "ndparams"                  [t| FilledNDParams |]
  , simpleField "candidate_pool_size"       [t| Int                |]
  , simpleField "modify_etc_hosts"          [t| Bool               |]
  , simpleField "modify_ssh_setup"          [t| Bool               |]
  , simpleField "maintain_node_health"      [t| Bool               |]
  , simpleField "uid_pool"                  [t| [Int]              |]
  , simpleField "default_iallocator"        [t| String             |]
  , simpleField "hidden_os"                 [t| [String]           |]
  , simpleField "blacklisted_os"            [t| [String]           |]
  , simpleField "primary_ip_family"         [t| Int                |]
  , simpleField "prealloc_wipe_disks"       [t| Bool               |]
 ]
 ++ serialFields)

-- * ConfigData definitions

$(buildObject "ConfigData" "config" $
--  timeStampFields ++
  [ simpleField "version"       [t| Int                |]
  , simpleField "cluster"       [t| Cluster            |]
  , containerField $ simpleField "nodes"      [t| Node     |]
  , containerField $ simpleField "nodegroups" [t| NodeGroup |]
  , containerField $ simpleField "instances"  [t| Instance |]
  ]
  ++ serialFields)

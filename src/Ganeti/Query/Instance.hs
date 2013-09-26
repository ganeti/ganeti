{-# LANGUAGE TupleSections #-}

{-| Implementation of the Ganeti Query2 instance queries.

-}

{-

Copyright (C) 2013 Google Inc.

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

module Ganeti.Query.Instance
  ( Runtime
  , fieldsMap
  , collectLiveData
  ) where

import qualified Data.Map as Map

import Ganeti.Objects
import Ganeti.Query.Common
import Ganeti.Query.Language
import Ganeti.Query.Types

-- | Dummy type for runtime to be implemented later, see the 'genericQuery'
-- function in 'Ganeti.Query.Query' for an explanation
data Runtime = Runtime

instanceFields :: FieldList Instance Runtime
instanceFields =
  [ (FieldDefinition "disk_template" "Disk_template" QFTText
     "Disk template",
     FieldSimple (rsNormal . instDiskTemplate), QffNormal)
  , (FieldDefinition "name" "Instance" QFTText
     "Instance name",
     FieldSimple (rsNormal . instName), QffHostname)
  , (FieldDefinition "hypervisor" "Hypervisor" QFTText
     "Hypervisor name",
     FieldSimple (rsNormal . instHypervisor), QffNormal)
  , (FieldDefinition "network_port" "Network_port" QFTOther
     "Instance network port if available (e.g. for VNC console)",
     FieldSimple (rsMaybeNoData . instNetworkPort), QffNormal)
  , (FieldDefinition "os" "OS" QFTText
     "Operating system",
     FieldSimple (rsNormal . instOs), QffNormal)
  ] ++
  serialFields "Instance" ++
  uuidFields "Instance"

fieldsMap :: FieldMap Instance Runtime
fieldsMap =
  Map.fromList [(fdefName f, v) | v@(f, _, _) <- instanceFields]

-- | Dummy function for collecting live data - just for interface testing
collectLiveData :: Bool -> ConfigData -> [Instance] -> IO [(Instance, Runtime)]
collectLiveData _ _ = return . map (, Runtime)

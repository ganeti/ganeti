{-| Implementation of Utility functions for storage

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

module Ganeti.Storage.Utils
  ( getClusterStorageUnits
  ) where

import Ganeti.Objects
import Ganeti.Types
import qualified Ganeti.Types as T

type StorageUnit = (StorageType, String)

-- | Get the cluster's default storage unit for a given disk template
getDefaultStorageKey :: ConfigData -> DiskTemplate -> Maybe String
getDefaultStorageKey cfg T.DTDrbd8 = clusterVolumeGroupName $ configCluster cfg
getDefaultStorageKey cfg T.DTPlain = clusterVolumeGroupName $ configCluster cfg
getDefaultStorageKey cfg T.DTFile =
    Just (clusterFileStorageDir $ configCluster cfg)
getDefaultStorageKey cfg T.DTSharedFile =
    Just (clusterSharedFileStorageDir $ configCluster cfg)
getDefaultStorageKey _ _ = Nothing

-- | Get the cluster's default spindle storage unit
getDefaultSpindleSU :: ConfigData -> (StorageType, Maybe String)
getDefaultSpindleSU cfg =
    (T.StorageLvmPv, clusterVolumeGroupName $ configCluster cfg)

-- | Get the cluster's storage units from the configuration
getClusterStorageUnits :: ConfigData -> [StorageUnit]
getClusterStorageUnits cfg = foldSUs (maybe_units ++ [spindle_unit])
  where disk_templates = clusterEnabledDiskTemplates $ configCluster cfg
        storage_types = map diskTemplateToStorageType disk_templates
        maybe_units = zip storage_types (map (getDefaultStorageKey cfg)
            disk_templates)
        spindle_unit = getDefaultSpindleSU cfg

-- | fold the storage unit list by sorting out the ones without keys
foldSUs :: [(StorageType, Maybe String)] -> [StorageUnit]
foldSUs = foldr ff []
  where ff (st, Just sk) acc = (st, sk) : acc
        ff (_, Nothing) acc = acc

-- | Mapping fo disk templates to storage type
-- FIXME: This is semantically the same as the constant
-- C.diskTemplatesStorageType
diskTemplateToStorageType :: DiskTemplate -> StorageType
diskTemplateToStorageType T.DTExt = T.StorageExt
diskTemplateToStorageType T.DTFile = T.StorageFile
diskTemplateToStorageType T.DTSharedFile = T.StorageFile
diskTemplateToStorageType T.DTDrbd8 = T.StorageLvmVg
diskTemplateToStorageType T.DTPlain = T.StorageLvmVg
diskTemplateToStorageType T.DTRbd = T.StorageRados
diskTemplateToStorageType T.DTDiskless = T.StorageDiskless
diskTemplateToStorageType T.DTBlock = T.StorageBlock

{-# LANGUAGE TemplateHaskell #-}

{-| Lenses for Ganeti config objects

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

module Ganeti.Objects.Lens where

import qualified Data.Set as Set
import System.Time (ClockTime(..))

import Ganeti.Lens (makeCustomLenses, Lens')
import Ganeti.Objects

-- | Class of objects that have timestamps.
class TimeStampObject a => TimeStampObjectL a where
  mTimeL :: Lens' a ClockTime

-- | Class of objects that have an UUID.
class UuidObject a => UuidObjectL a where
  uuidL :: Lens' a String

-- | Class of object that have a serial number.
class SerialNoObject a => SerialNoObjectL a where
  serialL :: Lens' a Int

-- | Class of objects that have tags.
class TagsObject a => TagsObjectL a where
  tagsL :: Lens' a (Set.Set String)

$(makeCustomLenses ''AddressPool)

$(makeCustomLenses ''Network)

instance SerialNoObjectL Network where
  serialL = networkSerialL

instance TagsObjectL Network where
  tagsL = networkTagsL

instance UuidObjectL Network where
  uuidL = networkUuidL

instance TimeStampObjectL Network where
  mTimeL = networkMtimeL

$(makeCustomLenses ''PartialNic)

$(makeCustomLenses ''Disk)

$(makeCustomLenses ''Instance)

instance TimeStampObjectL Instance where
  mTimeL = instMtimeL

instance UuidObjectL Instance where
  uuidL = instUuidL

instance SerialNoObjectL Instance where
  serialL = instSerialL

instance TagsObjectL Instance where
  tagsL = instTagsL

$(makeCustomLenses ''MinMaxISpecs)

$(makeCustomLenses ''PartialIPolicy)

$(makeCustomLenses ''FilledIPolicy)

$(makeCustomLenses ''Node)

instance TimeStampObjectL Node where
  mTimeL = nodeMtimeL

instance UuidObjectL Node where
  uuidL = nodeUuidL

instance SerialNoObjectL Node where
  serialL = nodeSerialL

instance TagsObjectL Node where
  tagsL = nodeTagsL

$(makeCustomLenses ''NodeGroup)

instance TimeStampObjectL NodeGroup where
  mTimeL = groupMtimeL

instance UuidObjectL NodeGroup where
  uuidL = groupUuidL

instance SerialNoObjectL NodeGroup where
  serialL = groupSerialL

instance TagsObjectL NodeGroup where
  tagsL = groupTagsL

$(makeCustomLenses ''Cluster)

instance TimeStampObjectL Cluster where
  mTimeL = clusterMtimeL

instance UuidObjectL Cluster where
  uuidL = clusterUuidL

instance SerialNoObjectL Cluster where
  serialL = clusterSerialL

instance TagsObjectL Cluster where
  tagsL = clusterTagsL

$(makeCustomLenses ''ConfigData)

instance SerialNoObjectL ConfigData where
  serialL = configSerialL

instance TimeStampObjectL ConfigData where
  mTimeL = configMtimeL

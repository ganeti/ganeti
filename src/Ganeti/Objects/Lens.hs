{-# LANGUAGE TemplateHaskell #-}

{-| Lenses for Ganeti config objects

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

module Ganeti.Objects.Lens where

import qualified Data.ByteString as BS
import qualified Data.ByteString.UTF8 as UTF8
import Control.Lens (Simple)
import Control.Lens.Iso (Iso, iso)
import qualified Data.Set as Set
import System.Time (ClockTime(..))

import Ganeti.Lens (makeCustomLenses, Lens')
import Ganeti.Objects

-- | Isomorphism between Strings and bytestrings
stringL :: Simple Iso BS.ByteString String
stringL = iso UTF8.toString UTF8.fromString

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
  uuidL = networkUuidL . stringL

instance TimeStampObjectL Network where
  mTimeL = networkMtimeL

$(makeCustomLenses ''PartialNic)

$(makeCustomLenses ''Disk)

instance TimeStampObjectL Disk where
  mTimeL = diskMtimeL

instance UuidObjectL Disk where
  uuidL = diskUuidL . stringL

instance SerialNoObjectL Disk where
  serialL = diskSerialL

$(makeCustomLenses ''Instance)

instance TimeStampObjectL Instance where
  mTimeL = instMtimeL

instance UuidObjectL Instance where
  uuidL = instUuidL . stringL

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
  uuidL = nodeUuidL . stringL

instance SerialNoObjectL Node where
  serialL = nodeSerialL

instance TagsObjectL Node where
  tagsL = nodeTagsL

$(makeCustomLenses ''NodeGroup)

instance TimeStampObjectL NodeGroup where
  mTimeL = groupMtimeL

instance UuidObjectL NodeGroup where
  uuidL = groupUuidL . stringL

instance SerialNoObjectL NodeGroup where
  serialL = groupSerialL

instance TagsObjectL NodeGroup where
  tagsL = groupTagsL

$(makeCustomLenses ''Cluster)

instance TimeStampObjectL Cluster where
  mTimeL = clusterMtimeL

instance UuidObjectL Cluster where
  uuidL = clusterUuidL . stringL

instance SerialNoObjectL Cluster where
  serialL = clusterSerialL

instance TagsObjectL Cluster where
  tagsL = clusterTagsL

$(makeCustomLenses ''ConfigData)

instance SerialNoObjectL ConfigData where
  serialL = configSerialL

instance TimeStampObjectL ConfigData where
  mTimeL = configMtimeL

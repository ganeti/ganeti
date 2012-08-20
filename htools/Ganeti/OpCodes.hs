{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the opcodes.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Ganeti.OpCodes
  ( OpCode(..)
  , ReplaceDisksMode(..)
  , DiskIndex
  , mkDiskIndex
  , unDiskIndex
  , opID
  , allOpIDs
  ) where

import Text.JSON (readJSON, showJSON, makeObj, JSON)

import qualified Ganeti.Constants as C
import Ganeti.THH

import Ganeti.HTools.JSON

-- | Replace disks type.
$(declareSADT "ReplaceDisksMode"
  [ ("ReplaceOnPrimary",    'C.replaceDiskPri)
  , ("ReplaceOnSecondary",  'C.replaceDiskSec)
  , ("ReplaceNewSecondary", 'C.replaceDiskChg)
  , ("ReplaceAuto",         'C.replaceDiskAuto)
  ])
$(makeJSONInstance ''ReplaceDisksMode)

-- | Disk index type (embedding constraints on the index value via a
-- smart constructor).
newtype DiskIndex = DiskIndex { unDiskIndex :: Int }
  deriving (Show, Read, Eq, Ord)

-- | Smart constructor for 'DiskIndex'.
mkDiskIndex :: (Monad m) => Int -> m DiskIndex
mkDiskIndex i | i >= 0 && i < C.maxDisks = return (DiskIndex i)
              | otherwise = fail $ "Invalid value for disk index '" ++
                            show i ++ "', required between 0 and " ++
                            show C.maxDisks

instance JSON DiskIndex where
  readJSON v = readJSON v >>= mkDiskIndex
  showJSON = showJSON . unDiskIndex

-- | OpCode representation.
--
-- We only implement a subset of Ganeti opcodes, but only what we
-- actually use in the htools codebase.
$(genOpCode "OpCode"
  [ ("OpTestDelay",
     [ simpleField "duration"  [t| Double   |]
     , simpleField "on_master" [t| Bool     |]
     , simpleField "on_nodes"  [t| [String] |]
     ])
  , ("OpInstanceReplaceDisks",
     [ simpleField "instance_name" [t| String |]
     , optionalField $ simpleField "remote_node" [t| String |]
     , simpleField "mode"  [t| ReplaceDisksMode |]
     , simpleField "disks" [t| [DiskIndex] |]
     , optionalField $ simpleField "iallocator" [t| String |]
     ])
  , ("OpInstanceFailover",
     [ simpleField "instance_name"      [t| String |]
     , simpleField "ignore_consistency" [t| Bool   |]
     , optionalField $ simpleField "target_node" [t| String |]
     ])
  , ("OpInstanceMigrate",
     [ simpleField "instance_name"  [t| String |]
     , simpleField "live"           [t| Bool   |]
     , simpleField "cleanup"        [t| Bool   |]
     , defaultField [| False |] $ simpleField "allow_failover" [t| Bool |]
     , optionalField $ simpleField "target_node" [t| String |]
     ])
  ])

-- | Returns the OP_ID for a given opcode value.
$(genOpID ''OpCode "opID")

-- | A list of all defined/supported opcode IDs.
$(genAllOpIDs ''OpCode "allOpIDs")

instance JSON OpCode where
  readJSON = loadOpCode
  showJSON = saveOpCode

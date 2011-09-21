{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the opcodes.

-}

{-

Copyright (C) 2009, 2010, 2011 Google Inc.

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
    , opID
    ) where

import Text.JSON (readJSON, showJSON, makeObj, JSON)
import qualified Text.JSON as J

import qualified Ganeti.Constants as C
import Ganeti.THH

import Ganeti.HTools.Utils

-- | Replace disks type.
$(declareSADT "ReplaceDisksMode"
     [ ("ReplaceOnPrimary",    'C.replaceDiskPri)
     , ("ReplaceOnSecondary",  'C.replaceDiskSec)
     , ("ReplaceNewSecondary", 'C.replaceDiskChg)
     , ("ReplaceAuto",         'C.replaceDiskAuto)
     ])
$(makeJSONInstance ''ReplaceDisksMode)

-- | OpCode representation.
--
-- We only implement a subset of Ganeti opcodes, but only what we
-- actually use in the htools codebase.
$(genOpCode "OpCode"
         [ ("OpTestDelay",
            [ ("duration",  [t| Double   |], noDefault)
            , ("on_master", [t| Bool     |], noDefault)
            , ("on_nodes",  [t| [String] |], noDefault)
            ])
         , ("OpInstanceReplaceDisks",
            [ ("instance_name", [t| String           |], noDefault)
            , ("remote_node",   [t| Maybe String     |], noDefault)
            , ("mode",          [t| ReplaceDisksMode |], noDefault)
            , ("disks",         [t| [Int]            |], noDefault)
            , ("iallocator",    [t| Maybe String     |], noDefault)
            ])
         , ("OpInstanceFailover",
            [ ("instance_name",      [t| String       |], noDefault)
            , ("ignore_consistency", [t| Bool         |], noDefault)
            , ("target_node",        [t| Maybe String |], noDefault)
            ])
         , ("OpInstanceMigrate",
            [ ("instance_name",  [t| String       |], noDefault)
            , ("live",           [t| Bool         |], noDefault)
            , ("cleanup",        [t| Bool         |], noDefault)
            , ("allow_failover", [t| Bool         |], [| Just False |])
            , ("target_node",    [t| Maybe String |], noDefault)
            ])
         ])

$(genOpID ''OpCode "opID")

instance JSON OpCode where
    readJSON = loadOpCode
    showJSON = saveOpCode

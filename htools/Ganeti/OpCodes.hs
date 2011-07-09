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

import Control.Monad
import Text.JSON (readJSON, showJSON, makeObj, JSON)
import qualified Text.JSON as J
import Text.JSON.Types

import Ganeti.HTools.Utils

-- | Replace disks type.
data ReplaceDisksMode = ReplaceOnPrimary
                  | ReplaceOnSecondary
                  | ReplaceNewSecondary
                  | ReplaceAuto
                  deriving (Show, Read, Eq)

instance JSON ReplaceDisksMode where
    showJSON m = case m of
                 ReplaceOnPrimary -> showJSON "replace_on_primary"
                 ReplaceOnSecondary -> showJSON "replace_on_secondary"
                 ReplaceNewSecondary -> showJSON "replace_new_secondary"
                 ReplaceAuto -> showJSON "replace_auto"
    readJSON s = case readJSON s of
                   J.Ok "replace_on_primary" -> J.Ok ReplaceOnPrimary
                   J.Ok "replace_on_secondary" -> J.Ok ReplaceOnSecondary
                   J.Ok "replace_new_secondary" -> J.Ok ReplaceNewSecondary
                   J.Ok "replace_auto" -> J.Ok ReplaceAuto
                   _ -> J.Error "Can't parse a valid ReplaceDisksMode"

-- | OpCode representation.
--
-- We only implement a subset of Ganeti opcodes, but only what we
-- actually use in the htools codebase.
data OpCode = OpTestDelay Double Bool [String]
            | OpInstanceReplaceDisks String (Maybe String) ReplaceDisksMode
              [Int] (Maybe String)
            | OpInstanceFailover String Bool (Maybe String)
            | OpInstanceMigrate String Bool Bool Bool (Maybe String)
            deriving (Show, Read, Eq)


-- | Computes the OP_ID for an OpCode.
opID :: OpCode -> String
opID (OpTestDelay _ _ _) = "OP_TEST_DELAY"
opID (OpInstanceReplaceDisks _ _ _ _ _) = "OP_INSTANCE_REPLACE_DISKS"
opID (OpInstanceFailover {}) = "OP_INSTANCE_FAILOVER"
opID (OpInstanceMigrate  {}) = "OP_INSTANCE_MIGRATE"

-- | Loads an OpCode from the JSON serialised form.
loadOpCode :: JSValue -> J.Result OpCode
loadOpCode v = do
  o <- liftM J.fromJSObject (readJSON v)
  let extract x = fromObj o x
  op_id <- extract "OP_ID"
  case op_id of
    "OP_TEST_DELAY" -> do
                 on_nodes  <- extract "on_nodes"
                 on_master <- extract "on_master"
                 duration  <- extract "duration"
                 return $ OpTestDelay duration on_master on_nodes
    "OP_INSTANCE_REPLACE_DISKS" -> do
                 inst   <- extract "instance_name"
                 node   <- maybeFromObj o "remote_node"
                 mode   <- extract "mode"
                 disks  <- extract "disks"
                 ialloc <- maybeFromObj o "iallocator"
                 return $ OpInstanceReplaceDisks inst node mode disks ialloc
    "OP_INSTANCE_FAILOVER" -> do
                 inst    <- extract "instance_name"
                 consist <- extract "ignore_consistency"
                 tnode   <- maybeFromObj o "target_node"
                 return $ OpInstanceFailover inst consist tnode
    "OP_INSTANCE_MIGRATE" -> do
                 inst    <- extract "instance_name"
                 live    <- extract "live"
                 cleanup <- extract "cleanup"
                 allow_failover <- fromObjWithDefault o "allow_failover" False
                 tnode   <- maybeFromObj o "target_node"
                 return $ OpInstanceMigrate inst live cleanup
                        allow_failover tnode
    _ -> J.Error $ "Unknown opcode " ++ op_id

-- | Serialises an opcode to JSON.
saveOpCode :: OpCode -> JSValue
saveOpCode op@(OpTestDelay duration on_master on_nodes) =
    let ol = [ ("OP_ID", showJSON $ opID op)
             , ("duration", showJSON duration)
             , ("on_master", showJSON on_master)
             , ("on_nodes", showJSON on_nodes) ]
    in makeObj ol

saveOpCode op@(OpInstanceReplaceDisks inst node mode disks iallocator) =
    let ol = [ ("OP_ID", showJSON $ opID op)
             , ("instance_name", showJSON inst)
             , ("mode", showJSON mode)
             , ("disks", showJSON disks)]
        ol2 = case node of
                Just n -> ("remote_node", showJSON n):ol
                Nothing -> ol
        ol3 = case iallocator of
                Just i -> ("iallocator", showJSON i):ol2
                Nothing -> ol2
    in makeObj ol3

saveOpCode op@(OpInstanceFailover inst consist tnode) =
    let ol = [ ("OP_ID", showJSON $ opID op)
             , ("instance_name", showJSON inst)
             , ("ignore_consistency", showJSON consist) ]
        ol' = case tnode of
                Nothing -> ol
                Just node -> ("target_node", showJSON node):ol
    in makeObj ol'

saveOpCode op@(OpInstanceMigrate inst live cleanup allow_failover tnode) =
    let ol = [ ("OP_ID", showJSON $ opID op)
             , ("instance_name", showJSON inst)
             , ("live", showJSON live)
             , ("cleanup", showJSON cleanup)
             , ("allow_failover", showJSON allow_failover) ]
        ol' = case tnode of
                Nothing -> ol
                Just node -> ("target_node", showJSON node):ol
    in makeObj ol'

instance JSON OpCode where
    readJSON = loadOpCode
    showJSON = saveOpCode

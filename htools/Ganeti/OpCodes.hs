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

data OpCode = OpTestDelay Double Bool [String]
            | OpReplaceDisks String (Maybe String) ReplaceDisksMode
              [Int] (Maybe String)
            | OpFailoverInstance String Bool
            | OpMigrateInstance String Bool Bool
            deriving (Show, Read, Eq)


opID :: OpCode -> String
opID (OpTestDelay _ _ _) = "OP_TEST_DELAY"
opID (OpReplaceDisks _ _ _ _ _) = "OP_INSTANCE_REPLACE_DISKS"
opID (OpFailoverInstance _ _) = "OP_INSTANCE_FAILOVER"
opID (OpMigrateInstance _ _ _) = "OP_INSTANCE_MIGRATE"

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
                 return $ OpReplaceDisks inst node mode disks ialloc
    "OP_INSTANCE_FAILOVER" -> do
                 inst    <- extract "instance_name"
                 consist <- extract "ignore_consistency"
                 return $ OpFailoverInstance inst consist
    "OP_INSTANCE_MIGRATE" -> do
                 inst    <- extract "instance_name"
                 live    <- extract "live"
                 cleanup <- extract "cleanup"
                 return $ OpMigrateInstance inst live cleanup
    _ -> J.Error $ "Unknown opcode " ++ op_id

saveOpCode :: OpCode -> JSValue
saveOpCode op@(OpTestDelay duration on_master on_nodes) =
    let ol = [ ("OP_ID", showJSON $ opID op)
             , ("duration", showJSON duration)
             , ("on_master", showJSON on_master)
             , ("on_nodes", showJSON on_nodes) ]
    in makeObj ol

saveOpCode op@(OpReplaceDisks inst node mode disks iallocator) =
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

saveOpCode op@(OpFailoverInstance inst consist) =
    let ol = [ ("OP_ID", showJSON $ opID op)
             , ("instance_name", showJSON inst)
             , ("ignore_consistency", showJSON consist) ]
    in makeObj ol

saveOpCode op@(OpMigrateInstance inst live cleanup) =
    let ol = [ ("OP_ID", showJSON $ opID op)
             , ("instance_name", showJSON inst)
             , ("live", showJSON live)
             , ("cleanup", showJSON cleanup) ]
    in makeObj ol

instance JSON OpCode where
    readJSON = loadOpCode
    showJSON = saveOpCode

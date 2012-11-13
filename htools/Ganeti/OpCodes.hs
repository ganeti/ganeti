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
  , TagObject(..)
  , tagObjectFrom
  , encodeTagObject
  , decodeTagObject
  , ReplaceDisksMode(..)
  , DiskIndex
  , mkDiskIndex
  , unDiskIndex
  , opID
  , allOpIDs
  ) where

import Text.JSON (readJSON, showJSON, JSON, JSValue(..), fromJSString)
import Text.JSON.Pretty (pp_value)

import qualified Ganeti.Constants as C
import Ganeti.THH

import Ganeti.JSON

-- | Data type representing what items do the tag operations apply to.
$(declareSADT "TagType"
  [ ("TagTypeInstance", 'C.tagInstance)
  , ("TagTypeNode",     'C.tagNode)
  , ("TagTypeGroup",    'C.tagNodegroup)
  , ("TagTypeCluster",  'C.tagCluster)
  ])
$(makeJSONInstance ''TagType)

-- | Data type holding a tag object (type and object name).
data TagObject = TagInstance String
               | TagNode     String
               | TagGroup    String
               | TagCluster
               deriving (Show, Read, Eq)

-- | Tag type for a given tag object.
tagTypeOf :: TagObject -> TagType
tagTypeOf (TagInstance {}) = TagTypeInstance
tagTypeOf (TagNode     {}) = TagTypeNode
tagTypeOf (TagGroup    {}) = TagTypeGroup
tagTypeOf (TagCluster  {}) = TagTypeCluster

-- | Gets the potential tag object name.
tagNameOf :: TagObject -> Maybe String
tagNameOf (TagInstance s) = Just s
tagNameOf (TagNode     s) = Just s
tagNameOf (TagGroup    s) = Just s
tagNameOf  TagCluster     = Nothing

-- | Builds a 'TagObject' from a tag type and name.
tagObjectFrom :: (Monad m) => TagType -> JSValue -> m TagObject
tagObjectFrom TagTypeInstance (JSString s) =
  return . TagInstance $ fromJSString s
tagObjectFrom TagTypeNode     (JSString s) = return . TagNode $ fromJSString s
tagObjectFrom TagTypeGroup    (JSString s) = return . TagGroup $ fromJSString s
tagObjectFrom TagTypeCluster   JSNull      = return TagCluster
tagObjectFrom t v =
  fail $ "Invalid tag type/name combination: " ++ show t ++ "/" ++
         show (pp_value v)

-- | Name of the tag \"name\" field.
tagNameField :: String
tagNameField = "name"

-- | Custom encoder for 'TagObject' as represented in an opcode.
encodeTagObject :: TagObject -> (JSValue, [(String, JSValue)])
encodeTagObject t = ( showJSON (tagTypeOf t)
                    , [(tagNameField, maybe JSNull showJSON (tagNameOf t))] )

-- | Custom decoder for 'TagObject' as represented in an opcode.
decodeTagObject :: (Monad m) => [(String, JSValue)] -> JSValue -> m TagObject
decodeTagObject obj kind = do
  ttype <- fromJVal kind
  tname <- fromObj obj tagNameField
  tagObjectFrom ttype tname

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
-- We only implement a subset of Ganeti opcodes: those which are actually used
-- in the htools codebase.
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
  , ("OpTagsSet",
     [ customField 'decodeTagObject 'encodeTagObject $
       simpleField "kind" [t| TagObject |]
     , simpleField "tags" [t| [String]  |]
     ])
  , ("OpTagsDel",
     [ customField 'decodeTagObject 'encodeTagObject $
       simpleField "kind" [t| TagObject |]
     , simpleField "tags" [t| [String]  |]
     ])
  ])

-- | Returns the OP_ID for a given opcode value.
$(genOpID ''OpCode "opID")

-- | A list of all defined/supported opcode IDs.
$(genAllOpIDs ''OpCode "allOpIDs")

instance JSON OpCode where
  readJSON = loadOpCode
  showJSON = saveOpCode

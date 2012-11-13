{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of opcodes parameters.

These are defined in a separate module only due to TemplateHaskell
stage restrictions - expressions defined in the current module can't
be passed to splices. So we have to either parameters/repeat each
parameter definition multiple times, or separate them into this
module.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.OpParams
  ( TagType(..)
  , TagObject(..)
  , tagObjectFrom
  , decodeTagObject
  , encodeTagObject
  , ReplaceDisksMode(..)
  , DiskIndex
  , mkDiskIndex
  , unDiskIndex
  , pInstanceName
  , pTagsList
  , pTagsObject
  ) where

import Text.JSON (readJSON, showJSON, JSON, JSValue(..), fromJSString)
import Text.JSON.Pretty (pp_value)

import qualified Ganeti.Constants as C
import Ganeti.THH
import Ganeti.JSON

-- * Helper functions and types

-- ** Tags

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

-- ** Disks

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

-- * Parameters

-- | Instance name.
pInstanceName :: Field
pInstanceName = simpleField "instance_name" [t| String |]

-- | Tags list.
pTagsList :: Field
pTagsList = simpleField "tags" [t| [String] |]

-- | Tags object.
pTagsObject :: Field
pTagsObject = customField 'decodeTagObject 'encodeTagObject $
              simpleField "kind" [t| TagObject |]

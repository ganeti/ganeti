{-# LANGUAGE TemplateHaskell, FunctionalDependencies #-}

{-| Implementation of the Ganeti Disk config object.

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

module Ganeti.Objects.Disk where

import Control.Applicative ((<*>), (<$>))
import qualified Data.ByteString.UTF8 as UTF8
import Data.Char (isAsciiLower, isAsciiUpper, isDigit)
import Data.List (isPrefixOf, isInfixOf)
import Language.Haskell.TH.Syntax
import Text.JSON (showJSON, readJSON, JSValue(..))
import qualified Text.JSON as J

import Ganeti.JSON (Container, fromObj)
import Ganeti.THH
import Ganeti.THH.Field
import Ganeti.Types
import Ganeti.Utils.Validate

-- | Constant for the dev_type key entry in the disk config.
devType :: String
devType = "dev_type"

-- | The disk parameters type.
type DiskParams = Container JSValue

-- | An alias for DRBD secrets
type DRBDSecret = String

-- Represents a group name and a volume name.
--
-- From @man lvm@:
--
-- The following characters are valid for VG and LV names: a-z A-Z 0-9 + _ . -
--
-- VG  and LV names cannot begin with a hyphen.  There are also various reserved
-- names that are used internally by lvm that can not be used as LV or VG names.
-- A VG cannot be  called  anything  that exists in /dev/ at the time of
-- creation, nor can it be called '.' or '..'.  A LV cannot be called '.' '..'
-- 'snapshot' or 'pvmove'. The LV name may also not contain the strings '_mlog'
-- or '_mimage'
data LogicalVolume = LogicalVolume { lvGroup :: String
                                   , lvVolume :: String
                                   }
  deriving (Eq, Ord)

instance Show LogicalVolume where
  showsPrec _ (LogicalVolume g v) =
    showString g . showString "/" . showString v

-- | Check the constraints for VG\/LV names (except the @\/dev\/@ check).
instance Validatable LogicalVolume where
  validate (LogicalVolume g v) = do
      let vgn = "Volume group name"
      -- Group name checks
      nonEmpty vgn g
      validChars vgn g
      notStartsDash vgn g
      notIn vgn g [".", ".."]
      -- Volume name checks
      let lvn = "Volume name"
      nonEmpty lvn v
      validChars lvn v
      notStartsDash lvn v
      notIn lvn v [".", "..", "snapshot", "pvmove"]
      reportIf ("_mlog" `isInfixOf` v) $ lvn ++ " must not contain '_mlog'."
      reportIf ("_mimage" `isInfixOf` v) $ lvn ++ "must not contain '_mimage'."
    where
      nonEmpty prefix x = reportIf (null x) $ prefix ++ " must be non-empty"
      notIn prefix x =
        mapM_ (\y -> reportIf (x == y)
                              $ prefix ++ " must not be '" ++ y ++ "'")
      notStartsDash prefix x = reportIf ("-" `isPrefixOf` x)
                                 $ prefix ++ " must not start with '-'"
      validChars prefix x =
        reportIf (not . all validChar $ x)
                 $ prefix ++ " must consist only of [a-z][A-Z][0-9][+_.-]"
      validChar c = isAsciiLower c || isAsciiUpper c || isDigit c
                    || (c `elem` "+_.-")

instance J.JSON LogicalVolume where
  showJSON = J.showJSON . show
  readJSON (J.JSString s) | (g, _ : l) <- break (== '/') (J.fromJSString s) =
    either fail return . evalValidate . validate' $ LogicalVolume g l
  readJSON v = fail $ "Invalid JSON value " ++ show v
                      ++ " for a logical volume"

-- | The disk configuration type. This includes the disk type itself,
-- for a more complete consistency. Note that since in the Python
-- code-base there's no authoritative place where we document the
-- logical id, this is probably a good reference point. There is a bijective
-- correspondence between the 'DiskLogicalId' constructors and 'DiskTemplate'.
data DiskLogicalId
  = LIDPlain LogicalVolume  -- ^ Volume group, logical volume
  | LIDDrbd8 String String Int Int Int (Private DRBDSecret)
  -- ^ NodeA, NodeB, Port, MinorA, MinorB, Secret
  | LIDFile FileDriver String -- ^ Driver, path
  | LIDSharedFile FileDriver String -- ^ Driver, path
  | LIDGluster FileDriver String -- ^ Driver, path
  | LIDBlockDev BlockDriver String -- ^ Driver, path (must be under /dev)
  | LIDRados String String -- ^ Unused, path
  | LIDExt String String -- ^ ExtProvider, unique name
    deriving (Show, Eq)

-- | Mapping from a logical id to a disk type.
lidDiskType :: DiskLogicalId -> DiskTemplate
lidDiskType (LIDPlain {}) = DTPlain
lidDiskType (LIDDrbd8 {}) = DTDrbd8
lidDiskType (LIDFile  {}) = DTFile
lidDiskType (LIDSharedFile  {}) = DTSharedFile
lidDiskType (LIDGluster  {}) = DTGluster
lidDiskType (LIDBlockDev {}) = DTBlock
lidDiskType (LIDRados {}) = DTRbd
lidDiskType (LIDExt {}) = DTExt

-- | Builds the extra disk_type field for a given logical id.
lidEncodeType :: DiskLogicalId -> [(String, JSValue)]
lidEncodeType v = [(devType, showJSON . lidDiskType $ v)]

-- | Custom encoder for DiskLogicalId (logical id only).
encodeDLId :: DiskLogicalId -> JSValue
encodeDLId (LIDPlain (LogicalVolume vg lv)) =
  JSArray [showJSON vg, showJSON lv]
encodeDLId (LIDDrbd8 nodeA nodeB port minorA minorB key) =
  JSArray [ showJSON nodeA, showJSON nodeB, showJSON port
          , showJSON minorA, showJSON minorB, showJSON key ]
encodeDLId (LIDRados pool name) = JSArray [showJSON pool, showJSON name]
encodeDLId (LIDFile driver name) = JSArray [showJSON driver, showJSON name]
encodeDLId (LIDSharedFile driver name) =
  JSArray [showJSON driver, showJSON name]
encodeDLId (LIDGluster driver name) = JSArray [showJSON driver, showJSON name]
encodeDLId (LIDBlockDev driver name) = JSArray [showJSON driver, showJSON name]
encodeDLId (LIDExt extprovider name) =
  JSArray [showJSON extprovider, showJSON name]

-- | Custom encoder for DiskLogicalId, composing both the logical id
-- and the extra disk_type field.
encodeFullDLId :: DiskLogicalId -> (JSValue, [(String, JSValue)])
encodeFullDLId v = (encodeDLId v, lidEncodeType v)

-- | Custom decoder for DiskLogicalId. This is manual for now, since
-- we don't have yet automation for separate-key style fields.
decodeDLId :: [(String, JSValue)] -> JSValue -> J.Result DiskLogicalId
decodeDLId obj lid = do
  dtype <- fromObj obj devType
  case dtype of
    DTDrbd8 ->
      case lid of
        JSArray [nA, nB, p, mA, mB, k] ->
          LIDDrbd8
            <$> readJSON nA
            <*> readJSON nB
            <*> readJSON p
            <*> readJSON mA
            <*> readJSON mB
            <*> readJSON k
        _ -> fail "Can't read logical_id for DRBD8 type"
    DTPlain ->
      case lid of
        JSArray [vg, lv] -> LIDPlain <$>
          (LogicalVolume <$> readJSON vg <*> readJSON lv)
        _ -> fail "Can't read logical_id for plain type"
    DTFile ->
      case lid of
        JSArray [driver, path] ->
          LIDFile
            <$> readJSON driver
            <*> readJSON path
        _ -> fail "Can't read logical_id for file type"
    DTSharedFile ->
      case lid of
        JSArray [driver, path] ->
          LIDSharedFile
            <$> readJSON driver
            <*> readJSON path
        _ -> fail "Can't read logical_id for shared file type"
    DTGluster ->
      case lid of
        JSArray [driver, path] ->
          LIDGluster
            <$> readJSON driver
            <*> readJSON path
        _ -> fail "Can't read logical_id for shared file type"
    DTBlock ->
      case lid of
        JSArray [driver, path] ->
          LIDBlockDev
            <$> readJSON driver
            <*> readJSON path
        _ -> fail "Can't read logical_id for blockdev type"
    DTRbd ->
      case lid of
        JSArray [driver, path] ->
          LIDRados
            <$> readJSON driver
            <*> readJSON path
        _ -> fail "Can't read logical_id for rdb type"
    DTExt ->
      case lid of
        JSArray [extprovider, name] ->
          LIDExt
            <$> readJSON extprovider
            <*> readJSON name
        _ -> fail "Can't read logical_id for extstorage type"
    DTDiskless ->
      fail "Retrieved 'diskless' disk."

-- | Disk data structure.

$(buildObjectWithForthcoming "Disk" "disk" $
  [ customField 'decodeDLId 'encodeFullDLId ["dev_type"] $
      simpleField "logical_id"    [t| DiskLogicalId   |]
  , defaultField  [| [] |]
      $ simpleField "children" (return . AppT ListT . ConT $ mkName "Disk")
  , defaultField  [| [] |] $ simpleField "nodes" [t| [String] |]
  , defaultField [| "" |] $ simpleField "iv_name" [t| String |]
  , simpleField "size" [t| Int |]
  , defaultField [| DiskRdWr |] $ simpleField "mode" [t| DiskMode |]
  , optionalField $ simpleField "name" [t| String |]
  , optionalField $ simpleField "spindles" [t| Int |]
  , optionalField $ simpleField "params" [t| DiskParams |]
  ]
  ++ uuidFields
  ++ serialFields
  ++ timeStampFields)

instance TimeStampObject Disk where
  cTimeOf = diskCtime
  mTimeOf = diskMtime

instance UuidObject Disk where
  uuidOf = UTF8.toString . diskUuid

instance SerialNoObject Disk where
  serialOf = diskSerial

instance ForthcomingObject Disk where
  isForthcoming = diskForthcoming

-- | Determines whether a disk or one of his children has the given logical id
-- (determined by the volume group name and by the logical volume name).
-- This can be true only for DRBD or LVM disks.
includesLogicalId :: LogicalVolume -> Disk -> Bool
includesLogicalId lv disk =
  case diskLogicalId disk of
    Just (LIDPlain lv') -> lv' == lv
    Just (LIDDrbd8 {}) ->
      any (includesLogicalId lv) $ diskChildren disk
    _ -> False

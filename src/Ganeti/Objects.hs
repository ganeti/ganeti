{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti config objects.

Some object fields are not implemented yet, and as such they are
commented out below.

-}

{-

Copyright (C) 2011, 2012, 2013, 2014 Google Inc.
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

module Ganeti.Objects
  ( HvParams
  , OsParams
  , OsParamsPrivate
  , PartialNicParams(..)
  , FilledNicParams(..)
  , fillNicParams
  , allNicParamFields
  , PartialNic(..)
  , FileDriver(..)
  , DRBDSecret
  , LogicalVolume(..)
  , DiskLogicalId(..)
  , Disk(..)
  , includesLogicalId
  , DiskTemplate(..)
  , PartialBeParams(..)
  , FilledBeParams(..)
  , fillBeParams
  , allBeParamFields
  , Instance(..)
  , PartialNDParams(..)
  , FilledNDParams(..)
  , fillNDParams
  , allNDParamFields
  , Node(..)
  , AllocPolicy(..)
  , FilledISpecParams(..)
  , PartialISpecParams(..)
  , fillISpecParams
  , allISpecParamFields
  , MinMaxISpecs(..)
  , FilledIPolicy(..)
  , PartialIPolicy(..)
  , fillIPolicy
  , GroupDiskParams
  , NodeGroup(..)
  , IpFamily(..)
  , ipFamilyToRaw
  , ipFamilyToVersion
  , fillDict
  , ClusterHvParams
  , OsHvParams
  , ClusterBeParams
  , ClusterOsParams
  , ClusterOsParamsPrivate
  , ClusterNicParams
  , UidPool
  , formatUidRange
  , UidRange
  , Cluster(..)
  , ConfigData(..)
  , TimeStampObject(..)
  , UuidObject(..)
  , SerialNoObject(..)
  , TagsObject(..)
  , DictObject(..) -- re-exported from THH
  , TagSet -- re-exported from THH
  , Network(..)
  , AddressPool(..)
  , Ip4Address()
  , mkIp4Address
  , Ip4Network()
  , mkIp4Network
  , ip4netAddr
  , ip4netMask
  , readIp4Address
  , ip4AddressToList
  , ip4AddressToNumber
  , ip4AddressFromNumber
  , nextIp4Address
  , IAllocatorParams
  , MasterNetworkParameters(..)
  ) where

import Control.Applicative
import Control.Arrow (first)
import Control.Monad.State
import Data.Char
import Data.List (foldl', isPrefixOf, isInfixOf, intercalate)
import Data.Maybe
import qualified Data.Map as Map
import qualified Data.Set as Set
import Data.Tuple (swap)
import Data.Word
import System.Time (ClockTime(..))
import Text.JSON (showJSON, readJSON, JSON, JSValue(..), fromJSString)
import qualified Text.JSON as J

import qualified AutoConf
import qualified Ganeti.Constants as C
import qualified Ganeti.ConstantUtils as ConstantUtils
import Ganeti.JSON
import Ganeti.Objects.BitArray (BitArray)
import Ganeti.Types
import Ganeti.THH
import Ganeti.THH.Field
import Ganeti.Utils (sepSplit, tryRead, parseUnitAssumeBinary)
import Ganeti.Utils.Validate

-- * Generic definitions

-- | Fills one map with keys from the other map, if not already
-- existing. Mirrors objects.py:FillDict.
fillDict :: (Ord k) => Map.Map k v -> Map.Map k v -> [k] -> Map.Map k v
fillDict defaults custom skip_keys =
  let updated = Map.union custom defaults
  in foldl' (flip Map.delete) updated skip_keys

-- | The hypervisor parameter type. This is currently a simple map,
-- without type checking on key/value pairs.
type HvParams = Container JSValue

-- | The OS parameters type. This is, and will remain, a string
-- container, since the keys are dynamically declared by the OSes, and
-- the values are always strings.
type OsParams = Container String
type OsParamsPrivate = Container (Private String)

-- | Class of objects that have timestamps.
class TimeStampObject a where
  cTimeOf :: a -> ClockTime
  mTimeOf :: a -> ClockTime

-- | Class of objects that have an UUID.
class UuidObject a where
  uuidOf :: a -> String

-- | Class of object that have a serial number.
class SerialNoObject a where
  serialOf :: a -> Int

-- | Class of objects that have tags.
class TagsObject a where
  tagsOf :: a -> Set.Set String

-- * Network definitions

-- ** Ipv4 types

data Ip4Address = Ip4Address Word8 Word8 Word8 Word8
  deriving (Eq, Ord)

mkIp4Address :: (Word8, Word8, Word8, Word8) -> Ip4Address
mkIp4Address (a, b, c, d) = Ip4Address a b c d

instance Show Ip4Address where
  show (Ip4Address a b c d) = intercalate "." $ map show [a, b, c, d]

readIp4Address :: (Applicative m, Monad m) => String -> m Ip4Address
readIp4Address s =
  case sepSplit '.' s of
    [a, b, c, d] -> Ip4Address <$>
                      tryRead "first octect" a <*>
                      tryRead "second octet" b <*>
                      tryRead "third octet"  c <*>
                      tryRead "fourth octet" d
    _ -> fail $ "Can't parse IPv4 address from string " ++ s

instance JSON Ip4Address where
  showJSON = showJSON . show
  readJSON (JSString s) = readIp4Address (fromJSString s)
  readJSON v = fail $ "Invalid JSON value " ++ show v ++ " for an IPv4 address"

-- Converts an address to a list of numbers
ip4AddressToList :: Ip4Address -> [Word8]
ip4AddressToList (Ip4Address a b c d) = [a, b, c, d]

-- | Converts an address into its ordinal number.
-- This is needed for indexing IP adresses in reservation pools.
ip4AddressToNumber :: Ip4Address -> Integer
ip4AddressToNumber = foldl (\n i -> 256 * n + toInteger i) 0 . ip4AddressToList

-- | Converts a number into an address.
-- This is needed for indexing IP adresses in reservation pools.
ip4AddressFromNumber :: Integer -> Ip4Address
ip4AddressFromNumber n =
  let s = state $ first fromInteger . swap . (`divMod` 256)
      (d, c, b, a) = evalState ((,,,) <$> s <*> s <*> s <*> s) n
   in Ip4Address a b c d

nextIp4Address :: Ip4Address -> Ip4Address
nextIp4Address = ip4AddressFromNumber . (+ 1) . ip4AddressToNumber

-- | Custom type for an IPv4 network.
data Ip4Network = Ip4Network { ip4netAddr :: Ip4Address
                             , ip4netMask :: Word8
                             }
                  deriving (Eq)

mkIp4Network :: Ip4Address -> Word8 -> Ip4Network
mkIp4Network = Ip4Network

instance Show Ip4Network where
  show (Ip4Network ip netmask) = show ip ++ "/" ++ show netmask

-- | JSON instance for 'Ip4Network'.
instance JSON Ip4Network where
  showJSON = showJSON . show
  readJSON (JSString s) =
    case sepSplit '/' (fromJSString s) of
      [ip, nm] -> do
        ip' <- readIp4Address ip
        nm' <- tryRead "parsing netmask" nm
        if nm' >= 0 && nm' <= 32
          then return $ Ip4Network ip' nm'
          else fail $ "Invalid netmask " ++ show nm' ++ " from string " ++
                      fromJSString s
      _ -> fail $ "Can't parse IPv4 network from string " ++ fromJSString s
  readJSON v = fail $ "Invalid JSON value " ++ show v ++ " for an IPv4 network"

-- ** Address pools

-- | Currently address pools just wrap a reservation 'BitArray'.
--
-- In future, 'Network' might be extended to include several address pools
-- and address pools might include their own ranges of addresses.
newtype AddressPool = AddressPool { apReservations :: BitArray }
  deriving (Eq, Ord, Show)

instance JSON AddressPool where
  showJSON = showJSON . apReservations
  readJSON = liftM AddressPool . readJSON

-- ** Ganeti \"network\" config object.

-- FIXME: Not all types might be correct here, since they
-- haven't been exhaustively deduced from the python code yet.
--
-- FIXME: When parsing, check that the ext_reservations and reservations
-- have the same length
$(buildObject "Network" "network" $
  [ simpleField "name"             [t| NonEmptyString |]
  , optionalField $
    simpleField "mac_prefix"       [t| String |]
  , simpleField "network"          [t| Ip4Network |]
  , optionalField $
    simpleField "network6"         [t| String |]
  , optionalField $
    simpleField "gateway"          [t| Ip4Address |]
  , optionalField $
    simpleField "gateway6"         [t| String |]
  , optionalField $
    simpleField "reservations"     [t| AddressPool |]
  , optionalField $
    simpleField "ext_reservations" [t| AddressPool |]
  ]
  ++ uuidFields
  ++ timeStampFields
  ++ serialFields
  ++ tagsFields)

instance SerialNoObject Network where
  serialOf = networkSerial

instance TagsObject Network where
  tagsOf = networkTags

instance UuidObject Network where
  uuidOf = networkUuid

instance TimeStampObject Network where
  cTimeOf = networkCtime
  mTimeOf = networkMtime

-- * NIC definitions

$(buildParam "Nic" "nicp"
  [ simpleField "mode" [t| NICMode |]
  , simpleField "link" [t| String  |]
  , simpleField "vlan" [t| String |]
  ])

$(buildObject "PartialNic" "nic" $
  [ simpleField "mac" [t| String |]
  , optionalField $ simpleField "ip" [t| String |]
  , simpleField "nicparams" [t| PartialNicParams |]
  , optionalField $ simpleField "network" [t| String |]
  , optionalField $ simpleField "name" [t| String |]
  ] ++ uuidFields)

instance UuidObject PartialNic where
  uuidOf = nicUuid

-- * Disk definitions

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

-- | Check the constraints for a VG/LV names (except the @\/dev\/@ check).
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
-- logical id, this is probably a good reference point.
data DiskLogicalId
  = LIDPlain LogicalVolume  -- ^ Volume group, logical volume
  | LIDDrbd8 String String Int Int Int DRBDSecret
  -- ^ NodeA, NodeB, Port, MinorA, MinorB, Secret
  | LIDFile FileDriver String -- ^ Driver, path
  | LIDSharedFile FileDriver String -- ^ Driver, path
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
        JSArray [nA, nB, p, mA, mB, k] -> do
          nA' <- readJSON nA
          nB' <- readJSON nB
          p'  <- readJSON p
          mA' <- readJSON mA
          mB' <- readJSON mB
          k'  <- readJSON k
          return $ LIDDrbd8 nA' nB' p' mA' mB' k'
        _ -> fail "Can't read logical_id for DRBD8 type"
    DTPlain ->
      case lid of
        JSArray [vg, lv] -> do
          vg' <- readJSON vg
          lv' <- readJSON lv
          return $ LIDPlain (LogicalVolume vg' lv')
        _ -> fail "Can't read logical_id for plain type"
    DTFile ->
      case lid of
        JSArray [driver, path] -> do
          driver' <- readJSON driver
          path'   <- readJSON path
          return $ LIDFile driver' path'
        _ -> fail "Can't read logical_id for file type"
    DTSharedFile ->
      case lid of
        JSArray [driver, path] -> do
          driver' <- readJSON driver
          path'   <- readJSON path
          return $ LIDSharedFile driver' path'
        _ -> fail "Can't read logical_id for shared file type"
    DTGluster ->
      case lid of
        JSArray [driver, path] -> do
          driver' <- readJSON driver
          path'   <- readJSON path
          return $ LIDSharedFile driver' path'
        _ -> fail "Can't read logical_id for shared file type"
    DTBlock ->
      case lid of
        JSArray [driver, path] -> do
          driver' <- readJSON driver
          path'   <- readJSON path
          return $ LIDBlockDev driver' path'
        _ -> fail "Can't read logical_id for blockdev type"
    DTRbd ->
      case lid of
        JSArray [driver, path] -> do
          driver' <- readJSON driver
          path'   <- readJSON path
          return $ LIDRados driver' path'
        _ -> fail "Can't read logical_id for rdb type"
    DTExt ->
      case lid of
        JSArray [extprovider, name] -> do
          extprovider' <- readJSON extprovider
          name'   <- readJSON name
          return $ LIDExt extprovider' name'
        _ -> fail "Can't read logical_id for extstorage type"
    DTDiskless ->
      fail "Retrieved 'diskless' disk."

-- | Disk data structure.
--
-- This is declared manually as it's a recursive structure, and our TH
-- code currently can't build it.
data Disk = Disk
  { diskLogicalId  :: DiskLogicalId
  , diskChildren   :: [Disk]
  , diskIvName     :: String
  , diskSize       :: Int
  , diskMode       :: DiskMode
  , diskName       :: Maybe String
  , diskSpindles   :: Maybe Int
  , diskParams     :: Maybe DiskParams
  , diskUuid       :: String
  , diskSerial     :: Int
  , diskCtime      :: ClockTime
  , diskMtime      :: ClockTime
  } deriving (Show, Eq)

$(buildObjectSerialisation "Disk" $
  [ customField 'decodeDLId 'encodeFullDLId ["dev_type"] $
      simpleField "logical_id"    [t| DiskLogicalId   |]
  , defaultField  [| [] |] $ simpleField "children" [t| [Disk] |]
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

instance UuidObject Disk where
  uuidOf = diskUuid

-- | Determines whether a disk or one of his children has the given logical id
-- (determined by the volume group name and by the logical volume name).
-- This can be true only for DRBD or LVM disks.
includesLogicalId :: LogicalVolume -> Disk -> Bool
includesLogicalId lv disk =
  case diskLogicalId disk of
    LIDPlain lv' -> lv' == lv
    LIDDrbd8 {} ->
      any (includesLogicalId lv) $ diskChildren disk
    _ -> False

-- * Instance definitions

$(buildParam "Be" "bep"
  [ specialNumericalField 'parseUnitAssumeBinary
      $ simpleField "minmem"      [t| Int  |]
  , specialNumericalField 'parseUnitAssumeBinary
      $ simpleField "maxmem"      [t| Int  |]
  , simpleField "vcpus"           [t| Int  |]
  , simpleField "auto_balance"    [t| Bool |]
  , simpleField "always_failover" [t| Bool |]
  , simpleField "spindle_use"     [t| Int  |]
  ])

$(buildObject "Instance" "inst" $
  [ simpleField "name"             [t| String             |]
  , simpleField "primary_node"     [t| String             |]
  , simpleField "os"               [t| String             |]
  , simpleField "hypervisor"       [t| Hypervisor         |]
  , simpleField "hvparams"         [t| HvParams           |]
  , simpleField "beparams"         [t| PartialBeParams    |]
  , simpleField "osparams"         [t| OsParams           |]
  , simpleField "osparams_private" [t| OsParamsPrivate    |]
  , simpleField "admin_state"      [t| AdminState         |]
  , simpleField "admin_state_source" [t| AdminStateSource   |]
  , simpleField "nics"             [t| [PartialNic]       |]
  , simpleField "disks"            [t| [String]           |]
  , simpleField "disk_template"    [t| DiskTemplate       |]
  , simpleField "disks_active"     [t| Bool               |]
  , optionalField $ simpleField "network_port" [t| Int  |]
  ]
  ++ timeStampFields
  ++ uuidFields
  ++ serialFields
  ++ tagsFields)

instance TimeStampObject Instance where
  cTimeOf = instCtime
  mTimeOf = instMtime

instance UuidObject Instance where
  uuidOf = instUuid

instance SerialNoObject Instance where
  serialOf = instSerial

instance TagsObject Instance where
  tagsOf = instTags

-- * IPolicy definitions

$(buildParam "ISpec" "ispec"
  [ simpleField ConstantUtils.ispecMemSize     [t| Int |]
  , simpleField ConstantUtils.ispecDiskSize    [t| Int |]
  , simpleField ConstantUtils.ispecDiskCount   [t| Int |]
  , simpleField ConstantUtils.ispecCpuCount    [t| Int |]
  , simpleField ConstantUtils.ispecNicCount    [t| Int |]
  , simpleField ConstantUtils.ispecSpindleUse  [t| Int |]
  ])

$(buildObject "MinMaxISpecs" "mmis"
  [ renameField "MinSpec" $ simpleField "min" [t| FilledISpecParams |]
  , renameField "MaxSpec" $ simpleField "max" [t| FilledISpecParams |]
  ])

-- | Custom partial ipolicy. This is not built via buildParam since it
-- has a special 2-level inheritance mode.
$(buildObject "PartialIPolicy" "ipolicy"
  [ optionalField . renameField "MinMaxISpecsP" $
    simpleField ConstantUtils.ispecsMinmax [t| [MinMaxISpecs] |]
  , optionalField . renameField "StdSpecP" $
    simpleField "std" [t| PartialISpecParams |]
  , optionalField . renameField "SpindleRatioP" $
    simpleField "spindle-ratio" [t| Double |]
  , optionalField . renameField "VcpuRatioP" $
    simpleField "vcpu-ratio" [t| Double |]
  , optionalField . renameField "DiskTemplatesP" $
    simpleField "disk-templates" [t| [DiskTemplate] |]
  ])

-- | Custom filled ipolicy. This is not built via buildParam since it
-- has a special 2-level inheritance mode.
$(buildObject "FilledIPolicy" "ipolicy"
  [ renameField "MinMaxISpecs" $
    simpleField ConstantUtils.ispecsMinmax [t| [MinMaxISpecs] |]
  , renameField "StdSpec" $ simpleField "std" [t| FilledISpecParams |]
  , simpleField "spindle-ratio"  [t| Double |]
  , simpleField "vcpu-ratio"     [t| Double |]
  , simpleField "disk-templates" [t| [DiskTemplate] |]
  ])

-- | Custom filler for the ipolicy types.
fillIPolicy :: FilledIPolicy -> PartialIPolicy -> FilledIPolicy
fillIPolicy (FilledIPolicy { ipolicyMinMaxISpecs  = fminmax
                           , ipolicyStdSpec       = fstd
                           , ipolicySpindleRatio  = fspindleRatio
                           , ipolicyVcpuRatio     = fvcpuRatio
                           , ipolicyDiskTemplates = fdiskTemplates})
            (PartialIPolicy { ipolicyMinMaxISpecsP  = pminmax
                            , ipolicyStdSpecP       = pstd
                            , ipolicySpindleRatioP  = pspindleRatio
                            , ipolicyVcpuRatioP     = pvcpuRatio
                            , ipolicyDiskTemplatesP = pdiskTemplates}) =
  FilledIPolicy { ipolicyMinMaxISpecs  = fromMaybe fminmax pminmax
                , ipolicyStdSpec       = case pstd of
                                         Nothing -> fstd
                                         Just p -> fillISpecParams fstd p
                , ipolicySpindleRatio  = fromMaybe fspindleRatio pspindleRatio
                , ipolicyVcpuRatio     = fromMaybe fvcpuRatio pvcpuRatio
                , ipolicyDiskTemplates = fromMaybe fdiskTemplates
                                         pdiskTemplates
                }
-- * Node definitions

$(buildParam "ND" "ndp"
  [ simpleField "oob_program"   [t| String |]
  , simpleField "spindle_count" [t| Int    |]
  , simpleField "exclusive_storage" [t| Bool |]
  , simpleField "ovs"           [t| Bool |]
  , simpleField "ovs_name"       [t| String |]
  , simpleField "ovs_link"       [t| String |]
  , simpleField "ssh_port"      [t| Int |]
  , simpleField "cpu_speed"     [t| Double |]
  ])

$(buildObject "Node" "node" $
  [ simpleField "name"             [t| String |]
  , simpleField "primary_ip"       [t| String |]
  , simpleField "secondary_ip"     [t| String |]
  , simpleField "master_candidate" [t| Bool   |]
  , simpleField "offline"          [t| Bool   |]
  , simpleField "drained"          [t| Bool   |]
  , simpleField "group"            [t| String |]
  , simpleField "master_capable"   [t| Bool   |]
  , simpleField "vm_capable"       [t| Bool   |]
  , simpleField "ndparams"         [t| PartialNDParams |]
  , simpleField "powered"          [t| Bool   |]
  ]
  ++ timeStampFields
  ++ uuidFields
  ++ serialFields
  ++ tagsFields)

instance TimeStampObject Node where
  cTimeOf = nodeCtime
  mTimeOf = nodeMtime

instance UuidObject Node where
  uuidOf = nodeUuid

instance SerialNoObject Node where
  serialOf = nodeSerial

instance TagsObject Node where
  tagsOf = nodeTags

-- * NodeGroup definitions

-- | The cluster/group disk parameters type.
type GroupDiskParams = Container DiskParams

-- | A mapping from network UUIDs to nic params of the networks.
type Networks = Container PartialNicParams

$(buildObject "NodeGroup" "group" $
  [ simpleField "name"         [t| String |]
  , defaultField [| [] |] $ simpleField "members" [t| [String] |]
  , simpleField "ndparams"     [t| PartialNDParams |]
  , simpleField "alloc_policy" [t| AllocPolicy     |]
  , simpleField "ipolicy"      [t| PartialIPolicy  |]
  , simpleField "diskparams"   [t| GroupDiskParams |]
  , simpleField "networks"     [t| Networks        |]
  ]
  ++ timeStampFields
  ++ uuidFields
  ++ serialFields
  ++ tagsFields)

instance TimeStampObject NodeGroup where
  cTimeOf = groupCtime
  mTimeOf = groupMtime

instance UuidObject NodeGroup where
  uuidOf = groupUuid

instance SerialNoObject NodeGroup where
  serialOf = groupSerial

instance TagsObject NodeGroup where
  tagsOf = groupTags

-- | IP family type
$(declareIADT "IpFamily"
  [ ("IpFamilyV4", 'AutoConf.pyAfInet4)
  , ("IpFamilyV6", 'AutoConf.pyAfInet6)
  ])
$(makeJSONInstance ''IpFamily)

-- | Conversion from IP family to IP version. This is needed because
-- Python uses both, depending on context.
ipFamilyToVersion :: IpFamily -> Int
ipFamilyToVersion IpFamilyV4 = C.ip4Version
ipFamilyToVersion IpFamilyV6 = C.ip6Version

-- | Cluster HvParams (hvtype to hvparams mapping).
type ClusterHvParams = GenericContainer Hypervisor HvParams

-- | Cluster Os-HvParams (os to hvparams mapping).
type OsHvParams = Container ClusterHvParams

-- | Cluser BeParams.
type ClusterBeParams = Container FilledBeParams

-- | Cluster OsParams.
type ClusterOsParams = Container OsParams
type ClusterOsParamsPrivate = Container (Private OsParams)

-- | Cluster NicParams.
type ClusterNicParams = Container FilledNicParams

-- | A low-high UID ranges.
type UidRange = (Int, Int)

formatUidRange :: UidRange -> String
formatUidRange (lower, higher)
  | lower == higher = show lower
  | otherwise       = show lower ++ "-" ++ show higher

-- | Cluster UID Pool, list (low, high) UID ranges.
type UidPool = [UidRange]

-- | The iallocator parameters type.
type IAllocatorParams = Container JSValue

-- | The master candidate client certificate digests
type CandidateCertificates = Container String

-- | Disk state parameters.
--
-- As according to the documentation this option is unused by Ganeti,
-- the content is just a 'JSValue'.
type DiskState = Container JSValue

-- | Hypervisor state parameters.
--
-- As according to the documentation this option is unused by Ganeti,
-- the content is just a 'JSValue'.
type HypervisorState = Container JSValue

-- * Cluster definitions
$(buildObject "Cluster" "cluster" $
  [ simpleField "rsahostkeypub"                  [t| String                 |]
  , optionalField $
    simpleField "dsahostkeypub"                  [t| String                 |]
  , simpleField "highest_used_port"              [t| Int                    |]
  , simpleField "tcpudp_port_pool"               [t| [Int]                  |]
  , simpleField "mac_prefix"                     [t| String                 |]
  , optionalField $
    simpleField "volume_group_name"              [t| String                 |]
  , simpleField "reserved_lvs"                   [t| [String]               |]
  , optionalField $
    simpleField "drbd_usermode_helper"           [t| String                 |]
  , simpleField "master_node"                    [t| String                 |]
  , simpleField "master_ip"                      [t| String                 |]
  , simpleField "master_netdev"                  [t| String                 |]
  , simpleField "master_netmask"                 [t| Int                    |]
  , simpleField "use_external_mip_script"        [t| Bool                   |]
  , simpleField "cluster_name"                   [t| String                 |]
  , simpleField "file_storage_dir"               [t| String                 |]
  , simpleField "shared_file_storage_dir"        [t| String                 |]
  , simpleField "gluster_storage_dir"            [t| String                 |]
  , simpleField "enabled_hypervisors"            [t| [Hypervisor]           |]
  , simpleField "hvparams"                       [t| ClusterHvParams        |]
  , simpleField "os_hvp"                         [t| OsHvParams             |]
  , simpleField "beparams"                       [t| ClusterBeParams        |]
  , simpleField "osparams"                       [t| ClusterOsParams        |]
  , simpleField "osparams_private_cluster"       [t| ClusterOsParamsPrivate |]
  , simpleField "nicparams"                      [t| ClusterNicParams       |]
  , simpleField "ndparams"                       [t| FilledNDParams         |]
  , simpleField "diskparams"                     [t| GroupDiskParams        |]
  , simpleField "candidate_pool_size"            [t| Int                    |]
  , simpleField "modify_etc_hosts"               [t| Bool                   |]
  , simpleField "modify_ssh_setup"               [t| Bool                   |]
  , simpleField "maintain_node_health"           [t| Bool                   |]
  , simpleField "uid_pool"                       [t| UidPool                |]
  , simpleField "default_iallocator"             [t| String                 |]
  , simpleField "default_iallocator_params"      [t| IAllocatorParams       |]
  , simpleField "hidden_os"                      [t| [String]               |]
  , simpleField "blacklisted_os"                 [t| [String]               |]
  , simpleField "primary_ip_family"              [t| IpFamily               |]
  , simpleField "prealloc_wipe_disks"            [t| Bool                   |]
  , simpleField "ipolicy"                        [t| FilledIPolicy          |]
  , defaultField [| emptyContainer |] $
    simpleField "hv_state_static"                [t| HypervisorState        |]
  , defaultField [| emptyContainer |] $
    simpleField "disk_state_static"              [t| DiskState              |]
  , simpleField "enabled_disk_templates"         [t| [DiskTemplate]         |]
  , simpleField "candidate_certs"                [t| CandidateCertificates  |]
  , simpleField "max_running_jobs"               [t| Int                    |]
  , simpleField "max_tracked_jobs"               [t| Int                    |]
  , simpleField "install_image"                  [t| String                 |]
  , simpleField "instance_communication_network" [t| String                 |]
  , simpleField "zeroing_image"                  [t| String                 |]
  , simpleField "compression_tools"              [t| [String]               |]
  , simpleField "enabled_user_shutdown"          [t| Bool                   |]
 ]
 ++ timeStampFields
 ++ uuidFields
 ++ serialFields
 ++ tagsFields)

instance TimeStampObject Cluster where
  cTimeOf = clusterCtime
  mTimeOf = clusterMtime

instance UuidObject Cluster where
  uuidOf = clusterUuid

instance SerialNoObject Cluster where
  serialOf = clusterSerial

instance TagsObject Cluster where
  tagsOf = clusterTags

-- * ConfigData definitions

$(buildObject "ConfigData" "config" $
--  timeStampFields ++
  [ simpleField "version"    [t| Int                 |]
  , simpleField "cluster"    [t| Cluster             |]
  , simpleField "nodes"      [t| Container Node      |]
  , simpleField "nodegroups" [t| Container NodeGroup |]
  , simpleField "instances"  [t| Container Instance  |]
  , simpleField "networks"   [t| Container Network   |]
  , simpleField "disks"      [t| Container Disk      |]
  ]
  ++ timeStampFields
  ++ serialFields)

instance SerialNoObject ConfigData where
  serialOf = configSerial

instance TimeStampObject ConfigData where
  cTimeOf = configCtime
  mTimeOf = configMtime

-- * Master network parameters

$(buildObject "MasterNetworkParameters" "masterNetworkParameters"
  [ simpleField "uuid"      [t| String   |]
  , simpleField "ip"        [t| String   |]
  , simpleField "netmask"   [t| Int      |]
  , simpleField "netdev"    [t| String   |]
  , simpleField "ip_family" [t| IpFamily |]
  ])


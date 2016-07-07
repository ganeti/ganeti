{-| DRBD Data Types

This module holds the definition of the data types describing the status of
DRBD.

-}
{-

Copyright (C) 2012 Google Inc.
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
module Ganeti.Storage.Drbd.Types
  ( DRBDStatus(..)
  , VersionInfo(..)
  , DeviceInfo(..)
  , ConnState(..)
  , LocalRemote(..)
  , Role(..)
  , DiskState(..)
  , PerfIndicators(..)
  , SyncStatus(..)
  , SizeUnit(..)
  , Time(..)
  , TimeUnit(..)
  , AdditionalInfo(..)
  , DrbdInstMinor(..)
  ) where

import Control.Monad
import Text.JSON
import Text.Printf

import Ganeti.JSON (optFieldsToObj, optionalJSField)

--TODO: consider turning deviceInfos into an IntMap
-- | Data type contaning all the data about the status of DRBD.
data DRBDStatus =
  DRBDStatus
  { versionInfo :: VersionInfo  -- ^ Version information about DRBD
  , deviceInfos :: [DeviceInfo] -- ^ Per-minor information
  } deriving (Eq, Show)

-- | The DRBDStatus instance of JSON.
instance JSON DRBDStatus where
  showJSON d = makeObj
    [ ("versionInfo", showJSON $ versionInfo d)
    , ("deviceInfos", showJSONs $ deviceInfos d)
    ]

  readJSON = error "JSON read instance not implemented for type DRBDStatus"

-- | Data type describing the DRBD version.
data VersionInfo =
  VersionInfo
  { version    :: Maybe String -- ^ DRBD driver version
  , api        :: Maybe String -- ^ The api version
  , proto      :: Maybe String -- ^ The protocol version
  , srcversion :: Maybe String -- ^ The version of the source files
  , gitHash    :: Maybe String -- ^ Git hash of the source files
  , buildBy    :: Maybe String -- ^ Who built the binary (and,
                               -- optionally, when)
  } deriving (Eq, Show)

-- | The VersionInfo instance of JSON.
instance JSON VersionInfo where
  showJSON (VersionInfo versionF apiF protoF srcversionF gitHashF buildByF) =
    optFieldsToObj
      [ optionalJSField "version" versionF
      , optionalJSField "api" apiF
      , optionalJSField "proto" protoF
      , optionalJSField "srcversion" srcversionF
      , optionalJSField "gitHash" gitHashF
      , optionalJSField "buildBy" buildByF
      ]

  readJSON = error "JSON read instance not implemented for type VersionInfo"

-- | Data type describing a device.
data DeviceInfo =
  UnconfiguredDevice Int -- ^ An DRBD minor marked as unconfigured
  | -- | A configured DRBD minor
    DeviceInfo
      { minorNumber :: Int                  -- ^ The minor index of the device
      , connectionState :: ConnState        -- ^ State of the connection
      , resourceRoles :: LocalRemote Role   -- ^ Roles of the resources
      , diskStates :: LocalRemote DiskState -- ^ Status of the disks
      , replicationProtocol :: Char         -- ^ The replication protocol
                                            -- being used
      , ioFlags :: String                   -- ^ The input/output flags
      , perfIndicators :: PerfIndicators    -- ^ Performance indicators
      , syncStatus :: Maybe SyncStatus      -- ^ The status of the
                                            -- syncronization of the disk
                                            -- (only if it is happening)
      , resync :: Maybe AdditionalInfo      -- ^ Additional info by DRBD 8.0
      , actLog :: Maybe AdditionalInfo      -- ^ Additional info by DRBD 8.0
      , instName :: Maybe String            -- ^ The name of the associated
                                            -- instance
      } deriving (Eq, Show)

-- | The DeviceInfo instance of JSON.
instance JSON DeviceInfo where
  showJSON (UnconfiguredDevice num) = makeObj
    [ ("minor", showJSON num)
    , ("connectionState", showJSON Unconfigured)
    ]
  showJSON (DeviceInfo minorNumberF connectionStateF (LocalRemote
    localRole remoteRole) (LocalRemote localState remoteState)
    replicProtocolF ioFlagsF perfIndicatorsF syncStatusF _ _ instNameF) =
    optFieldsToObj
    [ Just ("minor", showJSON minorNumberF)
    , Just ("connectionState", showJSON connectionStateF)
    , Just ("localRole", showJSON localRole)
    , Just ("remoteRole", showJSON remoteRole)
    , Just ("localState", showJSON localState)
    , Just ("remoteState", showJSON remoteState)
    , Just ("replicationProtocol", showJSON replicProtocolF)
    , Just ("ioFlags", showJSON ioFlagsF)
    , Just ("perfIndicators", showJSON perfIndicatorsF)
    , optionalJSField "syncStatus" syncStatusF
    , Just ("instance", maybe JSNull showJSON instNameF)
    ]

  readJSON = error "JSON read instance not implemented for type DeviceInfo"

-- | Data type describing the state of the connection.
data ConnState
  = StandAlone     -- ^  No network configuration available
  | Disconnecting  -- ^ Temporary state during disconnection
  | Unconnected    -- ^ Prior to a connection attempt
  | Timeout        -- ^ Following a timeout in the communication
  | BrokenPipe     -- ^ After the connection to the peer was lost
  | NetworkFailure -- ^ After the connection to the partner was lost
  | ProtocolError  -- ^ After the connection to the partner was lost
  | TearDown       -- ^ The peer is closing the connection
  | WFConnection   -- ^ Waiting for the peer to become visible
  | WFReportParams -- ^ Waiting for first packet from peer
  | Connected      -- ^ Connected, data mirroring active
  | StartingSyncS  -- ^ Source of a full sync started by admin
  | StartingSyncT  -- ^ Target of a full sync started by admin
  | WFBitMapS      -- ^ Source of a just starting partial sync
  | WFBitMapT      -- ^ Target of a just starting partial sync
  | WFSyncUUID     -- ^ Synchronization is about to begin
  | SyncSource     -- ^ Source of a running synchronization
  | SyncTarget     -- ^ Target of a running synchronization
  | PausedSyncS    -- ^ Source of a paused synchronization
  | PausedSyncT    -- ^ Target of a paused synchronization
  | VerifyS        -- ^ Source of a running verification
  | VerifyT        -- ^ Target of a running verification
  | Unconfigured   -- ^ The device is not configured
    deriving (Show, Eq)

-- | The ConnState instance of JSON.
instance JSON ConnState where
  showJSON = showJSON . show

  readJSON = error "JSON read instance not implemented for type ConnState"

-- | Algebraic data type describing something that has a local and a remote
-- value.
data LocalRemote a =
  LocalRemote
  { local  :: a -- ^ The local value
  , remote :: a -- ^ The remote value
  } deriving (Eq, Show)

-- | Data type describing.
data Role = Primary   -- ^ The device role is primary
          | Secondary -- ^ The device role is secondary
          | Unknown   -- ^ The device role is unknown
            deriving (Eq, Show)

-- | The Role instance of JSON.
instance JSON Role where
  showJSON = showJSON . show

  readJSON = error "JSON read instance not implemented for type Role"

-- | Data type describing disk states.
data DiskState
  = Diskless     -- ^ No local block device assigned to the DRBD driver
  | Attaching    -- ^ Reading meta data
  | Failed       -- ^ I/O failure
  | Negotiating  -- ^ "Attach" on an already-connected device
  | Inconsistent -- ^ The data is inconsistent between nodes.
  | Outdated     -- ^ Data consistent but outdated
  | DUnknown     -- ^ No network connection available
  | Consistent   -- ^ Consistent data, but without network connection
  | UpToDate     -- ^ Consistent, up-to-date. This is the normal state
    deriving (Eq, Show)

-- | The DiskState instance of JSON.
instance JSON DiskState where
  showJSON = showJSON . show

  readJSON = error "JSON read instance not implemented for type DiskState"

-- | Data type containing data about performance indicators.
data PerfIndicators = PerfIndicators
  { networkSend :: Int -- ^ KiB of data sent on the network
  , networkReceive :: Int -- ^ KiB of data received from the network
  , diskWrite :: Int -- ^ KiB of data written on local disk
  , diskRead :: Int -- ^ KiB of data read from local disk
  , activityLog :: Int -- ^ Number of updates of the activity log
  , bitMap :: Int -- ^ Number of updates to the bitmap area of the metadata
  , localCount :: Int -- ^ Number of open requests to the local I/O subsystem
  , pending :: Int -- ^ Num of requests sent to the partner but not yet answered
  , unacknowledged :: Int -- ^ Num of requests received by the partner but still
                        -- to be answered
  , applicationPending :: Int -- ^ Num of block I/O requests forwarded
                              -- to DRBD but that have not yet been
                              -- answered
  , epochs :: Maybe Int -- ^ Number of epoch objects
  , writeOrder :: Maybe Char -- ^ Currently used write ordering method
  , outOfSync :: Maybe Int -- ^ KiB of storage currently out of sync
  } deriving (Eq, Show)

-- | The PerfIndicators instance of JSON.
instance JSON PerfIndicators where
  showJSON p = optFieldsToObj
    [ Just ("networkSend", showJSON $ networkSend p)
    , Just ("networkReceive", showJSON $ networkReceive p)
    , Just ("diskWrite", showJSON $ diskWrite p)
    , Just ("diskRead", showJSON $ diskRead p)
    , Just ("activityLog", showJSON $ activityLog p)
    , Just ("bitMap", showJSON $ bitMap p)
    , Just ("localCount", showJSON $ localCount p)
    , Just ("pending", showJSON $ pending p)
    , Just ("unacknowledged", showJSON $ unacknowledged p)
    , Just ("applicationPending", showJSON $ applicationPending p)
    , optionalJSField "epochs" $ epochs p
    , optionalJSField "writeOrder" $ writeOrder p
    , optionalJSField "outOfSync" $ outOfSync p
    ]

  readJSON = error "JSON read instance not implemented for type PerfIndicators"

-- | Data type containing data about the synchronization status of a device.
data SyncStatus =
  SyncStatus
  { percentage      :: Double    -- ^ Percentage of syncronized data
  , partialSyncSize :: Int       -- ^ Numerator of the fraction of synced data
  , totalSyncSize   :: Int       -- ^ Denominator of the fraction of
                                 -- synced data
  , syncUnit        :: SizeUnit  -- ^ Measurement unit of the previous
                                 -- fraction
  , timeToFinish    :: Time      -- ^ Expected time before finishing
                                 -- the syncronization
  , speed           :: Int       -- ^ Speed of the syncronization
  , want            :: Maybe Int -- ^ Want of the syncronization
  , speedSizeUnit   :: SizeUnit  -- ^ Size unit of the speed
  , speedTimeUnit   :: TimeUnit  -- ^ Time unit of the speed
  } deriving (Eq, Show)

-- | The SyncStatus instance of JSON.
instance JSON SyncStatus where
  showJSON s = optFieldsToObj
    [ Just ("percentage", showJSON $ percentage s)
    , Just ("progress", showJSON $ show (partialSyncSize s) ++ "/" ++
        show (totalSyncSize s))
    , Just ("progressUnit", showJSON $ syncUnit s)
    , Just ("timeToFinish", showJSON $ timeToFinish s)
    , Just ("speed", showJSON $ speed s)
    , optionalJSField "want" $ want s
    , Just ("speedUnit", showJSON $ show (speedSizeUnit s) ++ "/" ++
        show (speedTimeUnit s))
    ]

  readJSON = error "JSON read instance not implemented for type SyncStatus"

-- | Data type describing a size unit for memory.
data SizeUnit = KiloByte | MegaByte deriving (Eq, Show)

-- | The SizeUnit instance of JSON.
instance JSON SizeUnit where
  showJSON = showJSON . show

  readJSON = error "JSON read instance not implemented for type SizeUnit"

-- | Data type describing a time (hh:mm:ss).
data Time = Time
  { hour :: Int
  , min  :: Int
  , sec  :: Int
  } deriving (Eq, Show)

-- | The Time instance of JSON.
instance JSON Time where
  showJSON (Time h m s) = showJSON (printf "%02d:%02d:%02d" h m s :: String)

  readJSON = error "JSON read instance not implemented for type Time"

-- | Data type describing a time unit.
data TimeUnit = Second deriving (Eq, Show)

-- | The TimeUnit instance of JSON.
instance JSON TimeUnit where
  showJSON Second = showJSON "Second"

  readJSON = error "JSON read instance not implemented for type TimeUnit"

-- | Additional device-specific cache-like information produced by
-- drbd <= 8.0.
--
-- Internal debug information exported by old DRBD versions.
-- Undocumented both in DRBD and here.
data AdditionalInfo = AdditionalInfo
  { partialUsed :: Int
  , totalUsed   :: Int
  , hits        :: Int
  , misses      :: Int
  , starving    :: Int
  , dirty       :: Int
  , changed     :: Int
  } deriving (Eq, Show)

-- | Data type representing the pairing of a DRBD minor with an instance.
data DrbdInstMinor = DrbdInstMinor
  { dimNode :: String
  , dimMinor :: Int
  , dimInstName :: String
  , dimDiskIdx :: String
  , dimRole :: String
  , dimPeer :: String
  } deriving (Show)

-- | The DrbdInstMinor instance of JSON.
instance JSON DrbdInstMinor where
  showJSON (DrbdInstMinor a b c d e f) =
    JSArray
      [ showJSON a
      , showJSON b
      , showJSON c
      , showJSON d
      , showJSON e
      , showJSON f
      ]
  readJSON (JSArray [a, b, c, d, e, f]) =
    DrbdInstMinor
      `fmap` readJSON a
      `ap` readJSON b
      `ap` readJSON c
      `ap` readJSON d
      `ap` readJSON e
      `ap` readJSON f
  readJSON _ = fail "Unable to read a DrbdInstMinor"

{-| DRBD Data Types

This module holds the definition of the data types describing the status of
DRBD.

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
module Ganeti.Block.Drbd.Types
  ( DRBDStatus(..)
  , VersionInfo(..)
  , DeviceInfo(..)
  , ConnectionState(..)
  , LocalRemote(..)
  , Role(..)
  , DiskState(..)
  , PerformanceIndicators(..)
  , SyncStatus(..)
  , SizeUnit(..)
  , Time(..)
  , TimeUnit(..)
  , AdditionalInfo(..)
  ) where

--TODO: consider turning deviceInfos into an IntMap
-- | Data type contaning all the data about the status of DRBD.
data DRBDStatus =
  DRBDStatus
  { versionInfo :: VersionInfo  -- ^ Version information about DRBD
  , deviceInfos :: [DeviceInfo] -- ^ Per-minor information
  } deriving (Eq, Show)

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

-- | Data type describing a device.
data DeviceInfo =
  UnconfiguredDevice Int -- ^ An DRBD minor marked as unconfigured
  | -- | A configured DRBD minor
    DeviceInfo
      { minorNumber :: Int -- ^ The minor index of the device
      , connectionState :: ConnectionState -- ^ State of the connection
      , resourceRoles :: LocalRemote Role -- ^ Roles of the resources
      , diskStates :: LocalRemote DiskState -- ^ Status of the disks
      , replicationProtocol :: Char -- ^ The replication protocol being used
      , ioFlags :: String -- ^ The input/output flags
      , performanceIndicators :: PerformanceIndicators -- ^ Performance indicators
      , syncStatus :: Maybe SyncStatus -- ^ The status of the syncronization of
                                     -- the disk (only if it is happening)
      , resync :: Maybe AdditionalInfo -- ^ Additional info by DRBD 8.0
      , actLog :: Maybe AdditionalInfo -- ^ Additional info by DRBD 8.0
      } deriving (Eq, Show)

-- | Data type describing the state of the connection.
data ConnectionState
  = StandAlone     -- ^  No network configuration available
  | Disconnecting  -- ^ Temporary state during disconnection
  | Unconnected    -- ^ Prior to a connection attempt
  | Timeout        -- ^ Following a timeout in the communication
  | BrokenPipe     -- ^ After the connection to the peer was lost
  | NetworkFailure -- ^ After the connection to the parner was lost
  | ProtocolError  -- ^ After the connection to the parner was lost
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
  | VerifyS        -- ^ Source of an running verification
  | VerifyT        -- ^ Target of an running verification
  | Unconfigured   -- ^ The device is not configured
    deriving (Show, Eq)

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

-- | Data type containing data about performance indicators.
data PerformanceIndicators = PerformanceIndicators
  { networkSend :: Int -- ^ KiB of data sent on the network
  , networkReceive :: Int -- ^ KiB of data received from the network
  , diskWrite :: Int -- ^ KiB of data written on local disk
  , diskRead :: Int -- ^ KiB of data read from local disk
  , activityLog :: Int -- ^ Number of updates of the activity log
  , bitMap :: Int -- ^ Number of updates to the bitmap area of the metadata
  , localCount :: Int -- ^ Number of open requests to te local I/O subsystem
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

-- | Data type describing a size unit for memory.
data SizeUnit = KiloByte | MegaByte deriving (Eq, Show)

-- | Data type describing a time (hh:mm:ss).
data Time = Time
  { hour :: Integer
  , min  :: Integer
  , sec  :: Integer
  } deriving (Eq, Show)

-- | Data type describing a time unit.
data TimeUnit = Second deriving (Eq, Show)

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

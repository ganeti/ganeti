{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti data collector types.

-}

{-

Copyright (C) 2012, 2013 Google Inc.

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

module Ganeti.DataCollectors.Types
  ( addStatus
  , DCCategory(..)
  , DCKind(..)
  , DCReport(..)
  , DCStatus(..)
  , DCStatusCode(..)
  , DCVersion(..)
  , buildReport
  ) where

import Text.JSON

import Ganeti.Constants as C
import Ganeti.THH
import Ganeti.Utils (getCurrentTime)

-- | The possible classes a data collector can belong to.
data DCCategory = DCInstance | DCStorage | DCDaemon | DCHypervisor
  deriving (Show, Eq)

-- | The JSON instance for DCCategory.
instance JSON DCCategory where
  showJSON = showJSON . show
  readJSON =
    error "JSON read instance not implemented for type DCCategory"

-- | The possible status codes of a data collector.
data DCStatusCode = DCSCOk      -- ^ Everything is OK
                  | DCSCTempBad -- ^ Bad, but being automatically fixed
                  | DCSCUnknown -- ^ Unable to determine the status
                  | DCSCBad     -- ^ Bad. External intervention required
                  deriving (Show, Eq, Ord)

-- | The JSON instance for CollectorStatus.
instance JSON DCStatusCode where
  showJSON DCSCOk      = showJSON (0 :: Int)
  showJSON DCSCTempBad = showJSON (1 :: Int)
  showJSON DCSCUnknown = showJSON (2 :: Int)
  showJSON DCSCBad     = showJSON (4 :: Int)
  readJSON = error "JSON read instance not implemented for type DCStatusCode"

-- | The status of a \"status reporting data collector\".
$(buildObject "DCStatus" "dcStatus"
  [ simpleField "code"    [t| DCStatusCode |]
  , simpleField "message" [t| String |]
  ])

-- | The type representing the kind of the collector.
data DCKind = DCKPerf   -- ^ Performance reporting collector
            | DCKStatus -- ^ Status reporting collector
            deriving (Show, Eq)

-- | The JSON instance for CollectorKind.
instance JSON DCKind where
  showJSON DCKPerf   = showJSON (0 :: Int)
  showJSON DCKStatus = showJSON (1 :: Int)
  readJSON = error "JSON read instance not implemented for type DCKind"

-- | Type representing the version number of a data collector.
data DCVersion = DCVerBuiltin | DCVersion String deriving (Show, Eq)

-- | The JSON instance for DCVersion.
instance JSON DCVersion where
  showJSON DCVerBuiltin = showJSON C.builtinDataCollectorVersion
  showJSON (DCVersion v) = showJSON v
  readJSON = error "JSON read instance not implemented for type DCVersion"

-- | This is the format of the report produced by each data collector.
$(buildObject "DCReport" "dcReport"
  [ simpleField "name"           [t| String |]
  , simpleField "version"        [t| DCVersion |]
  , simpleField "format_version" [t| Int |]
  , simpleField "timestamp"      [t| Integer |]
  , optionalNullSerField $
      simpleField "category"     [t| DCCategory |]
  , simpleField "kind"           [t| DCKind |]
  , simpleField "data"           [t| JSValue |]
  ])

-- | Add the data collector status information to the JSON representation of
-- the collector data.
addStatus :: DCStatus -> JSValue -> JSValue
addStatus dcStatus (JSObject obj) =
  makeObj $ ("status", showJSON dcStatus) : fromJSObject obj
addStatus dcStatus value = makeObj
  [ ("status", showJSON dcStatus)
  , ("data", value)
  ]

-- | Utility function for building a report automatically adding the current
-- timestamp (rounded up to seconds).
-- If the version is not specified, it will be set to the value indicating
-- a builtin collector.
buildReport :: String -> DCVersion -> Int -> Maybe DCCategory -> DCKind
            -> JSValue -> IO DCReport
buildReport name version format_version category kind jsonData = do
  now <- getCurrentTime
  let timestamp = now * 1000000000 :: Integer
  return $
    DCReport name version format_version timestamp category kind
      jsonData

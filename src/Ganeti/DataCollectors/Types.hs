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
  , CollectorData(..)
  , CollectorMap
  , buildReport
  , mergeStatuses
  , getCategoryName
  ) where

import Data.Char
import Data.Ratio
import qualified Data.Map as Map
import qualified Data.Sequence as Seq
import Text.JSON

import Ganeti.Constants as C
import Ganeti.THH
import Ganeti.Utils (getCurrentTime)

-- | The possible classes a data collector can belong to.
data DCCategory = DCInstance | DCStorage | DCDaemon | DCHypervisor
  deriving (Show, Eq, Read)

-- | Get the category name and return it as a string.
getCategoryName :: DCCategory -> String
getCategoryName dcc = map toLower . drop 2 . show $ dcc

categoryNames :: Map.Map String DCCategory
categoryNames =
  let l = [DCInstance, DCStorage, DCDaemon, DCHypervisor]
  in Map.fromList $ zip (map getCategoryName l) l

-- | The JSON instance for DCCategory.
instance JSON DCCategory where
  showJSON = showJSON . getCategoryName
  readJSON (JSString s) =
    let s' = fromJSString s
    in case Map.lookup s' categoryNames of
         Just category -> Ok category
         Nothing -> fail $ "Invalid category name " ++ s' ++ " for type\
                           \ DCCategory"
  readJSON v = fail $ "Invalid JSON value " ++ show v ++ " for type DCCategory"

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
  readJSON (JSRational _ x) =
    if denominator x /= 1
    then fail $ "Invalid JSON value " ++ show x ++ " for type DCKind"
    else
      let x' = (fromIntegral . numerator $ x) :: Int
      in if x' == 0 then Ok DCKPerf
         else if x' == 1 then Ok DCKStatus
         else fail $ "Invalid JSON value " ++ show x' ++ " for type DCKind"
  readJSON v = fail $ "Invalid JSON value " ++ show v ++ " for type DCKind"

-- | Type representing the version number of a data collector.
data DCVersion = DCVerBuiltin | DCVersion String deriving (Show, Eq)

-- | The JSON instance for DCVersion.
instance JSON DCVersion where
  showJSON DCVerBuiltin = showJSON C.builtinDataCollectorVersion
  showJSON (DCVersion v) = showJSON v
  readJSON (JSString s) =
    if fromJSString s == C.builtinDataCollectorVersion
    then Ok DCVerBuiltin else Ok . DCVersion $ fromJSString s
  readJSON v = fail $ "Invalid JSON value " ++ show v ++ " for type DCVersion"

-- | Type for the value field of the above map.
data CollectorData = CPULoadData (Seq.Seq (Integer, [Int]))

-- | Type for the map storing the data of the statefull DataCollectors.
type CollectorMap = Map.Map String CollectorData

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

-- | Helper function for merging statuses.
mergeStatuses :: (DCStatusCode, String) -> (DCStatusCode, [String])
              -> (DCStatusCode, [String])
mergeStatuses (newStat, newStr) (storedStat, storedStrs) =
  let resStat = max newStat storedStat
      resStrs =
        if newStr == ""
          then storedStrs
          else storedStrs ++ [newStr]
  in (resStat, resStrs)

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

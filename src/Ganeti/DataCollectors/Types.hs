{-# LANGUAGE TemplateHaskell, CPP #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Implementation of the Ganeti data collector types.

-}

{-

Copyright (C) 2012, 2013 Google Inc.
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
  , ReportBuilder(..)
  , DataCollector(..)
  ) where

import Control.DeepSeq (NFData, rnf)
#if !MIN_VERSION_containers(0,5,0)
import Control.Seq (using, seqFoldable, rdeepseq)
#endif
import Data.Char
import Data.Ratio
import qualified Data.Map as Map
import qualified Data.Sequence as Seq
import System.Time (ClockTime(..))
import Text.JSON
import Ganeti.Constants as C
import Ganeti.Objects (ConfigData)
import Ganeti.THH
import Ganeti.Utils (getCurrentTimeUSec)

-- | The possible classes a data collector can belong to.
data DCCategory = DCInstance | DCStorage | DCDaemon | DCHypervisor
  deriving (Show, Eq, Read, Enum, Bounded)

-- | Get the category name and return it as a string.
getCategoryName :: DCCategory -> String
getCategoryName dcc = map toLower . drop 2 . show $ dcc

categoryNames :: Map.Map String DCCategory
categoryNames =
  let l = [minBound ..]
  in Map.fromList $ zip (map getCategoryName l) l

-- | The JSON instance for DCCategory.
instance JSON DCCategory where
  showJSON = showJSON . getCategoryName
  readJSON (JSString s) =
    let s' = fromJSString s
    in case Map.lookup s' categoryNames of
         Just category -> Ok category
         Nothing -> fail $ "Invalid category name " ++ s' ++ " for type"
                           ++ " DCCategory"
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

-- | Type for the value field of the `CollectorMap` below.
data CollectorData =
  CPULoadData (Seq.Seq (ClockTime, [Int]))
  | InstanceCpuLoad (Map.Map String (Seq.Seq (ClockTime, Double)))

instance NFData ClockTime where
  rnf (TOD x y) = rnf x `seq` rnf y

#if MIN_VERSION_containers(0,5,0)

instance NFData CollectorData where
  rnf (CPULoadData x) = rnf x
  rnf (InstanceCpuLoad x) = rnf x

#else

{-

In older versions of the containers library, Seq is not an
instance of NFData, so use a generic way to reduce to normal
form

-}

instance NFData CollectorData where
  rnf (CPULoadData x) =  (x `using` seqFoldable rdeepseq) `seq` ()
  rnf (InstanceCpuLoad x) = (x `using` seqFoldable (seqFoldable rdeepseq))
                            `seq` ()

#endif

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
  usecs <- getCurrentTimeUSec
  let timestamp = usecs * 1000 :: Integer
  return $
    DCReport name version format_version timestamp category kind
      jsonData

-- | A report of a data collector might be stateful or stateless.
data ReportBuilder = StatelessR (IO DCReport)
                   | StatefulR (Maybe CollectorData -> IO DCReport)

type Name = String

-- | Type describing a data collector basic information
data DataCollector = DataCollector
  { dName     :: Name           -- ^ Name of the data collector
  , dCategory :: Maybe DCCategory -- ^ Category (storage, instance, ecc)
                                 --   of the collector
  , dKind     :: DCKind         -- ^ Kind (performance or status reporting) of
                                 --   the data collector
  , dReport   :: ReportBuilder  -- ^ Report produced by the collector
  , dUpdate   :: Maybe (Maybe CollectorData -> IO CollectorData)
                                 -- ^ Update operation for stateful collectors.
  , dActive   :: Name -> ConfigData -> Bool
                    -- ^ Checks if the collector applies for the cluster.
  , dInterval :: Name -> ConfigData -> Integer
                    -- ^ Interval between collection in microseconds
  }

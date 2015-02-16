{-| xentop CPU data collector

-}

{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.DataCollectors.XenCpuLoad
  ( dcName
  , dcVersion
  , dcFormatVersion
  , dcCategory
  , dcKind
  , dcReport
  , dcUpdate
  ) where

import Control.Monad (liftM, when)
import Control.Monad.IO.Class (liftIO)
import qualified Data.Map as Map
import Data.Maybe (mapMaybe)
import qualified Data.Sequence as Seq
import System.Process (readProcess)
import qualified Text.JSON as J
import System.Time (getClockTime, ClockTime)

import Ganeti.BasicTypes (GenericResult(..), Result, genericResult, runResultT)
import qualified Ganeti.Constants as C
import Ganeti.DataCollectors.Types
import Ganeti.Utils (readMaybe, clockTimeToUSec)

-- | The name of this data collector.
dcName :: String
dcName = C.dataCollectorXenCpuLoad

-- | The version of this data collector.
dcVersion :: DCVersion
dcVersion = DCVerBuiltin

-- | The version number for the data format of this data collector.
dcFormatVersion :: Int
dcFormatVersion = 1

-- | The category of this data collector.
dcCategory :: Maybe DCCategory
dcCategory = Nothing

-- | The kind of this data collector.
dcKind :: DCKind
dcKind = DCKPerf

-- | Read xentop output, if this program is available.
readXentop :: IO (Result String)
readXentop =
  runResultT . liftIO $ readProcess C.xentopCommand ["-f", "-b", "-i", "1"] ""

-- | Parse output of xentop command.
parseXentop :: String -> Result (Map.Map String Double)
parseXentop s = do
  let values = map words $ lines s
  case values of
    [] -> Bad "No output received"
    (name_header:_:cpu_header:_):vals -> do
      when (name_header /= "NAME" || cpu_header /= "CPU(sec)")
        $ Bad "Unexpected data format"
      return . Map.fromList
        $ mapMaybe
            (\ dom -> case dom of
                        name:_:cpu:_ -> if name /= "Domain-0"
                                          then liftM ((,) name) $ readMaybe cpu
                                          else Nothing
                        _ -> Nothing
            )
            vals
    _ -> Bad "Insufficient number of output columns"

-- | Updates the given Collector data.
dcUpdate :: Maybe CollectorData -> IO CollectorData
dcUpdate maybeCollector = do
  let oldData = case maybeCollector of
                  Just (InstanceCpuLoad x) -> x
                  _ -> Map.empty
  now <- getClockTime
  newResult <- liftM (>>= parseXentop) readXentop
  let newValues = Map.map (Seq.singleton . (,) now)
                  $ genericResult (const Map.empty) id newResult
      sampleSizeUSec = fromIntegral C.cpuavgloadWindowSize * 1000000
      combinedValues = Map.unionWith (Seq.><) newValues oldData
      withinRange = Map.map
                      (Seq.dropWhileR
                        ((<) sampleSizeUSec
                         . (clockTimeToUSec now -)
                         . clockTimeToUSec . fst))
                      combinedValues
  return $ InstanceCpuLoad withinRange

-- | From a list of timestamps and cumulative CPU data, compute the
-- average CPU activity in vCPUs.
loadAverage :: Seq.Seq (ClockTime, Double) -> Maybe Double
loadAverage observations = do
  when (Seq.null observations) Nothing
  let (t2, cpu2) = Seq.index observations 0
      (t1, cpu1) = Seq.index observations $ Seq.length observations - 1
      tUsec2 = clockTimeToUSec t2
      tUsec1 = clockTimeToUSec t1
  when (tUsec2 - tUsec1 < (fromIntegral C.xentopAverageThreshold * 1000000))
    Nothing
  return $ 1000000 * (cpu2 - cpu1) / fromIntegral (tUsec2 - tUsec1)

-- | The data exported by the data collector, taken from the default location.
dcReport :: Maybe CollectorData -> IO DCReport
dcReport maybeCollector =
  let collectedData = case maybeCollector of
                        Just (InstanceCpuLoad x) -> x
                        _ -> Map.empty
      loads = Map.mapMaybe loadAverage collectedData
  in buildReport dcName dcVersion dcFormatVersion dcCategory dcKind
      . J.JSObject . J.toJSObject . Map.toAscList $ Map.map J.showJSON loads

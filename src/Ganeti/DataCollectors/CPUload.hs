{-# OPTIONS_GHC -fno-warn-overlapping-patterns #-}
{-| @/proc/stat@ data collector.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.DataCollectors.CPUload
  ( dcName
  , dcVersion
  , dcFormatVersion
  , dcCategory
  , dcKind
  , dcReport
  , dcUpdate
  ) where

import Control.Arrow (first)
import qualified Control.Exception as E
import Data.Attoparsec.Text.Lazy as A
import Data.Maybe (fromMaybe)
import Data.Text.Lazy (pack, unpack)
import qualified Text.JSON as J
import qualified Data.Sequence as Seq
import System.Posix.Unistd (getSysVar, SysVar(ClockTick))
import System.Time (ClockTime(..), getClockTime)

import qualified Ganeti.BasicTypes as BT
import qualified Ganeti.Constants as C
import Ganeti.Cpu.LoadParser(cpustatParser)
import Ganeti.DataCollectors.Types
import qualified Ganeti.JSON as GJ
import Ganeti.Utils
import Ganeti.Cpu.Types

-- | The default path of the CPU status file.
-- It is hardcoded because it is not likely to change.
defaultFile :: FilePath
defaultFile = C.statFile

-- | The buffer size of the values kept in the map.
bufferSize :: Int
bufferSize = C.cpuavgloadBufferSize

-- | The window size of the values that will export the average load.
windowSize :: Integer
windowSize = toInteger C.cpuavgloadWindowSize

-- | The default setting for the maximum amount of not parsed character to
-- print in case of error.
-- It is set to use most of the screen estate on a standard 80x25 terminal.
-- TODO: add the possibility to set this with a command line parameter.
defaultCharNum :: Int
defaultCharNum = 80*20

-- | The name of this data collector.
dcName :: String
dcName = C.dataCollectorCPULoad

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

-- | The data exported by the data collector, taken from the default location.
dcReport :: Maybe CollectorData -> IO DCReport
dcReport colData =
  let extractColData c = case c of
        (CPULoadData v) -> Just v
        _ -> Nothing
      cpuLoadData = fromMaybe Seq.empty $ colData >>= extractColData
  in buildDCReport cpuLoadData

-- | Data stored by the collector in mond's memory.
type Buffer = Seq.Seq (ClockTime, [Int])

-- | Compute the load from a CPU.
computeLoad :: CPUstat -> Int
computeLoad cpuData =
  csUser cpuData + csNice cpuData + csSystem cpuData
  + csIowait cpuData + csIrq cpuData + csSoftirq cpuData
  + csSteal cpuData + csGuest cpuData + csGuestNice cpuData

-- | Reads and Computes the load for each CPU.
dcCollectFromFile :: FilePath -> IO (ClockTime, [Int])
dcCollectFromFile inputFile = do
  contents <-
    ((E.try $ readFile inputFile) :: IO (Either IOError String)) >>=
      exitIfBad "reading from file" . either (BT.Bad . show) BT.Ok
  cpustatData <-
    case A.parse cpustatParser $ pack contents of
      A.Fail unparsedText contexts errorMessage -> exitErr $
        show (Prelude.take defaultCharNum $ unpack unparsedText) ++ "\n"
          ++ show contexts ++ "\n" ++ errorMessage
      A.Done _ cpustatD -> return cpustatD
  now <- getClockTime
  return (now, map computeLoad cpustatData)

-- | Returns the collected data in the appropriate type.
dcCollect :: IO Buffer
dcCollect  = do
  l <- dcCollectFromFile defaultFile
  return (Seq.singleton l)

-- | Formats data for JSON transformation.
formatData :: [Double] -> CPUavgload
formatData [] = CPUavgload (0 :: Int) [] (0 :: Double)
formatData l@(x:xs) = CPUavgload (length l - 1) xs x

-- | Update a Map Entry.
updateEntry :: Buffer -> Buffer -> Buffer
updateEntry newBuffer mapEntry =
  (Seq.><) newBuffer
  (if Seq.length mapEntry < bufferSize
    then mapEntry
    else Seq.drop 1 mapEntry)

-- | Updates the given Collector data.
dcUpdate :: Maybe CollectorData -> IO CollectorData
dcUpdate mcd = do
  v <- dcCollect
  let new_v = fromMaybe v $ do
        cd <- mcd
        case cd of
          CPULoadData old_v -> return $ updateEntry v old_v
          _ -> Nothing
  new_v `seq` return $ CPULoadData new_v

-- | Computes the average load for every CPU and the overall from data read
-- from the map. Returns Bad if there are not enough values to compute it.
computeAverage :: Buffer -> Integer -> Integer -> BT.Result [Double]
computeAverage s w ticks =
  let inUSec = fmap (first clockTimeToUSec) s
      window = Seq.takeWhileL ((> w) . fst)  inUSec
      go Seq.EmptyL          _                    = BT.Bad "Empty buffer"
      go _                   Seq.EmptyR           = BT.Bad "Empty buffer"
      go (leftmost Seq.:< _) (_ Seq.:> rightmost) = do
        let (timestampL, listL) = leftmost
            (timestampR, listR) = rightmost
            workInWindow = zipWith (-) listL listR
            timediff = timestampL - timestampR
            overall = fromInteger (timediff * ticks) / 1000000 :: Double
        if overall > 0
          then BT.Ok $ map (flip (/) overall . fromIntegral) workInWindow
          else BT.Bad $ "Time covered by data is not sufficient."
                      ++ "The window considered is " ++ show w
  in go (Seq.viewl window) (Seq.viewr window)


-- | This function computes the JSON representation of the CPU load.
buildJsonReport :: Buffer -> IO J.JSValue
buildJsonReport v = do
  ticks <- getSysVar ClockTick
  let res = computeAverage v windowSize ticks
      showError s = J.showJSON $ GJ.containerFromList [("error", s)]
  return $ BT.genericResult showError (J.showJSON . formatData) res

-- | This function computes the DCReport for the CPU load.
buildDCReport :: Buffer -> IO DCReport
buildDCReport v  =
  buildJsonReport v >>=
    buildReport dcName dcVersion dcFormatVersion dcCategory dcKind

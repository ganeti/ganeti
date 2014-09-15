{-| DRBD data collector.

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

module Ganeti.DataCollectors.Drbd
  ( main
  , options
  , arguments
  , dcName
  , dcVersion
  , dcFormatVersion
  , dcCategory
  , dcKind
  , dcReport
  ) where


import qualified Control.Exception as E
import Control.Monad
import Data.Attoparsec.Text.Lazy as A
import Data.List
import Data.Maybe
import Data.Text.Lazy (pack, unpack)
import Network.BSD (getHostName)
import qualified Text.JSON as J

import qualified Ganeti.BasicTypes as BT
import qualified Ganeti.Constants as C
import Ganeti.Storage.Drbd.Parser(drbdStatusParser)
import Ganeti.Storage.Drbd.Types
import Ganeti.Common
import Ganeti.Confd.Client
import Ganeti.Confd.Types
import Ganeti.DataCollectors.CLI
import Ganeti.DataCollectors.Types
import Ganeti.Utils


-- | The default path of the DRBD status file.
-- It is hardcoded because it is not likely to change.
defaultFile :: FilePath
defaultFile = C.drbdStatusFile

-- | The default setting for the maximum amount of not parsed character to
-- print in case of error.
-- It is set to use most of the screen estate on a standard 80x25 terminal.
-- TODO: add the possibility to set this with a command line parameter.
defaultCharNum :: Int
defaultCharNum = 80*20

-- | The name of this data collector.
dcName :: String
dcName = C.dataCollectorDrbd

-- | The version of this data collector.
dcVersion :: DCVersion
dcVersion = DCVerBuiltin

-- | The version number for the data format of this data collector.
dcFormatVersion :: Int
dcFormatVersion = 1

-- | The category of this data collector.
dcCategory :: Maybe DCCategory
dcCategory = Just DCStorage

-- | The kind of this data collector.
dcKind :: DCKind
dcKind = DCKStatus

-- | The data exported by the data collector, taken from the default location.
dcReport :: IO DCReport
dcReport = buildDCReport defaultFile Nothing

-- * Command line options

options :: IO [OptType]
options =
  return
    [ oDrbdStatus
    , oDrbdPairing
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = [ArgCompletion OptComplFile 0 (Just 0)]

-- | Get information about the pairing of DRBD minors and Ganeti instances
-- on the current node. The information is taken from the Confd client
-- or, if a filename is specified, from a JSON encoded file (for testing
-- purposes).
getPairingInfo :: Maybe String -> IO (BT.Result [DrbdInstMinor])
getPairingInfo Nothing = do
  curNode <- getHostName
  client <- getConfdClient Nothing Nothing
  reply <- query client ReqNodeDrbd $ PlainQuery curNode
  return $
    case fmap (J.readJSONs . confdReplyAnswer) reply of
      Just (J.Ok instMinor) -> BT.Ok instMinor
      Just (J.Error msg) -> BT.Bad msg
      Nothing -> BT.Bad "No answer from the Confd server"
getPairingInfo (Just filename) = do
  content <- readFile filename
  return $
    case J.decode content of
      J.Ok instMinor -> BT.Ok instMinor
      J.Error msg -> BT.Bad msg

-- | Compute the status code and message, given the current DRBD data
-- The final state will have the code corresponding to the worst code of
-- all the devices, and the error message given from the concatenation of the
-- non-empty error messages.
computeStatus :: DRBDStatus -> DCStatus
computeStatus (DRBDStatus _ devInfos) =
  let statuses = map computeDevStatus devInfos
      (code, strList) = foldr mergeStatuses (DCSCOk, [""]) statuses
  in DCStatus code $ intercalate "\n" strList

-- | Compute the status of a DRBD device and its error message.
computeDevStatus :: DeviceInfo -> (DCStatusCode, String)
computeDevStatus (UnconfiguredDevice _) = (DCSCOk, "")
computeDevStatus dev =
  let errMsg s = show (minorNumber dev) ++ ": " ++ s
      compute_helper StandAlone =
        (DCSCBad, errMsg "No network config available")
      compute_helper Disconnecting =
        (DCSCBad, errMsg "The peer is being disconnected")
      compute_helper Unconnected =
        (DCSCTempBad, errMsg "Trying to establish a network connection")
      compute_helper Timeout =
        (DCSCTempBad, errMsg "Communication problems between the peers")
      compute_helper BrokenPipe =
        (DCSCTempBad, errMsg "Communication problems between the peers")
      compute_helper NetworkFailure =
        (DCSCTempBad, errMsg "Communication problems between the peers")
      compute_helper ProtocolError =
        (DCSCTempBad, errMsg "Communication problems between the peers")
      compute_helper TearDown =
        (DCSCBad, errMsg "The peer is closing the connection")
      compute_helper WFConnection =
        (DCSCTempBad, errMsg "Trying to establish a network connection")
      compute_helper WFReportParams =
        (DCSCTempBad, errMsg "Trying to establish a network connection")
      compute_helper Connected = (DCSCOk, "")
      compute_helper StartingSyncS = (DCSCOk, "")
      compute_helper StartingSyncT = (DCSCOk, "")
      compute_helper WFBitMapS = (DCSCOk, "")
      compute_helper WFBitMapT = (DCSCOk, "")
      compute_helper WFSyncUUID = (DCSCOk, "")
      compute_helper SyncSource = (DCSCOk, "")
      compute_helper SyncTarget = (DCSCOk, "")
      compute_helper PausedSyncS = (DCSCOk, "")
      compute_helper PausedSyncT = (DCSCOk, "")
      compute_helper VerifyS = (DCSCOk, "")
      compute_helper VerifyT = (DCSCOk, "")
      compute_helper Unconfigured = (DCSCOk, "")
  in compute_helper $ connectionState dev

-- | This function computes the JSON representation of the DRBD status.
buildJsonReport :: FilePath -> Maybe FilePath -> IO J.JSValue
buildJsonReport statusFile pairingFile = do
  contents <-
    ((E.try $ readFile statusFile) :: IO (Either IOError String)) >>=
      exitIfBad "reading from file" . either (BT.Bad . show) BT.Ok
  pairingResult <- getPairingInfo pairingFile
  pairing <- logWarningIfBad "Can't get pairing info" [] pairingResult
  drbdData <-
    case A.parse (drbdStatusParser pairing) $ pack contents of
      A.Fail unparsedText contexts errorMessage -> exitErr $
        show (Prelude.take defaultCharNum $ unpack unparsedText) ++ "\n"
          ++ show contexts ++ "\n" ++ errorMessage
      A.Done _ drbdS -> return drbdS
  let status = computeStatus drbdData
  return . addStatus status $ J.showJSON drbdData

-- | This function computes the DCReport for the DRBD status.
buildDCReport :: FilePath -> Maybe FilePath -> IO DCReport
buildDCReport statusFile pairingFile =
  buildJsonReport statusFile pairingFile >>=
    buildReport dcName dcVersion dcFormatVersion dcCategory dcKind

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  let statusFile = fromMaybe defaultFile $ optDrbdStatus opts
      pairingFile = optDrbdPairing opts
  unless (null args) . exitErr $ "This program takes exactly zero" ++
                                  " arguments, got '" ++ unwords args ++ "'"
  report <- buildDCReport statusFile pairingFile
  putStrLn $ J.encode report

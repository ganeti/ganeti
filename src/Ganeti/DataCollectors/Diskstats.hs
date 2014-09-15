{-| @/proc/diskstats@ data collector.

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

module Ganeti.DataCollectors.Diskstats
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
import Data.Maybe
import Data.Text.Lazy (pack, unpack)
import qualified Text.JSON as J

import qualified Ganeti.BasicTypes as BT
import qualified Ganeti.Constants as C
import Ganeti.Storage.Diskstats.Parser(diskstatsParser)
import Ganeti.Common
import Ganeti.DataCollectors.CLI
import Ganeti.DataCollectors.Types
import Ganeti.Utils


-- | The default path of the diskstats status file.
-- It is hardcoded because it is not likely to change.
defaultFile :: FilePath
defaultFile = C.diskstatsFile

-- | The default setting for the maximum amount of not parsed character to
-- print in case of error.
-- It is set to use most of the screen estate on a standard 80x25 terminal.
-- TODO: add the possibility to set this with a command line parameter.
defaultCharNum :: Int
defaultCharNum = 80*20

-- | The name of this data collector.
dcName :: String
dcName = C.dataCollectorDiskStats

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
dcKind = DCKPerf

-- | The data exported by the data collector, taken from the default location.
dcReport :: IO DCReport
dcReport = buildDCReport defaultFile

-- * Command line options

options :: IO [OptType]
options =
  return
    [ oInputFile
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = [ArgCompletion OptComplFile 0 (Just 0)]

-- | This function computes the JSON representation of the diskstats status.
buildJsonReport :: FilePath -> IO J.JSValue
buildJsonReport inputFile = do
  contents <-
    ((E.try $ readFile inputFile) :: IO (Either IOError String)) >>=
      exitIfBad "reading from file" . either (BT.Bad . show) BT.Ok
  diskstatsData <-
    case A.parse diskstatsParser $ pack contents of
      A.Fail unparsedText contexts errorMessage -> exitErr $
        show (Prelude.take defaultCharNum $ unpack unparsedText) ++ "\n"
          ++ show contexts ++ "\n" ++ errorMessage
      A.Done _ diskstatsD -> return diskstatsD
  return $ J.showJSON diskstatsData

-- | This function computes the DCReport for the diskstats status.
buildDCReport :: FilePath -> IO DCReport
buildDCReport inputFile =
  buildJsonReport inputFile >>=
    buildReport dcName dcVersion dcFormatVersion dcCategory dcKind

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  let inputFile = fromMaybe defaultFile $ optInputFile opts
  unless (null args) . exitErr $ "This program takes exactly zero" ++
                                  " arguments, got '" ++ unwords args ++ "'"
  report <- buildDCReport inputFile
  putStrLn $ J.encode report

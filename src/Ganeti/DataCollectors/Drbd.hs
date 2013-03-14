{-| DRBD data collector.

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

module Ganeti.DataCollectors.Drbd
  ( main
  , options
  , arguments
  , dcName
  ) where


import qualified Control.Exception as E
import Control.Monad
import Data.Attoparsec.Text.Lazy as A
import Data.Maybe
import Data.Text.Lazy (pack, unpack)
import Network.BSD (getHostName)
import qualified Text.JSON as J

import qualified Ganeti.BasicTypes as BT
import qualified Ganeti.Constants as C
import Ganeti.Block.Drbd.Parser(drbdStatusParser)
import Ganeti.Block.Drbd.Types(DrbdInstMinor)
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
dcName = "drbd"

-- | The version number for the data format of this data collector.
dcFormatVersion :: Int
dcFormatVersion = 1

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

-- | This function builds a report with the DRBD status.
buildDRBDReport :: FilePath -> Maybe FilePath -> IO DCReport
buildDRBDReport statusFile pairingFile = do
  contents <-
    ((E.try $ readFile statusFile) :: IO (Either IOError String)) >>=
      exitIfBad "reading from file" . either (BT.Bad . show) BT.Ok
  pairingResult <- getPairingInfo pairingFile
  pairing <- exitIfBad "Can't get pairing info" pairingResult
  jsonData <-
    case A.parse (drbdStatusParser pairing) $ pack contents of
      A.Fail unparsedText contexts errorMessage -> exitErr $
        show (Prelude.take defaultCharNum $ unpack unparsedText) ++ "\n"
          ++ show contexts ++ "\n" ++ errorMessage
      A.Done _ drbdStatus -> return $ J.showJSON drbdStatus
  buildReport dcName Nothing dcFormatVersion jsonData

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  let statusFile = fromMaybe defaultFile $ optDrbdStatus opts
      pairingFile = optDrbdPairing opts
  unless (null args) . exitErr $ "This program takes exactly zero" ++
                                  " arguments, got '" ++ unwords args ++ "'"
  report <- buildDRBDReport statusFile pairingFile
  putStrLn $ J.encode report

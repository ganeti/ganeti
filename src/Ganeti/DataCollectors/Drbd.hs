{-| DRBD data collector.

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

module Ganeti.DataCollectors.Drbd
  ( main
  , options
  , arguments
  ) where


import qualified Control.Exception as E
import Data.Attoparsec.Text.Lazy as A
import Data.Text.Lazy (pack, unpack)
import Text.JSON

import qualified Ganeti.BasicTypes as BT
import qualified Ganeti.Constants as C
import Ganeti.Block.Drbd.Parser(drbdStatusParser)
import Ganeti.Common
import Ganeti.DataCollectors.CLI
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

options :: IO [OptType]
options = return []

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = [ArgCompletion OptComplFile 0 (Just 1)]

-- * Command line options

-- | Main function.
main :: Options -> [String] -> IO ()
main _ args = do
  proc_drbd <- case args of
                 [ ] -> return defaultFile
                 [x] -> return x
                 _   -> exitErr $ "This program takes only one argument," ++
                                  " got '" ++ unwords args ++ "'"
  contents <-
    ((E.try $ readFile proc_drbd) :: IO (Either IOError String)) >>=
      exitIfBad "reading from file" . either (BT.Bad . show) BT.Ok
  output <-
    case A.parse (drbdStatusParser []) $ pack contents of
      A.Fail unparsedText contexts errorMessage -> exitErr $
        show (Prelude.take defaultCharNum $ unpack unparsedText) ++ "\n"
          ++ show contexts ++ "\n" ++ errorMessage
      A.Done _ drbdStatus -> return $ encode drbdStatus
  putStrLn output

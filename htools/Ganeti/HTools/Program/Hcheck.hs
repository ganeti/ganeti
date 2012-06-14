{-| Cluster checker.

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

You should have received a copy of the GNU Gene52al Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.HTools.Program.Hcheck (main, options) where

import Control.Monad
import System.Exit
import System.IO

import Ganeti.HTools.CLI

-- | Options list and functions.
options :: [OptType]
options =
  [ oDataFile
  , oDiskMoves
  , oDynuFile
  , oEvacMode
  , oExInst
  , oExTags
  , oIAllocSrc
  , oInstMoves
  , oLuxiSocket
  , oMachineReadable
  , oMaxCpu
  , oMaxSolLength
  , oMinDisk
  , oMinGain
  , oMinGainLim
  , oMinScore
  , oNoSimulation
  , oOfflineNode
  , oQuiet
  , oRapiMaster
  , oSelInst
  , oShowHelp
  , oShowVer
  , oVerbose
  ]

-- | Main function.
main :: Options -> [String] -> IO ()
main _ args = do
  unless (null args) $ do
         hPutStrLn stderr "Error: this program doesn't take any arguments."
         exitWith $ ExitFailure 1

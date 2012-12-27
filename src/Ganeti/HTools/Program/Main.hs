{-| Small module holding program definitions.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.HTools.Program.Main
  ( personalities
  , main
  ) where

import Control.Exception
import Control.Monad (guard)
import Data.Char (toLower)
import System.Environment
import System.IO
import System.IO.Error (isDoesNotExistError)

import Ganeti.Common (formatCommands, PersonalityList)
import Ganeti.HTools.CLI (Options, parseOpts, genericOpts)
import qualified Ganeti.HTools.Program.Hail as Hail
import qualified Ganeti.HTools.Program.Hbal as Hbal
import qualified Ganeti.HTools.Program.Hcheck as Hcheck
import qualified Ganeti.HTools.Program.Hscan as Hscan
import qualified Ganeti.HTools.Program.Hspace as Hspace
import qualified Ganeti.HTools.Program.Hinfo as Hinfo
import qualified Ganeti.HTools.Program.Hroller as Hroller
import Ganeti.Utils

-- | Supported binaries.
personalities :: PersonalityList Options
personalities =
  [ ("hail",    (Hail.main,    Hail.options,    Hail.arguments,
                 "Ganeti IAllocator plugin that implements the instance\
                 \ placement and movement using the same algorithm as\
                 \ hbal(1)"))
  , ("hbal",    (Hbal.main,    Hbal.options,    Hbal.arguments,
                 "cluster balancer that looks at the current state of\
                 \ the cluster and computes a series of steps designed\
                 \ to bring the cluster into a better state"))
  , ("hcheck",  (Hcheck.main,  Hcheck.options,  Hcheck.arguments,
                "cluster checker; prints information about cluster's\
                \ health and checks whether a rebalance done using\
                \ hbal would help"))
  , ("hscan",   (Hscan.main,   Hscan.options,   Hscan.arguments,
                "tool for scanning clusters via RAPI and saving their\
                \ data in the input format used by hbal(1) and hspace(1)"))
  , ("hspace",  (Hspace.main,  Hspace.options,  Hspace.arguments,
                "computes how many additional instances can be fit on a\
                \ cluster, while maintaining N+1 status."))
  , ("hinfo",   (Hinfo.main,   Hinfo.options,   Hinfo.arguments,
                "cluster information printer; it prints information\
                \ about the current cluster state and its residing\
                \ nodes/instances"))
  , ("hroller", (Hroller.main, Hroller.options, Hroller.arguments,
                "cluster rolling maintenance helper; it helps scheduling\
                \ node reboots in a manner that doesn't conflict with the\
                \ instances' topology"))
  ]

-- | Display usage and exit.
usage :: String -> IO ()
usage name = do
  hPutStrLn stderr $ "Unrecognised personality '" ++ name ++ "'."
  hPutStrLn stderr "This program must be installed under one of the following\
                   \ names:"
  hPutStrLn stderr . unlines $ formatCommands personalities
  exitErr "Please either rename/symlink the program or set\n\
          \the environment variable HTOOLS to the desired role."

main :: IO ()
main = do
  binary <- catchJust (guard . isDoesNotExistError)
            (getEnv "HTOOLS") (const getProgName)
  let name = map toLower binary
  case name `lookup` personalities of
    Nothing -> usage name
    Just (fn, options, arguments, _) -> do
         cmd_args <- getArgs
         real_options <- options
         (opts, args) <- parseOpts cmd_args name (real_options ++ genericOpts)
                           arguments
         fn opts args

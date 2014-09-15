{-| Small module holding program definitions.

-}

{-

Copyright (C) 2011, 2012 Google Inc.
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
import qualified Ganeti.HTools.Program.Harep as Harep
import qualified Ganeti.HTools.Program.Hbal as Hbal
import qualified Ganeti.HTools.Program.Hcheck as Hcheck
import qualified Ganeti.HTools.Program.Hscan as Hscan
import qualified Ganeti.HTools.Program.Hspace as Hspace
import qualified Ganeti.HTools.Program.Hsqueeze as Hsqueeze
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
  , ("harep",   (Harep.main,   Harep.options,   Harep.arguments,
                 "auto-repair tool that detects certain kind of problems\
                 \ with instances and applies the allowed set of solutions"))
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
  , ("hsqueeze", (Hsqueeze.main, Hsqueeze.options, Hsqueeze.arguments,
                "cluster dynamic power management;  it powers up and down\
                \ nodes to keep the amount of free online resources in a\
                \ given range"))
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

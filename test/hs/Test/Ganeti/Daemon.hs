{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Test.Ganeti.Daemon (testDaemon) where

import Test.QuickCheck hiding (Result)
import Test.HUnit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Common

import Ganeti.Common
import Ganeti.Daemon as Daemon

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Test a few string arguments.
prop_string_arg :: String -> Property
prop_string_arg argument =
  let args = [ (argument, oBindAddress, optBindAddress)
             ]
  in conjoin $
     map (checkOpt Just defaultOptions failTest (const (==?)) Just) args

-- | Test a few integer arguments (only one for now).
prop_numeric_arg :: Int -> Property
prop_numeric_arg argument =
  checkOpt (Just . show) defaultOptions
    failTest (const (==?)) (Just . fromIntegral)
    (argument, oPort 0, optPort)

-- | Test a few boolean arguments.
case_bool_arg :: Assertion
case_bool_arg =
  mapM_ (checkOpt (const Nothing) defaultOptions assertFailure
                  assertEqual id)
        [ (False, oNoDaemonize,  optDaemonize)
        , (True,  oDebug,        optDebug)
        , (True,  oNoUserChecks, optNoUserChecks)
        ]

-- | Tests a few invalid arguments.
case_wrong_arg :: Assertion
case_wrong_arg =
  mapM_ (passFailOpt defaultOptions assertFailure (return ()))
        [ (oSyslogUsage, "foo", "yes")
        , (oPort 0,      "x",   "10")
        ]

-- | Test that the option list supports some common options.
case_stdopts :: Assertion
case_stdopts =
  checkEarlyExit defaultOptions "prog" [oShowHelp, oShowVer] []

testSuite "Daemon"
          [ 'prop_string_arg
          , 'prop_numeric_arg
          , 'case_bool_arg
          , 'case_wrong_arg
          , 'case_stdopts
          ]

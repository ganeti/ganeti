{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

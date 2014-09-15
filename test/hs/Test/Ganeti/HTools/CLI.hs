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

module Test.Ganeti.HTools.CLI (testHTools_CLI) where

import Test.HUnit
import Test.QuickCheck

import Control.Monad
import Data.List
import Text.Printf (printf)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Common

import Ganeti.BasicTypes
import Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Program.Main as Program
import qualified Ganeti.HTools.Types as Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Test correct parsing.
prop_parseISpec :: String -> Int -> Int -> Int -> Maybe Int -> Property
prop_parseISpec descr dsk mem cpu spn =
  let (str, spn') = case spn of
                      Nothing -> (printf "%d,%d,%d" dsk mem cpu::String, 1)
                      Just spn'' ->
                        (printf "%d,%d,%d,%d" dsk mem cpu spn''::String, spn'')
  in parseISpecString descr str ==? Ok (Types.RSpec cpu mem dsk spn')

-- | Test parsing failure due to wrong section count.
prop_parseISpecFail :: String -> Property
prop_parseISpecFail descr =
  forAll (choose (0,100) `suchThat` (not . flip elem [3, 4])) $ \nelems ->
  forAll (replicateM nelems arbitrary) $ \values ->
  let str = intercalate "," $ map show (values::[Int])
  in case parseISpecString descr str of
       Ok v -> failTest $ "Expected failure, got " ++ show v
       _ -> passTest

-- | Test a few string arguments.
prop_string_arg :: String -> Property
prop_string_arg argument =
  let args = [ (oDataFile,      optDataFile)
             , (oDynuFile,      optDynuFile)
             , (oSaveCluster,   optSaveCluster)
             , (oPrintCommands, optShowCmds)
             , (genOLuxiSocket "", optLuxi)
             , (oIAllocSrc,     optIAllocSrc)
             ]
  in conjoin $ map (\(o, opt) ->
                      checkOpt Just defaultOptions
                      failTest (const (==?)) Just (argument, o, opt)) args

-- | Test a few positive arguments.
prop_numeric_arg :: Positive Double -> Property
prop_numeric_arg (Positive argument) =
  let args = [ (oMaxCpu,     optMcpu)
             , (oMinDisk,    Just . optMdsk)
             , (oMinGain,    Just . optMinGain)
             , (oMinGainLim, Just . optMinGainLim)
             , (oMinScore,   Just . optMinScore)
             ]
  in conjoin $
     map (\(x, y) -> checkOpt (Just . show) defaultOptions
                     failTest (const (==?)) Just (argument, x, y)) args

-- | Test a few boolean arguments.
case_bool_arg :: Assertion
case_bool_arg =
  mapM_ (checkOpt (const Nothing) defaultOptions assertFailure
                  assertEqual id)
        [ (False, oDiskMoves,    optDiskMoves)
        , (False, oInstMoves,    optInstMoves)
        , (True,  oEvacMode,     optEvacMode)
        , (True,  oExecJobs,     optExecJobs)
        , (True,  oNoHeaders,    optNoHeaders)
        , (True,  oNoSimulation, optNoSimulation)
        ]

-- | Tests a few invalid arguments.
case_wrong_arg :: Assertion
case_wrong_arg =
  mapM_ (passFailOpt defaultOptions assertFailure (return ()))
        [ (oSpindleUse,   "-1", "1")
        , (oSpindleUse,   "a",  "1")
        , (oMaxCpu,       "-1", "1")
        , (oMinDisk,      "a",  "1")
        , (oMinGainLim,   "a",  "1")
        , (oMaxSolLength, "x",  "10")
        , (oStdSpec,      "no-such-spec", "1,1,1")
        , (oTieredSpec,   "no-such-spec", "1,1,1")
        ]

-- | Test that all binaries support some common options.
case_stdopts :: Assertion
case_stdopts =
  mapM_ (\(name, (_, o, a, _)) -> do
           o' <- o
           checkEarlyExit defaultOptions name
             (o' ++ genericOpts) a) Program.personalities

testSuite "HTools/CLI"
          [ 'prop_parseISpec
          , 'prop_parseISpecFail
          , 'prop_string_arg
          , 'prop_numeric_arg
          , 'case_bool_arg
          , 'case_wrong_arg
          , 'case_stdopts
          ]

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
import qualified Ganeti.HTools.Program as Program
import qualified Ganeti.HTools.Types as Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Test correct parsing.
prop_parseISpec :: String -> Int -> Int -> Int -> Property
prop_parseISpec descr dsk mem cpu =
  let str = printf "%d,%d,%d" dsk mem cpu::String
  in parseISpecString descr str ==? Ok (Types.RSpec cpu mem dsk)

-- | Test parsing failure due to wrong section count.
prop_parseISpecFail :: String -> Property
prop_parseISpecFail descr =
  forAll (choose (0,100) `suchThat` (/= 3)) $ \nelems ->
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
             , (oLuxiSocket,    optLuxi)
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
  mapM_ (\(name, (_, o, a)) -> do
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

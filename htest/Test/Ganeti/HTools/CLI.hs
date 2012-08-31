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

import Test.QuickCheck

import Control.Monad
import Data.List
import Text.Printf (printf)
import qualified System.Console.GetOpt as GetOpt

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Program as Program
import qualified Ganeti.HTools.Types as Types

-- | Test correct parsing.
prop_parseISpec :: String -> Int -> Int -> Int -> Property
prop_parseISpec descr dsk mem cpu =
  let str = printf "%d,%d,%d" dsk mem cpu::String
  in CLI.parseISpecString descr str ==? Types.Ok (Types.RSpec cpu mem dsk)

-- | Test parsing failure due to wrong section count.
prop_parseISpecFail :: String -> Property
prop_parseISpecFail descr =
  forAll (choose (0,100) `suchThat` ((/=) 3)) $ \nelems ->
  forAll (replicateM nelems arbitrary) $ \values ->
  let str = intercalate "," $ map show (values::[Int])
  in case CLI.parseISpecString descr str of
       Types.Ok v -> failTest $ "Expected failure, got " ++ show v
       _ -> passTest

-- | Test parseYesNo.
prop_parseYesNo :: Bool -> Bool -> [Char] -> Property
prop_parseYesNo def testval val =
  forAll (elements [val, "yes", "no"]) $ \actual_val ->
  if testval
    then CLI.parseYesNo def Nothing ==? Types.Ok def
    else let result = CLI.parseYesNo def (Just actual_val)
         in if actual_val `elem` ["yes", "no"]
              then result ==? Types.Ok (actual_val == "yes")
              else property $ Types.isBad result

-- | Helper to check for correct parsing of string arg.
checkStringArg :: [Char]
               -> (GetOpt.OptDescr (CLI.Options -> Types.Result CLI.Options),
                   CLI.Options -> Maybe [Char])
               -> Property
checkStringArg val (opt, fn) =
  let GetOpt.Option _ longs _ _ = opt
  in case longs of
       [] -> failTest "no long options?"
       cmdarg:_ ->
         case CLI.parseOptsInner ["--" ++ cmdarg ++ "=" ++ val] "prog" [opt] of
           Left e -> failTest $ "Failed to parse option: " ++ show e
           Right (options, _) -> fn options ==? Just val

-- | Test a few string arguments.
prop_StringArg :: [Char] -> Property
prop_StringArg argument =
  let args = [ (CLI.oDataFile,      CLI.optDataFile)
             , (CLI.oDynuFile,      CLI.optDynuFile)
             , (CLI.oSaveCluster,   CLI.optSaveCluster)
             , (CLI.oReplay,        CLI.optReplay)
             , (CLI.oPrintCommands, CLI.optShowCmds)
             , (CLI.oLuxiSocket,    CLI.optLuxi)
             ]
  in conjoin $ map (checkStringArg argument) args

-- | Helper to test that a given option is accepted OK with quick exit.
checkEarlyExit :: String -> [CLI.OptType] -> String -> Property
checkEarlyExit name options param =
  case CLI.parseOptsInner [param] name options of
    Left (code, _) ->
      printTestCase ("Program " ++ name ++
                     " returns invalid code " ++ show code ++
                     " for option " ++ param) (code == 0)
    _ -> failTest $ "Program " ++ name ++ " doesn't consider option " ++
         param ++ " as early exit one"

-- | Test that all binaries support some common options. There is
-- nothing actually random about this test...
prop_stdopts :: Property
prop_stdopts =
  let params = ["-h", "--help", "-V", "--version"]
      opts = map (\(name, (_, o)) -> (name, o)) Program.personalities
      -- apply checkEarlyExit across the cartesian product of params and opts
  in conjoin [checkEarlyExit n o p | p <- params, (n, o) <- opts]

testSuite "HTools/CLI"
          [ 'prop_parseISpec
          , 'prop_parseISpecFail
          , 'prop_parseYesNo
          , 'prop_StringArg
          , 'prop_stdopts
          ]

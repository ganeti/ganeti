{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for the 'Ganeti.Common' module.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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

module Test.Ganeti.Common
  ( testCommon
  , checkOpt
  , passFailOpt
  , checkEarlyExit
  ) where

import Test.QuickCheck hiding (Result)
import Test.HUnit

import qualified System.Console.GetOpt as GetOpt
import System.Exit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.HTools.Program.Main (personalities)

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Helper to check for correct parsing of an option.
checkOpt :: (StandardOptions b) =>
            (a -> Maybe String) -- ^ Converts the value into a cmdline form
         -> b                   -- ^ The default options
         -> (String -> c)       -- ^ Fail test function
         -> (String -> d -> d -> c) -- ^ Check for equality function
         -> (a -> d)            -- ^ Transforms the value to a compare val
         -> (a, GenericOptType b, b -> d) -- ^ Triple of value, the
                                          -- option, function to
                                          -- extract the set value
                                          -- from the options
         -> c
checkOpt repr defaults failfn eqcheck valfn
         (val, opt@(GetOpt.Option _ longs _ _, _), fn) =
  case longs of
    [] -> failfn "no long options?"
    cmdarg:_ ->
      case parseOptsInner defaults
             ["--" ++ cmdarg ++ maybe "" ("=" ++) (repr val)]
             "prog" [opt] [] of
        Left e -> failfn $ "Failed to parse option '" ++ cmdarg ++ ": " ++
                  show e
        Right (options, _) -> eqcheck ("Wrong value in option " ++
                                       cmdarg ++ "?") (valfn val) (fn options)

-- | Helper to check for correct and incorrect parsing of an option.
passFailOpt :: (StandardOptions b) =>
               b                 -- ^ The default options
            -> (String -> c)     -- ^ Fail test function
            -> c                 -- ^ Pass function
            -> (GenericOptType b, String, String)
            -- ^ The list of enabled options, fail value and pass value
            -> c
passFailOpt defaults failfn passfn
              (opt@(GetOpt.Option _ longs _ _, _), bad, good) =
  let first_opt = case longs of
                    [] -> error "no long options?"
                    x:_ -> x
      prefix = "--" ++ first_opt ++ "="
      good_cmd = prefix ++ good
      bad_cmd = prefix ++ bad in
  case (parseOptsInner defaults [bad_cmd]  "prog" [opt] [],
        parseOptsInner defaults [good_cmd] "prog" [opt] []) of
    (Left _,  Right _) -> passfn
    (Right _, Right _) -> failfn $ "Command line '" ++ bad_cmd ++
                          "' succeeded when it shouldn't"
    (Left  _, Left  _) -> failfn $ "Command line '" ++ good_cmd ++
                          "' failed when it shouldn't"
    (Right _, Left  _) ->
      failfn $ "Command line '" ++ bad_cmd ++
               "' succeeded when it shouldn't, while command line '" ++
               good_cmd ++ "' failed when it shouldn't"

-- | Helper to test that a given option is accepted OK with quick exit.
checkEarlyExit :: (StandardOptions a) =>
                  a -> String -> [GenericOptType a] -> [ArgCompletion]
               -> Assertion
checkEarlyExit defaults name options arguments =
  mapM_ (\param ->
           case parseOptsInner defaults [param] name options arguments of
             Left (code, _) ->
               assertEqual ("Program " ++ name ++
                            " returns invalid code " ++ show code ++
                            " for option " ++ param) ExitSuccess code
             _ -> assertFailure $ "Program " ++ name ++
                  " doesn't consider option " ++
                  param ++ " as early exit one"
        ) ["-h", "--help", "-V", "--version"]

-- | Test parseYesNo.
prop_parse_yes_no :: Bool -> Bool -> String -> Property
prop_parse_yes_no def testval val =
  forAll (elements [val, "yes", "no"]) $ \actual_val ->
  if testval
    then parseYesNo def Nothing ==? Ok def
    else let result = parseYesNo def (Just actual_val)
         in if actual_val `elem` ["yes", "no"]
              then result ==? Ok (actual_val == "yes")
              else property $ isBad result

-- | Check that formatCmdUsage works similar to Python _FormatUsage.
case_formatCommands :: Assertion
case_formatCommands =
  assertEqual "proper wrap for HTools Main"
    resCmdTest (formatCommands personalities)
  where resCmdTest :: [String]
        resCmdTest =
          [ " hail     - Ganeti IAllocator plugin that implements the instance\
            \ placement and"
          , "            movement using the same algorithm as hbal(1)"
          , " harep    - auto-repair tool that detects certain kind of problems\
            \ with"
          , "            instances and applies the allowed set of solutions"
          , " hbal     - cluster balancer that looks at the current state of\
            \ the cluster and"
          , "            computes a series of steps designed to bring the\
            \ cluster into a"
          , "            better state"
          , " hcheck   - cluster checker; prints information about cluster's\
            \ health and"
          , "            checks whether a rebalance done using hbal would help"
          , " hinfo    - cluster information printer; it prints information\
            \ about the current"
          , "            cluster state and its residing nodes/instances"
          , " hroller  - cluster rolling maintenance helper; it helps\
            \ scheduling node reboots"
          , "            in a manner that doesn't conflict with the instances'\
            \ topology"
          , " hscan    - tool for scanning clusters via RAPI and saving their\
            \ data in the"
          , "            input format used by hbal(1) and hspace(1)"
          , " hspace   - computes how many additional instances can be fit on a\
            \ cluster,"
          , "            while maintaining N+1 status."
          , " hsqueeze - cluster dynamic power management;  it powers up and\
            \ down nodes to"
          , "            keep the amount of free online resources in a given\
            \ range"
          ]

testSuite "Common"
          [ 'prop_parse_yes_no
          , 'case_formatCommands
          ]

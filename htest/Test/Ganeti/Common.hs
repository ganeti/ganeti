{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for the 'Ganeti.Common' module.

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
         (val, opt@(GetOpt.Option _ longs _ _), fn) =
  case longs of
    [] -> failfn "no long options?"
    cmdarg:_ ->
      case parseOptsInner defaults
             ["--" ++ cmdarg ++ maybe "" ("=" ++) (repr val)]
             "prog" [opt] of
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
              (opt@(GetOpt.Option _ longs _ _), bad, good) =
  let prefix = "--" ++ head longs ++ "="
      good_cmd = prefix ++ good
      bad_cmd = prefix ++ bad in
  case (parseOptsInner defaults [bad_cmd]  "prog" [opt],
        parseOptsInner defaults [good_cmd] "prog" [opt]) of
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
                  a -> String -> [GenericOptType a] -> Assertion
checkEarlyExit defaults name options =
  mapM_ (\param ->
           case parseOptsInner defaults [param] name options of
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


testSuite "Common"
          [ 'prop_parse_yes_no
          ]

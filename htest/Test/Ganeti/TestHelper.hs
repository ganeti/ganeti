{-# LANGUAGE TemplateHaskell #-}

{-| Unittest helpers for Haskell components

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

module Test.Ganeti.TestHelper
  ( testSuite
  ) where

import Data.List (stripPrefix, isPrefixOf)
import Data.Maybe (fromMaybe)
import Test.Framework
import Test.Framework.Providers.HUnit
import Test.Framework.Providers.QuickCheck2
import Test.HUnit (Assertion)
import Test.QuickCheck
import Language.Haskell.TH

-- | Tries to drop a prefix from a string.
simplifyName :: String -> String -> String
simplifyName pfx string = fromMaybe string (stripPrefix pfx string)

-- | Builds a test from a QuickCheck property.
runQC :: Testable prop => String -> String -> prop -> Test
runQC pfx name = testProperty (simplifyName ("prop_" ++ pfx ++ "_") name)

-- | Builds a test for a HUnit test case.
runHUnit :: String -> String -> Assertion -> Test
runHUnit pfx name = testCase (simplifyName ("case_" ++ pfx ++ "_") name)

-- | Runs the correct test provider for a given test, based on its
-- name (not very nice, but...).
run :: String -> Name -> Q Exp
run tsname name =
  let str = nameBase name
      nameE = varE name
      strE = litE (StringL str)
  in case () of
       _ | "prop_" `isPrefixOf` str -> [| runQC tsname $strE $nameE |]
         | "case_" `isPrefixOf` str -> [| runHUnit tsname $strE $nameE |]
         | otherwise -> fail $ "Unsupported test function name '" ++ str ++ "'"

-- | Builds a test suite.
testSuite :: String -> [Name] -> Q [Dec]
testSuite tsname tdef = do
  let fullname = mkName $ "test" ++ tsname
  tests <- mapM (run tsname) tdef
  sigtype <- [t| (String, [Test]) |]
  return [ SigD fullname sigtype
         , ValD (VarP fullname) (NormalB (TupE [LitE (StringL tsname),
                                                ListE tests])) []
         ]

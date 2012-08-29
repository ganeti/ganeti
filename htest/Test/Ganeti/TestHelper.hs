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

-- | Test property prefix.
propPrefix :: String
propPrefix = "prop_"

-- | Test case prefix.
casePrefix :: String
casePrefix = "case_"

-- | Tries to drop a prefix from a string.
simplifyName :: String -> String -> String
simplifyName pfx string = fromMaybe string (stripPrefix pfx string)

-- | Builds a test from a QuickCheck property.
runProp :: Testable prop => String -> prop -> Test
runProp = testProperty . simplifyName propPrefix

-- | Builds a test for a HUnit test case.
runCase :: String -> Assertion -> Test
runCase = testCase . simplifyName casePrefix

-- | Runs the correct test provider for a given test, based on its
-- name (not very nice, but...).
run :: Name -> Q Exp
run name =
  let str = nameBase name
      nameE = varE name
      strE = litE (StringL str)
  in case () of
       _ | propPrefix `isPrefixOf` str -> [| runProp $strE $nameE |]
         | casePrefix `isPrefixOf` str -> [| runCase $strE $nameE |]
         | otherwise -> fail $ "Unsupported test function name '" ++ str ++ "'"

-- | Convert slashes in a name to underscores.
mapSlashes :: String -> String
mapSlashes = map (\c -> if c == '/' then '_' else c)

-- | Builds a test suite.
testSuite :: String -> [Name] -> Q [Dec]
testSuite tsname tdef = do
  let fullname = mkName $ "test" ++ mapSlashes tsname
  tests <- mapM run tdef
  sigtype <- [t| (String, [Test]) |]
  return [ SigD fullname sigtype
         , ValD (VarP fullname) (NormalB (TupE [LitE (StringL tsname),
                                                ListE tests])) []
         ]

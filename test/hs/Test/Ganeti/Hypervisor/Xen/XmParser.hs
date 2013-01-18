{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for @xm list --long@ parser -}

{-

Copyright (C) 2013 Google Inc.

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

module Test.Ganeti.Hypervisor.Xen.XmParser
  ( testHypervisor_Xen_XmParser
  ) where

import Test.HUnit
import Test.QuickCheck as QuickCheck hiding (Result)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Control.Monad (liftM)
import qualified Data.Attoparsec.Text as A
import Data.Text (pack)
import Data.Char
import qualified Data.Map as Map

import Ganeti.Hypervisor.Xen.Types
import Ganeti.Hypervisor.Xen.XmParser

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitraries

-- | Arbitrary instance for generating configurations.
-- A completely arbitrary configuration would contain too many lists and its
-- size would be to big to be actually parsable in reasonable time.
-- This Arbitrary builds a random Config that is still of a reasonable size.
-- Avoid generating strings that might be interpreted as numbers.
instance Arbitrary LispConfig where
  arbitrary = frequency
    [ (5, liftM LCString (genName `suchThat` (not . canBeNumber)))
    , (5, liftM LCDouble arbitrary)
    , (1, liftM LCList (choose(1,20) >>= (`vectorOf` arbitrary)))
    ]

-- | Determines conservatively whether a string could be a number.
canBeNumber :: String -> Bool
canBeNumber [] = False
canBeNumber (c:[]) = canBeNumberChar c
canBeNumber (c:xs) = canBeNumberChar c && canBeNumber xs

-- | Determines whether a char can be part of the string representation of a
-- number (even in scientific notation).
canBeNumberChar :: Char -> Bool
canBeNumberChar c = isDigit c || (c `elem` "eE-")

-- * Helper functions for tests

-- | Function for testing whether a domain configuration is parsed correctly.
testDomain :: String -> Map.Map String Domain -> Assertion
testDomain fileName expectedContent = do
    fileContent <- readTestData fileName
    case A.parseOnly xmListParser $ pack fileContent of
        Left msg -> assertFailure $ "Parsing failed: " ++ msg
        Right obtained -> assertEqual fileName expectedContent obtained

-- | Determines whether two LispConfig are equal, with the exception of Double
-- values, that just need to be "almost equal".
-- Meant mainly for testing purposes, given that Double values may be slightly
-- rounded during parsing.
isAlmostEqual :: LispConfig -> LispConfig -> Bool
isAlmostEqual (LCList c1) (LCList c2) =
  (length c1 == length c2) &&
  foldr
    (\current acc -> (acc && uncurry isAlmostEqual current))
    True
    (zip c1 c2)
isAlmostEqual (LCString s1) (LCString s2) = s1 == s2
isAlmostEqual (LCDouble d1) (LCDouble d2) = abs (d1-d2) <= 1e-12
isAlmostEqual _ _ = False

-- | Function to serialize LispConfigs in such a way that they can be rebuilt
-- again by the lispConfigParser.
serializeConf :: LispConfig -> String
serializeConf (LCList c) = "(" ++ unwords (map serializeConf c) ++ ")"
serializeConf (LCString s) = s
serializeConf (LCDouble d) = show d

-- | Test whether a randomly generated config can be parsed.
-- Implicitly, this also tests that the Show instance of Config is correct.
prop_config :: LispConfig -> Property
prop_config conf =
  case A.parseOnly lispConfigParser . pack . serializeConf $ conf of
        Left msg -> fail $ "Parsing failed: " ++ msg
        Right obtained -> property $ isAlmostEqual obtained conf

-- | Test a Xen 4.0.1 @xm list --long@ output.
case_xen401list :: Assertion
case_xen401list = testDomain "xen-xm-list-long-4.0.1.txt" $
  Map.fromList
    [ ("Domain-0", Domain 0 "Domain-0" 184000.41332 ActualRunning Nothing)
    , ("instance1.example.com", Domain 119 "instance1.example.com" 24.116146647
      ActualBlocked Nothing)
    ]

testSuite "Hypervisor/Xen/XmParser"
          [ 'prop_config
          , 'case_xen401list
          ]

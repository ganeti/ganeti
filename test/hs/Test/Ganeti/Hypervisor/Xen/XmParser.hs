{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for @xm list --long@ parser -}

{-

Copyright (C) 2013 Google Inc.
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
import Text.Printf

import Ganeti.Hypervisor.Xen.Types
import Ganeti.Hypervisor.Xen.XmParser

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Arbitraries

-- | Generator for 'ListConfig'.
--
-- A completely arbitrary configuration would contain too many lists
-- and its size would be to big to be actually parsable in reasonable
-- time. This generator builds a random Config that is still of a
-- reasonable size, and it also Avoids generating strings that might
-- be interpreted as numbers.
genConfig :: Int -> Gen LispConfig
genConfig 0 =
  -- only terminal values for size 0
  frequency [ (5, liftM LCString (genName `suchThat` (not . canBeNumber)))
            , (5, liftM LCDouble arbitrary)
            ]
genConfig n =
  -- for size greater than 0, allow "some" lists
  frequency [ (5, liftM LCString (resize n genName `suchThat`
                                  (not . canBeNumber)))
            , (5, liftM LCDouble arbitrary)
            , (1, liftM LCList (choose (1, n) >>=
                                (\n' -> vectorOf n' (genConfig $ n `div` n'))))
            ]

-- | Arbitrary instance for 'LispConfig' using 'genConfig'.
instance Arbitrary LispConfig where
  arbitrary = sized genConfig

-- | Determines conservatively whether a string could be a number.
canBeNumber :: String -> Bool
canBeNumber [] = False
canBeNumber [c] = canBeNumberChar c
canBeNumber (c:xs) = canBeNumberChar c && canBeNumber xs

-- | Determines whether a char can be part of the string representation of a
-- number (even in scientific notation).
canBeNumberChar :: Char -> Bool
canBeNumberChar c = isDigit c || (c `elem` "eE-")

-- | Generates an arbitrary @xm uptime@ output line.
instance Arbitrary UptimeInfo where
  arbitrary = do
    name <- genFQDN
    NonNegative idNum <- arbitrary :: Gen (NonNegative Int)
    NonNegative days <- arbitrary :: Gen (NonNegative Int)
    hours <- choose (0, 23) :: Gen Int
    mins <- choose (0, 59) :: Gen Int
    secs <- choose (0, 59) :: Gen Int
    let uptime :: String
        uptime =
          if days /= 0
            then printf "%d days, %d:%d:%d" days hours mins secs
            else printf "%d:%d:%d" hours mins secs
    return $ UptimeInfo name idNum uptime

-- * Helper functions for tests

-- | Function for testing whether a domain configuration is parsed correctly.
testDomain :: String -> Map.Map String Domain -> Assertion
testDomain fileName expectedContent = do
  fileContent <- readTestData fileName
  case A.parseOnly xmListParser $ pack fileContent of
    Left msg -> assertFailure $ "Parsing failed: " ++ msg
    Right obtained -> assertEqual fileName expectedContent obtained

-- | Function for testing whether a @xm uptime@ output (stored in a file)
-- is parsed correctly.
testUptimeInfo :: String -> Map.Map Int UptimeInfo -> Assertion
testUptimeInfo fileName expectedContent = do
  fileContent <- readTestData fileName
  case A.parseOnly xmUptimeParser $ pack fileContent of
    Left msg -> assertFailure $ "Parsing failed: " ++ msg
    Right obtained -> assertEqual fileName expectedContent obtained

-- | Determines whether two LispConfig are equal, with the exception of Double
-- values, that just need to be \"almost equal\".
--
-- Meant mainly for testing purposes, given that Double values may be slightly
-- rounded during parsing.
isAlmostEqual :: LispConfig -> LispConfig -> Property
isAlmostEqual (LCList c1) (LCList c2) =
  (length c1 ==? length c2) .&&.
  conjoin (zipWith isAlmostEqual c1 c2)
isAlmostEqual (LCString s1) (LCString s2) = s1 ==? s2
isAlmostEqual (LCDouble d1) (LCDouble d2) = printTestCase msg $ rel <= 1e-12
    where rel = relativeError d1 d2
          msg = "Relative error " ++ show rel ++ " not smaller than 1e-12\n" ++
                "expected: " ++ show d2 ++ "\n but got: " ++ show d1
isAlmostEqual a b =
  failTest $ "Comparing different types: '" ++ show a ++ "' with '" ++
             show b ++ "'"

-- | Function to serialize LispConfigs in such a way that they can be rebuilt
-- again by the lispConfigParser.
serializeConf :: LispConfig -> String
serializeConf (LCList c) = "(" ++ unwords (map serializeConf c) ++ ")"
serializeConf (LCString s) = s
serializeConf (LCDouble d) = show d

-- | Function to serialize UptimeInfos in such a way that they can be rebuilt
-- againg by the uptimeLineParser.
serializeUptime :: UptimeInfo -> String
serializeUptime (UptimeInfo name idNum uptime) =
  printf "%s\t%d\t%s" name idNum uptime

-- | Test whether a randomly generated config can be parsed.
-- Implicitly, this also tests that the Show instance of Config is correct.
prop_config :: LispConfig -> Property
prop_config conf =
  case A.parseOnly lispConfigParser . pack . serializeConf $ conf of
        Left msg -> failTest $ "Parsing failed: " ++ msg
        Right obtained -> printTestCase "Failing almost equal check" $
                          isAlmostEqual obtained conf

-- | Test whether a randomly generated UptimeInfo text line can be parsed.
prop_uptimeInfo :: UptimeInfo -> Property
prop_uptimeInfo uInfo =
  case A.parseOnly uptimeLineParser . pack . serializeUptime $ uInfo of
    Left msg -> failTest $ "Parsing failed: " ++ msg
    Right obtained -> obtained ==? uInfo

-- | Test a Xen 4.0.1 @xm list --long@ output.
case_xen401list :: Assertion
case_xen401list = testDomain "xen-xm-list-long-4.0.1.txt" $
  Map.fromList
    [ ("Domain-0", Domain 0 "Domain-0" 184000.41332 ActualRunning Nothing)
    , ("instance1.example.com", Domain 119 "instance1.example.com" 24.116146647
      ActualBlocked Nothing)
    ]

-- | Test a Xen 4.0.1 @xm uptime@ output.
case_xen401uptime :: Assertion
case_xen401uptime = testUptimeInfo "xen-xm-uptime-4.0.1.txt" $
  Map.fromList
    [ (0, UptimeInfo "Domain-0" 0 "98 days,  2:27:44")
    , (119, UptimeInfo "instance1.example.com" 119 "15 days, 20:57:07")
    ]

testSuite "Hypervisor/Xen/XmParser"
          [ 'prop_config
          , 'prop_uptimeInfo
          , 'case_xen401list
          , 'case_xen401uptime
          ]

{-| Unittest helpers for ganeti-htools.

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

module Test.Ganeti.TestCommon where

import Control.Applicative
import Control.Exception (catchJust)
import Control.Monad
import Data.List
import qualified Test.HUnit as HUnit
import Test.QuickCheck
import Test.QuickCheck.Monadic
import qualified Text.JSON as J
import System.Environment (getEnv)
import System.Exit (ExitCode(..))
import System.IO.Error (isDoesNotExistError)
import System.Process (readProcessWithExitCode)

import qualified Ganeti.BasicTypes as BasicTypes

-- * Constants

-- | Maximum memory (1TiB, somewhat random value).
maxMem :: Int
maxMem = 1024 * 1024

-- | Maximum disk (8TiB, somewhat random value).
maxDsk :: Int
maxDsk = 1024 * 1024 * 8

-- | Max CPUs (1024, somewhat random value).
maxCpu :: Int
maxCpu = 1024

-- | Max vcpu ratio (random value).
maxVcpuRatio :: Double
maxVcpuRatio = 1024.0

-- | Max spindle ratio (random value).
maxSpindleRatio :: Double
maxSpindleRatio = 1024.0

-- | Max nodes, used just to limit arbitrary instances for smaller
-- opcode definitions (e.g. list of nodes in OpTestDelay).
maxNodes :: Int
maxNodes = 32

-- | Max opcodes or jobs in a submit job and submit many jobs.
maxOpCodes :: Int
maxOpCodes = 16

-- * Helper functions

-- | Checks for equality with proper annotation.
(==?) :: (Show a, Eq a) => a -> a -> Property
(==?) x y = printTestCase
            ("Expected equality, but '" ++
             show x ++ "' /= '" ++ show y ++ "'") (x == y)
infix 3 ==?

-- | Show a message and fail the test.
failTest :: String -> Property
failTest msg = printTestCase msg False

-- | A 'True' property.
passTest :: Property
passTest = property True

-- | Return the python binary to use. If the PYTHON environment
-- variable is defined, use its value, otherwise use just \"python\".
pythonCmd :: IO String
pythonCmd = catchJust (guard . isDoesNotExistError)
            (getEnv "PYTHON") (const (return "python"))

-- | Run Python with an expression, returning the exit code, standard
-- output and error.
runPython :: String -> String -> IO (ExitCode, String, String)
runPython expr stdin = do
  py_binary <- pythonCmd
  readProcessWithExitCode py_binary ["-c", expr] stdin

-- | Check python exit code, and fail via HUnit assertions if
-- non-zero. Otherwise, return the standard output.
checkPythonResult :: (ExitCode, String, String) -> IO String
checkPythonResult (py_code, py_stdout, py_stderr) = do
  HUnit.assertEqual ("python exited with error: " ++ py_stderr)
       ExitSuccess py_code
  return py_stdout

-- * Arbitrary instances

-- | Defines a DNS name.
newtype DNSChar = DNSChar { dnsGetChar::Char }

instance Arbitrary DNSChar where
  arbitrary = do
    x <- elements (['a'..'z'] ++ ['0'..'9'] ++ "_-")
    return (DNSChar x)

instance Show DNSChar where
  show = show . dnsGetChar

-- | Generates a single name component.
getName :: Gen String
getName = do
  n <- choose (1, 64)
  dn <- vector n
  return (map dnsGetChar dn)

-- | Generates an entire FQDN.
getFQDN :: Gen String
getFQDN = do
  ncomps <- choose (1, 4)
  names <- vectorOf ncomps getName
  return $ intercalate "." names

-- | Combinator that generates a 'Maybe' using a sub-combinator.
getMaybe :: Gen a -> Gen (Maybe a)
getMaybe subgen = do
  bool <- arbitrary
  if bool
    then Just <$> subgen
    else return Nothing

-- | Defines a tag type.
newtype TagChar = TagChar { tagGetChar :: Char }

-- | All valid tag chars. This doesn't need to match _exactly_
-- Ganeti's own tag regex, just enough for it to be close.
tagChar :: [Char]
tagChar = ['a'..'z'] ++ ['A'..'Z'] ++ ['0'..'9'] ++ ".+*/:@-"

instance Arbitrary TagChar where
  arbitrary = do
    c <- elements tagChar
    return (TagChar c)

-- | Generates a tag
genTag :: Gen [TagChar]
genTag = do
  -- the correct value would be C.maxTagLen, but that's way too
  -- verbose in unittests, and at the moment I don't see any possible
  -- bugs with longer tags and the way we use tags in htools
  n <- choose (1, 10)
  vector n

-- | Generates a list of tags (correctly upper bounded).
genTags :: Gen [String]
genTags = do
  -- the correct value would be C.maxTagsPerObj, but per the comment
  -- in genTag, we don't use tags enough in htools to warrant testing
  -- such big values
  n <- choose (0, 10::Int)
  tags <- mapM (const genTag) [1..n]
  return $ map (map tagGetChar) tags

-- | Generates a fields list. This uses the same character set as a
-- DNS name (just for simplicity).
getFields :: Gen [String]
getFields = do
  n <- choose (1, 32)
  vectorOf n getName

-- | Generates a list of a given size with non-duplicate elements.
genUniquesList :: (Eq a, Arbitrary a) => Int -> Gen [a]
genUniquesList cnt =
  foldM (\lst _ -> do
           newelem <- arbitrary `suchThat` (`notElem` lst)
           return (newelem:lst)) [] [1..cnt]

newtype SmallRatio = SmallRatio Double deriving Show
instance Arbitrary SmallRatio where
  arbitrary = do
    v <- choose (0, 1)
    return $ SmallRatio v

-- | Checks for serialisation idempotence.
testSerialisation :: (Eq a, Show a, J.JSON a) => a -> Property
testSerialisation a =
  case J.readJSON (J.showJSON a) of
    J.Error msg -> failTest $ "Failed to deserialise: " ++ msg
    J.Ok a' -> a ==? a'

-- | Result to PropertyM IO.
resultProp :: BasicTypes.Result a -> PropertyM IO a
resultProp (BasicTypes.Bad msg) = stop $ failTest msg
resultProp (BasicTypes.Ok  val) = return val

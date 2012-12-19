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
import qualified Data.Set as Set
import System.Environment (getEnv)
import System.Exit (ExitCode(..))
import System.IO.Error (isDoesNotExistError)
import System.Process (readProcessWithExitCode)
import qualified Test.HUnit as HUnit
import Test.QuickCheck
import Test.QuickCheck.Monadic
import qualified Text.JSON as J
import Numeric

import qualified Ganeti.BasicTypes as BasicTypes
import Ganeti.Types

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

-- | Checks for equality with proper annotation. The first argument is
-- the computed value, the second one the expected value.
(==?) :: (Show a, Eq a) => a -> a -> Property
(==?) x y = printTestCase
            ("Expected equality, but got mismatch\nexpected: " ++
             show y ++ "\n but got: " ++ show x) (x == y)
infix 3 ==?

-- | Checks for inequality with proper annotation. The first argument
-- is the computed value, the second one the expected (not equal)
-- value.
(/=?) :: (Show a, Eq a) => a -> a -> Property
(/=?) x y = printTestCase
            ("Expected inequality, but got equality: '" ++
             show x ++ "'.") (x /= y)
infix 3 /=?

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
  arbitrary = liftM DNSChar $ elements (['a'..'z'] ++ ['0'..'9'] ++ "_-")

instance Show DNSChar where
  show = show . dnsGetChar

-- | Generates a single name component.
genName :: Gen String
genName = do
  n <- choose (1, 16)
  dn <- vector n
  return (map dnsGetChar dn)

-- | Generates an entire FQDN.
genFQDN :: Gen String
genFQDN = do
  ncomps <- choose (1, 4)
  names <- vectorOf ncomps genName
  return $ intercalate "." names

-- | Combinator that generates a 'Maybe' using a sub-combinator.
genMaybe :: Gen a -> Gen (Maybe a)
genMaybe subgen = frequency [ (1, pure Nothing), (3, Just <$> subgen) ]

-- | Defines a tag type.
newtype TagChar = TagChar { tagGetChar :: Char }

-- | All valid tag chars. This doesn't need to match _exactly_
-- Ganeti's own tag regex, just enough for it to be close.
tagChar :: String
tagChar = ['a'..'z'] ++ ['A'..'Z'] ++ ['0'..'9'] ++ ".+*/:@-"

instance Arbitrary TagChar where
  arbitrary = liftM TagChar $ elements tagChar

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
genFields :: Gen [String]
genFields = do
  n <- choose (1, 32)
  vectorOf n genName

-- | Generates a list of a given size with non-duplicate elements.
genUniquesList :: (Eq a, Arbitrary a, Ord a) => Int -> Gen a -> Gen [a]
genUniquesList cnt generator = do
  set <- foldM (\set _ -> do
                  newelem <- generator `suchThat` (`Set.notMember` set)
                  return (Set.insert newelem set)) Set.empty [1..cnt]
  return $ Set.toList set

newtype SmallRatio = SmallRatio Double deriving Show
instance Arbitrary SmallRatio where
  arbitrary = liftM SmallRatio $ choose (0, 1)

-- | Helper for 'genSet', declared separately due to type constraints.
genSetHelper :: (Ord a) => [a] -> Maybe Int -> Gen (Set.Set a)
genSetHelper candidates size = do
  size' <- case size of
             Nothing -> choose (0, length candidates)
             Just s | s > length candidates ->
                        error $ "Invalid size " ++ show s ++ ", maximum is " ++
                                show (length candidates)
                    | otherwise -> return s
  foldM (\set _ -> do
           newelem <- elements candidates `suchThat` (`Set.notMember` set)
           return (Set.insert newelem set)) Set.empty [1..size']

-- | Generates a set of arbitrary elements.
genSet :: (Ord a, Bounded a, Enum a) => Maybe Int -> Gen (Set.Set a)
genSet = genSetHelper [minBound..maxBound]

-- | Generate an arbitrary IPv4 address in textual form (non empty).
genIp4Addr :: Gen NonEmptyString
genIp4Addr = genIp4AddrStr >>= mkNonEmpty

-- | Generate an arbitrary IPv4 address in textual form.
genIp4AddrStr :: Gen String
genIp4AddrStr = do
  a <- choose (1::Int, 255)
  b <- choose (0::Int, 255)
  c <- choose (0::Int, 255)
  d <- choose (0::Int, 255)
  return $ intercalate "." (map show [a, b, c, d])

-- | Generates an arbitrary IPv4 address with a given netmask in textual form.
genIp4NetWithNetmask :: Int -> Gen NonEmptyString
genIp4NetWithNetmask netmask = do
  ip <- genIp4AddrStr
  mkNonEmpty $ ip ++ "/" ++ show netmask

-- | Generate an arbitrary IPv4 network in textual form.
genIp4Net :: Gen NonEmptyString
genIp4Net = do
  netmask <- choose (8::Int, 30)
  genIp4NetWithNetmask netmask

-- | Helper function to compute the number of hosts in a network
-- given the netmask. (For IPv4 only.)
netmask2NumHosts :: Int -> Int
netmask2NumHosts n = 2^(32-n)

-- | Generates an arbitrary IPv6 network address in textual form.
-- The generated address is not simpflified, e. g. an address like
-- "2607:f0d0:1002:0051:0000:0000:0000:0004" does not become
-- "2607:f0d0:1002:51::4"
genIp6Addr :: Gen String
genIp6Addr = do
  rawIp <- vectorOf 8 $ choose (0::Integer, 65535)
  return $ intercalate ":" (map (`showHex` "") rawIp)

-- | Generates an arbitrary IPv6 network in textual form.
genIp6Net :: Gen String
genIp6Net = do
  netmask <- choose (8::Int, 126)
  ip <- genIp6Addr
  return $ ip ++ "/" ++ show netmask

-- * Helper functions

-- | Checks for serialisation idempotence.
testSerialisation :: (Eq a, Show a, J.JSON a) => a -> Property
testSerialisation a =
  case J.readJSON (J.showJSON a) of
    J.Error msg -> failTest $ "Failed to deserialise: " ++ msg
    J.Ok a' -> a ==? a'

-- | Result to PropertyM IO.
resultProp :: (Show a) => BasicTypes.GenericResult a b -> PropertyM IO b
resultProp (BasicTypes.Bad err) = stop . failTest $ show err
resultProp (BasicTypes.Ok  val) = return val

-- | Return the source directory of Ganeti.
getSourceDir :: IO FilePath
getSourceDir = catchJust (guard . isDoesNotExistError)
            (getEnv "TOP_SRCDIR")
            (const (return "."))

-- | Returns the path of a file in the test data directory, given its name.
testDataFilename :: String -> String -> IO FilePath
testDataFilename datadir name = do
        src <- getSourceDir
        return $ src ++ datadir ++ name

-- | Returns the content of the specified python test data file.
readPythonTestData :: String -> IO String
readPythonTestData filename = do
    name <- testDataFilename "/test/data/" filename
    readFile name

-- | Returns the content of the specified haskell test data file.
readTestData :: String -> IO String
readTestData filename = do
    name <- testDataFilename "/htest/data/" filename
    readFile name

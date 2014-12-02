{-# LANGUAGE CPP #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Common helper functions and instances for all Ganeti tests.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Test.Ganeti.TestCommon
  ( maxMem
  , maxDsk
  , maxCpu
  , maxSpindles
  , maxVcpuRatio
  , maxSpindleRatio
  , maxNodes
  , maxOpCodes
  , (==?)
  , (/=?)
  , failTest
  , passTest
  , stableCover
  , pythonCmd
  , runPython
  , checkPythonResult
  , DNSChar(..)
  , genPrintableAsciiChar
  , genPrintableAsciiString
  , genPrintableAsciiStringNE
  , genName
  , genFQDN
  , genUUID
  , genMaybe
  , genSublist
  , genMap
  , genTags
  , genFields
  , genUniquesList
  , SmallRatio(..)
  , genSetHelper
  , genSet
  , genListSet
  , genAndRestArguments
  , genIPv4Address
  , genIPv4Network
  , genIp6Addr
  , genIp6Net
  , genOpCodesTagName
  , genLuxiTagName
  , netmask2NumHosts
  , testSerialisation
  , testArraySerialisation
  , testDeserialisationFail
  , resultProp
  , readTestData
  , genSample
  , testParser
  , genPropParser
  , genNonNegative
  , relativeError
  , getTempFileName
  , listOfUniqueBy
  , counterexample
  ) where

import Control.Applicative
import Control.Exception (catchJust)
import Control.Monad
import Data.Attoparsec.Text (Parser, parseOnly)
import Data.List
import qualified Data.Map as M
import Data.Text (pack)
import Data.Word
import qualified Data.Set as Set
import System.Directory (getTemporaryDirectory, removeFile)
import System.Environment (getEnv)
import System.Exit (ExitCode(..))
import System.IO (hClose, openTempFile)
import System.IO.Error (isDoesNotExistError)
import System.Process (readProcessWithExitCode)
import qualified Test.HUnit as HUnit
import Test.QuickCheck
#if !MIN_VERSION_QuickCheck(2,7,0)
import qualified Test.QuickCheck as QC
#endif
import Test.QuickCheck.Monadic
import qualified Text.JSON as J
import Numeric

import qualified Ganeti.BasicTypes as BasicTypes
import Ganeti.JSON (ArrayObject(..))
import Ganeti.Types
import Ganeti.Utils.Monad (unfoldrM)

-- * Arbitrary orphan instances

instance (Ord k, Arbitrary k, Arbitrary a) => Arbitrary (M.Map k a) where
  arbitrary = M.fromList <$> arbitrary
  shrink m = M.fromList <$> shrink (M.toList m)


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

-- | Max spindles (1024, somewhat random value).
maxSpindles :: Int
maxSpindles = 1024

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
(==?) x y = counterexample
            ("Expected equality, but got mismatch\nexpected: " ++
             show y ++ "\n but got: " ++ show x) (x == y)
infix 3 ==?

-- | Checks for inequality with proper annotation. The first argument
-- is the computed value, the second one the expected (not equal)
-- value.
(/=?) :: (Show a, Eq a) => a -> a -> Property
(/=?) x y = counterexample
            ("Expected inequality, but got equality: '" ++
             show x ++ "'.") (x /= y)
infix 3 /=?

-- | Show a message and fail the test.
failTest :: String -> Property
failTest msg = counterexample msg False

-- | A 'True' property.
passTest :: Property
passTest = property True

-- | A stable version of QuickCheck's `cover`. In its current implementation,
-- cover will not detect insufficient coverage if the actual coverage in the
-- sample is 0. Work around this by lifting the probability to at least
-- 10 percent.
-- The underlying issue is tracked at
-- https://github.com/nick8325/quickcheck/issues/26
stableCover :: Testable prop => Bool -> Int -> String -> prop -> Property
stableCover p percent s prop =
  let newlabel = "(stabilized to at least 10%) " ++ s
  in forAll (frequency [(1, return True), (9, return False)]) $ \ basechance ->
     cover (basechance || p) (10 + (percent * 9 `div` 10)) newlabel prop

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

-- * Generators

-- | Generates printable ASCII characters (from ' ' to '~').
genPrintableAsciiChar :: Gen Char
genPrintableAsciiChar = choose ('\x20', '\x7e')

-- | Generates a short string (0 <= n <= 40 chars) from printable ASCII.
genPrintableAsciiString :: Gen String
genPrintableAsciiString = do
  n <- choose (0, 40)
  vectorOf n genPrintableAsciiChar

-- | Generates a short string (1 <= n <= 40 chars) from printable ASCII.
genPrintableAsciiStringNE :: Gen NonEmptyString
genPrintableAsciiStringNE = do
  n <- choose (1, 40)
  vectorOf n genPrintableAsciiChar >>= mkNonEmpty

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

-- | Generates a UUID-like string.
--
-- Only to be used for QuickCheck testing. For obtaining actual UUIDs use
-- the newUUID function in Ganeti.Utils
genUUID :: Gen String
genUUID = do
  c1 <- vector 6
  c2 <- vector 4
  c3 <- vector 4
  c4 <- vector 4
  c5 <- vector 4
  c6 <- vector 4
  c7 <- vector 6
  return $ map dnsGetChar c1 ++ "-" ++ map dnsGetChar c2 ++ "-" ++
    map dnsGetChar c3 ++ "-" ++ map dnsGetChar c4 ++ "-" ++
    map dnsGetChar c5 ++ "-" ++ map dnsGetChar c6 ++ "-" ++
    map dnsGetChar c7

-- | Combinator that generates a 'Maybe' using a sub-combinator.
genMaybe :: Gen a -> Gen (Maybe a)
genMaybe subgen = frequency [ (1, pure Nothing), (3, Just <$> subgen) ]

-- | Generates a sublist of a given list, keeping the ordering.
-- The generated elements are always a subset of the list.
--
-- In order to better support corner cases, the size of the sublist is
-- chosen to have the uniform distribution.
genSublist :: [a] -> Gen [a]
genSublist xs = choose (0, l) >>= g xs l
  where
    l = length xs
    g _      _ 0 = return []
    g []     _ _ = return []
    g ys     n k | k == n = return ys
    g (y:ys) n k = frequency [ (k,     liftM (y :) (g ys (n - 1) (k - 1)))
                             , (n - k, g ys (n - 1) k)
                             ]

-- | Generates a map given generators for keys and values.
genMap :: (Ord k, Ord v) => Gen k -> Gen v -> Gen (M.Map k v)
genMap kg vg = M.fromList <$> listOf ((,) <$> kg <*> vg)

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

-- | Generates a 'Set' of arbitrary elements.
genSet :: (Ord a, Bounded a, Enum a) => Maybe Int -> Gen (Set.Set a)
genSet = genSetHelper [minBound..maxBound]

-- | Generates a 'Set' of arbitrary elements wrapped in a 'ListSet'
genListSet :: (Ord a, Bounded a, Enum a) => Maybe Int
              -> Gen (BasicTypes.ListSet a)
genListSet is = BasicTypes.ListSet <$> genSet is

-- | Generate an arbitrary element of and AndRestArguments field.
genAndRestArguments :: Gen (M.Map String J.JSValue)
genAndRestArguments = do
  n <- choose (0::Int, 10)
  let oneParam _ = do
                      name <- choose (15 ::Int, 25)
                                >>= flip vectorOf (elements tagChar)
                      intvalue <- arbitrary
                      value <- oneof [ J.JSString . J.toJSString <$> genName
                                     , return $ J.showJSON (intvalue :: Int)
                                     ]
                      return (name, value)
  M.fromList `liftM` mapM oneParam [1..n]

-- | Generate an arbitrary IPv4 address in textual form.
genIPv4 :: Gen String
genIPv4 = do
  a <- choose (1::Int, 255)
  b <- choose (0::Int, 255)
  c <- choose (0::Int, 255)
  d <- choose (0::Int, 255)
  return . intercalate "." $ map show [a, b, c, d]

genIPv4Address :: Gen IPv4Address
genIPv4Address = mkIPv4Address =<< genIPv4

-- | Generate an arbitrary IPv4 network in textual form.
genIPv4AddrRange :: Gen String
genIPv4AddrRange = do
  ip <- genIPv4
  netmask <- choose (8::Int, 30)
  return $ ip ++ "/" ++ show netmask

genIPv4Network :: Gen IPv4Network
genIPv4Network = mkIPv4Network =<< genIPv4AddrRange

-- | Helper function to compute the number of hosts in a network
-- given the netmask. (For IPv4 only.)
netmask2NumHosts :: Word8 -> Int
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

-- | Generates a valid, arbitrary tag name with respect to the given
-- 'TagKind' for opcodes.
genOpCodesTagName :: TagKind -> Gen (Maybe String)
genOpCodesTagName TagKindCluster = return Nothing
genOpCodesTagName _ = Just <$> genFQDN

-- | Generates a valid, arbitrary tag name with respect to the given
-- 'TagKind' for Luxi.
genLuxiTagName :: TagKind -> Gen String
genLuxiTagName TagKindCluster = return ""
genLuxiTagName _ = genFQDN

-- * Helper functions

-- | Checks for serialisation idempotence.
testSerialisation :: (Eq a, Show a, J.JSON a) => a -> Property
testSerialisation a =
  case J.readJSON (J.showJSON a) of
    J.Error msg -> failTest $ "Failed to deserialise: " ++ msg
    J.Ok a' -> a ==? a'

-- | Checks for array serialisation idempotence.
testArraySerialisation :: (Eq a, Show a, ArrayObject a) => a -> Property
testArraySerialisation a =
  case fromJSArray (toJSArray a) of
    J.Error msg -> failTest $ "Failed to deserialise: " ++ msg
    J.Ok a' -> a ==? a'

-- | Checks if the deserializer doesn't accept forbidden values.
-- The first argument is ignored, it just enforces the correct type.
testDeserialisationFail :: (Eq a, Show a, J.JSON a)
                        => a -> J.JSValue -> Property
testDeserialisationFail a val =
  case liftM (`asTypeOf` a) $ J.readJSON val of
    J.Error _ -> passTest
    J.Ok x    -> failTest $ "Parsed invalid value " ++ show val ++
                            " to: " ++ show x

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

-- | Returns the content of the specified haskell test data file.
readTestData :: String -> IO String
readTestData filename = do
    name <- testDataFilename "/test/data/" filename
    readFile name

-- | Generate arbitrary values in the IO monad. This is a simple
-- wrapper over 'sample''.
genSample :: Gen a -> IO a
genSample gen = do
  values <- sample' gen
  case values of
    [] -> error "sample' returned an empty list of values??"
    x:_ -> return x

-- | Function for testing whether a file is parsed correctly.
testParser :: (Show a, Eq a) => Parser a -> String -> a -> HUnit.Assertion
testParser parser fileName expectedContent = do
  fileContent <- readTestData fileName
  case parseOnly parser $ pack fileContent of
    Left msg -> HUnit.assertFailure $ "Parsing failed: " ++ msg
    Right obtained -> HUnit.assertEqual fileName expectedContent obtained

-- | Generate a property test for parsers.
genPropParser :: (Show a, Eq a) => Parser a -> String -> a -> Property
genPropParser parser s expected =
  case parseOnly parser $ pack s of
    Left msg -> failTest $ "Parsing failed: " ++ msg
    Right obtained -> expected ==? obtained

-- | Generate an arbitrary non negative integer number
genNonNegative :: Gen Int
genNonNegative =
  fmap fromEnum (arbitrary::Gen (Test.QuickCheck.NonNegative Int))

-- | Computes the relative error of two 'Double' numbers.
--
-- This is the \"relative error\" algorithm in
-- http:\/\/randomascii.wordpress.com\/2012\/02\/25\/
-- comparing-floating-point-numbers-2012-edition (URL split due to too
-- long line).
relativeError :: Double -> Double -> Double
relativeError d1 d2 =
  let delta = abs $ d1 - d2
      a1 = abs d1
      a2 = abs d2
      greatest = max a1 a2
  in if delta == 0
       then 0
       else delta / greatest

-- | Helper to a get a temporary file name.
getTempFileName :: String -> IO FilePath
getTempFileName filename = do
  tempdir <- getTemporaryDirectory
  (fpath, handle) <- openTempFile tempdir filename
  _ <- hClose handle
  removeFile fpath
  return fpath


-- | @listOfUniqueBy gen keyFun forbidden@: Generates a list of random length,
-- where all generated elements will be unique by the keying function
-- @keyFun@. They will also be distinct from all elements in @forbidden@ by
-- the keying function.
--
-- As for 'listOf', the maximum output length depends on the size parameter.
--
-- Example:
--
-- > listOfUniqueBy (arbitrary :: Gen String) (length) ["hey"]
-- > -- Generates a list of strings of different length, but not of length 3.
--
-- The passed @gen@ should not make key collisions too likely, since the
-- implementation uses `suchThat`, looping until enough unique elements
-- have been generated. If the @gen@ makes collisions likely, this function
-- will consequently be slow, or not terminate if it is not possible to
-- generate enough elements, like in:
--
-- > listOfUniqueBy (arbitrary :: Gen Int) (`mod` 2) []
-- > -- May not terminate depending on the size parameter of the Gen,
-- > -- since there are only 2 unique keys (0 and 1).
listOfUniqueBy :: (Ord b) => Gen a -> (a -> b) -> [a] -> Gen [a]
listOfUniqueBy gen keyFun forbidden = do
  let keysOf = Set.fromList . map keyFun

  k <- sized $ \n -> choose (0, n)
  flip unfoldrM (0, keysOf forbidden) $ \(i, usedKeys) ->
    if i == k
      then return Nothing
      else do
        x <- gen `suchThat` ((`Set.notMember` usedKeys) . keyFun)
        return $ Just (x, (i + 1, Set.insert (keyFun x) usedKeys))


#if !MIN_VERSION_QuickCheck(2,7,0)
counterexample :: Testable prop => String -> prop -> Property
counterexample = QC.printTestCase
#endif

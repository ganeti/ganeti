{-# LANGUAGE FlexibleContexts, ScopedTypeVariables, CPP #-}

{-| Utility functions. -}

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

module Ganeti.Utils
  ( debug
  , debugFn
  , debugXy
  , sepSplit
  , findFirst
  , stdDev
  , if'
  , select
  , applyIf
  , commaJoin
  , ensureQuoted
  , tryRead
  , readMaybe
  , formatTable
  , printTable
  , parseUnit
  , parseUnitAssumeBinary
  , plural
  , niceSort
  , niceSortKey
  , exitIfBad
  , exitErr
  , exitWhen
  , exitUnless
  , logWarningIfBad
  , rStripSpace
  , newUUID
  , isUUID
  , getCurrentTime
  , getCurrentTimeUSec
  , clockTimeToString
  , clockTimeToCTime
  , clockTimeToUSec
  , cTimeToClockTime
  , diffClockTimes
  , chompPrefix
  , warn
  , wrap
  , trim
  , defaultHead
  , exitIfEmpty
  , splitEithers
  , recombineEithers
  , resolveAddr
  , monadicThe
  , setOwnerAndGroupFromNames
  , setOwnerWGroupR
  , formatOrdinal
  , tryAndLogIOError
  , withDefaultOnIOError
  , lockFile
  , FStat
  , nullFStat
  , getFStat
  , getFStatSafe
  , needsReload
  , watchFile
  , watchFileBy
  , safeRenameFile
  , FilePermissions(..)
  , ensurePermissions
  , ordNub
  , isSubsequenceOf
  , frequency
  ) where

import Control.Concurrent
import Control.Exception (try, bracket)
import Control.Monad
import Control.Monad.Error
import Control.Monad.Fail (MonadFail)
import qualified Data.Attoparsec.ByteString as A
import qualified Data.ByteString.UTF8 as UTF8
import Data.Char (toUpper, isAlphaNum, isDigit, isSpace)
import qualified Data.Either as E
import Data.Function (on)
import Data.IORef
import Data.List
import qualified Data.Map as M
import Data.Maybe (fromMaybe)
import qualified Data.Set as S
import Foreign.C.Types (CTime(..))
import Numeric (showOct)
import System.Directory (renameFile, createDirectoryIfMissing)
import System.FilePath.Posix (takeDirectory)
import System.INotify
import System.Posix.Types

import Debug.Trace
import Network.Socket

import Ganeti.BasicTypes
import Ganeti.Compat
import qualified Ganeti.ConstantUtils as ConstantUtils
import Ganeti.Logging
import Ganeti.Runtime
import System.IO
import System.Exit
import System.Posix.Files
import System.Posix.IO
import System.Time (ClockTime(..), getClockTime, TimeDiff(..))
import qualified System.Time as STime

-- * Debug functions

-- | To be used only for debugging, breaks referential integrity.
debug :: Show a => a -> a
debug x = trace (show x) x

-- | Displays a modified form of the second parameter before returning
-- it.
debugFn :: Show b => (a -> b) -> a -> a
debugFn fn x = debug (fn x) `seq` x

-- | Show the first parameter before returning the second one.
debugXy :: Show a => a -> b -> b
debugXy = seq . debug

-- * Miscellaneous

-- | Apply the function if condition holds, otherwise use default value.
applyIf :: Bool -> (a -> a) -> a -> a
applyIf b f x = if b then f x else x

-- | Comma-join a string list.
commaJoin :: [String] -> String
commaJoin = intercalate ","

-- | Split a list on a separator and return a list of lists.
sepSplit :: Eq a => a -> [a] -> [[a]]
sepSplit sep s
  | null s    = []
  | null xs   = [x]
  | null ys   = [x,[]]
  | otherwise = x:sepSplit sep ys
  where (x, xs) = break (== sep) s
        ys = drop 1 xs

-- | Finds the first unused element in a set starting from a given base.
findFirst :: (Ord a, Enum a) => a -> S.Set a -> a
findFirst base xs =
  case S.splitMember base xs of
    (_, False, _) -> base
    (_, True, ys) -> fromMaybe (succ base) $
      (fmap fst . find (uncurry (<)) . zip [succ base..] . S.toAscList $ ys)
      `mplus` fmap (succ . fst) (S.maxView ys)

-- | Simple pluralize helper
plural :: Int -> String -> String -> String
plural 1 s _ = s
plural _ _ p = p

-- | Ensure a value is quoted if needed.
ensureQuoted :: String -> String
ensureQuoted v = if not (all (\c -> isAlphaNum c || c == '.') v)
                 then '\'':v ++ "'"
                 else v

-- * Mathematical functions

-- Simple and slow statistical functions, please replace with better
-- versions

-- | Standard deviation function.
stdDev :: [Double] -> Double
stdDev lst =
  -- first, calculate the list length and sum lst in a single step,
  -- for performance reasons
  let (ll', sx) = foldl' (\(rl, rs) e ->
                           let rl' = rl + 1
                               rs' = rs + e
                           in rl' `seq` rs' `seq` (rl', rs')) (0::Int, 0) lst
      ll = fromIntegral ll'::Double
      mv = sx / ll
      av = foldl' (\accu em -> let d = em - mv in accu + d * d) 0.0 lst
  in sqrt (av / ll) -- stddev

-- *  Logical functions

-- Avoid syntactic sugar and enhance readability. These functions are proposed
-- by some for inclusion in the Prelude, and at the moment they are present
-- (with various definitions) in the utility-ht package. Some rationale and
-- discussion is available at <http://www.haskell.org/haskellwiki/If-then-else>

-- | \"if\" as a function, rather than as syntactic sugar.
if' :: Bool -- ^ condition
    -> a    -- ^ \"then\" result
    -> a    -- ^ \"else\" result
    -> a    -- ^ \"then\" or "else" result depending on the condition
if' True x _ = x
if' _    _ y = y

-- * Parsing utility functions

-- | Parse results from readsPrec.
parseChoices :: MonadFail m => String -> String -> [(a, String)] -> m a
parseChoices _ _ [(v, "")] = return v
parseChoices name s [(_, e)] =
    fail $ name ++ ": leftover characters when parsing '"
           ++ s ++ "': '" ++ e ++ "'"
parseChoices name s _ = fail $ name ++ ": cannot parse string '" ++ s ++ "'"

-- | Safe 'read' function returning data encapsulated in a Result.
tryRead :: (MonadFail m, Read a) => String -> String -> m a
tryRead name s = parseChoices name s $ reads s

-- | Parse a string using the 'Read' instance.
-- Succeeds if there is exactly one valid result.
--
-- /Backport from Text.Read introduced in base-4.6.0.0/
readMaybe :: Read a => String -> Maybe a
readMaybe s = case reads s of
  [(a, "")] -> Just a
  _         -> Nothing

-- | Format a table of strings to maintain consistent length.
formatTable :: [[String]] -> [Bool] -> [[String]]
formatTable vals numpos =
    let vtrans = transpose vals  -- transpose, so that we work on rows
                                 -- rather than columns
        mlens = map (maximum . map length) vtrans
        expnd = map (\(flds, isnum, ml) ->
                         map (\val ->
                                  let delta = ml - length val
                                      filler = replicate delta ' '
                                  in if delta > 0
                                     then if isnum
                                          then filler ++ val
                                          else val ++ filler
                                     else val
                             ) flds
                    ) (zip3 vtrans numpos mlens)
   in transpose expnd

-- | Constructs a printable table from given header and rows
printTable :: String -> [String] -> [[String]] -> [Bool] -> String
printTable lp header rows isnum =
  unlines . map ((++) lp . (:) ' ' . unwords) $
  formatTable (header:rows) isnum

-- | Converts a unit (e.g. m or GB) into a scaling factor.
parseUnitValue :: (MonadFail m) => Bool -> String -> m Rational
parseUnitValue noDecimal unit
  -- binary conversions first
  | null unit                     = return 1
  | unit == "m" || upper == "MIB" = return 1
  | unit == "g" || upper == "GIB" = return kbBinary
  | unit == "t" || upper == "TIB" = return $ kbBinary * kbBinary
  -- SI conversions
  | unit == "M" || upper == "MB"  = return mbFactor
  | unit == "G" || upper == "GB"  = return $ mbFactor * kbDecimal
  | unit == "T" || upper == "TB"  = return $ mbFactor * kbDecimal * kbDecimal
  | otherwise = fail $ "Unknown unit '" ++ unit ++ "'"
  where upper = map toUpper unit
        kbBinary = 1024 :: Rational
        kbDecimal = if noDecimal then kbBinary else 1000
        decToBin = kbDecimal / kbBinary -- factor for 1K conversion
        mbFactor = decToBin * decToBin -- twice the factor for just 1K

-- | Tries to extract number and scale from the given string.
--
-- Input must be in the format NUMBER+ SPACE* [UNIT]. If no unit is
-- specified, it defaults to MiB. Return value is always an integral
-- value in MiB; if the first argument is True, all kilos are binary.
parseUnitEx :: (MonadFail m, Integral a, Read a) => Bool -> String -> m a
parseUnitEx noDecimal str =
  -- TODO: enhance this by splitting the unit parsing code out and
  -- accepting floating-point numbers
  case (reads str::[(Int, String)]) of
    [(v, suffix)] ->
      let unit = dropWhile (== ' ') suffix
      in do
        scaling <- parseUnitValue noDecimal unit
        return $ truncate (fromIntegral v * scaling)
    _ -> fail $ "Can't parse string '" ++ str ++ "'"

-- | Tries to extract number and scale from the given string.
--
-- Input must be in the format NUMBER+ SPACE* [UNIT]. If no unit is
-- specified, it defaults to MiB. Return value is always an integral
-- value in MiB.
parseUnit :: (MonadFail m, Integral a, Read a) => String -> m a
parseUnit = parseUnitEx False

-- | Tries to extract a number and scale from a given string, taking
-- all kilos to be binary.
parseUnitAssumeBinary :: (MonadFail m, Integral a, Read a) => String -> m a
parseUnitAssumeBinary = parseUnitEx True

-- | Unwraps a 'Result', exiting the program if it is a 'Bad' value,
-- otherwise returning the actual contained value.
exitIfBad :: String -> Result a -> IO a
exitIfBad msg (Bad s) = exitErr (msg ++ ": " ++ s)
exitIfBad _ (Ok v) = return v

-- | Exits immediately with an error message.
exitErr :: String -> IO a
exitErr errmsg = do
  hPutStrLn stderr $ "Error: " ++ errmsg
  exitWith (ExitFailure 1)

-- | Exits with an error message if the given boolean condition if true.
exitWhen :: Bool -> String -> IO ()
exitWhen True msg = exitErr msg
exitWhen False _  = return ()

-- | Exits with an error message /unless/ the given boolean condition
-- if true, the opposite of 'exitWhen'.
exitUnless :: Bool -> String -> IO ()
exitUnless cond = exitWhen (not cond)

-- | Unwraps a 'Result', logging a warning message and then returning a default
-- value if it is a 'Bad' value, otherwise returning the actual contained value.
logWarningIfBad :: String -> a -> Result a -> IO a
logWarningIfBad msg defVal (Bad s) = do
  logWarning $ msg ++ ": " ++ s
  return defVal
logWarningIfBad _ _ (Ok v) = return v

-- | Try an IO interaction, log errors and unfold as a 'Result'.
tryAndLogIOError :: IO a -> String -> (a -> Result b) -> IO (Result b)
tryAndLogIOError io msg okfn =
 try io >>= either
   (\ e -> do
       let combinedmsg = msg ++ ": " ++ show (e :: IOError)
       logError combinedmsg
       return . Bad $ combinedmsg)
   (return . okfn)

-- | Try an IO interaction and return a default value if the interaction
-- throws an IOError.
withDefaultOnIOError :: a -> IO a -> IO a
withDefaultOnIOError a io =
  try io >>= either (\ (_ :: IOError) -> return a) return

-- | Print a warning, but do not exit.
warn :: String -> IO ()
warn = hPutStrLn stderr . (++) "Warning: "

-- | Helper for 'niceSort'. Computes the key element for a given string.
extractKey :: [Either Integer String]  -- ^ Current (partial) key, reversed
           -> String                   -- ^ Remaining string
           -> ([Either Integer String], String)
extractKey ek [] = (reverse ek, [])
extractKey ek xs@(x:_) =
  let (span_fn, conv_fn) = if isDigit x
                             then (isDigit, Left . read)
                             else (not . isDigit, Right)
      (k, rest) = span span_fn xs
  in extractKey (conv_fn k:ek) rest

{-| Sort a list of strings based on digit and non-digit groupings.

Given a list of names @['a1', 'a10', 'a11', 'a2']@ this function
will sort the list in the logical order @['a1', 'a2', 'a10', 'a11']@.

The sort algorithm breaks each name in groups of either only-digits or
no-digits, and sorts based on each group.

Internally, this is not implemented via regexes (like the Python
version), but via actual splitting of the string in sequences of
either digits or everything else, and converting the digit sequences
in /Left Integer/ and the non-digit ones in /Right String/, at which
point sorting becomes trivial due to the built-in 'Either' ordering;
we only need one extra step of dropping the key at the end.

-}
niceSort :: [String] -> [String]
niceSort = niceSortKey id

-- | Key-version of 'niceSort'. We use 'sortBy' and @compare `on` fst@
-- since we don't want to add an ordering constraint on the /a/ type,
-- hence the need to only compare the first element of the /(key, a)/
-- tuple.
niceSortKey :: (a -> String) -> [a] -> [a]
niceSortKey keyfn =
  map snd . sortBy (compare `on` fst) .
  map (\s -> (fst . extractKey [] $ keyfn s, s))

-- | Strip space characthers (including newline). As this is
-- expensive, should only be run on small strings.
rStripSpace :: String -> String
rStripSpace = reverse . dropWhile isSpace . reverse

-- | Returns a random UUID.
-- This is a Linux-specific method as it uses the /proc filesystem.
newUUID :: IO String
newUUID = do
  contents <- readFile ConstantUtils.randomUuidFile
  return $! rStripSpace $ take 128 contents

-- | Parser that doesn't fail on a valid UUIDs (same as
-- "Ganeti.Constants.uuidRegex").
uuidCheckParser :: A.Parser ()
uuidCheckParser = do
  -- Not using Attoparsec.Char8 because "all attempts to use characters
  -- above code point U+00FF will give wrong answers" and we don't
  -- want such things to be accepted as UUIDs.
  let lowerHex = A.satisfy (\c -> (48 <= c && c <= 57) ||  -- 0-9
                                  (97 <= c && c <= 102))   -- a-f
      hx n = A.count n lowerHex
      d = A.word8 45  -- '-'
  void $ hx 8 >> d >> hx 4 >> d >> hx 4 >> d >> hx 4 >> d >> hx 12

-- | Checks if the string is a valid UUID as in "Ganeti.Constants.uuidRegex".
isUUID :: String -> Bool
isUUID =
  isRight . A.parseOnly (uuidCheckParser <* A.endOfInput) . UTF8.fromString

-- | Returns the current time as an 'Integer' representing the number
-- of seconds from the Unix epoch.
getCurrentTime :: IO Integer
getCurrentTime = do
  TOD ctime _ <- getClockTime
  return ctime

-- | Returns the current time as an 'Integer' representing the number
-- of microseconds from the Unix epoch (hence the need for 'Integer').
getCurrentTimeUSec :: IO Integer
getCurrentTimeUSec = liftM clockTimeToUSec getClockTime

-- | Convert a ClockTime into a (seconds-only) timestamp.
clockTimeToString :: ClockTime -> String
clockTimeToString (TOD t _) = show t

-- | Convert a ClockTime into a (seconds-only) 'EpochTime' (AKA @time_t@).
clockTimeToCTime :: ClockTime -> EpochTime
clockTimeToCTime (TOD secs _) = fromInteger secs

-- | Convert a ClockTime the number of microseconds since the epoch.
clockTimeToUSec :: ClockTime -> Integer
clockTimeToUSec (TOD ctime pico) =
  -- pico: 10^-12, micro: 10^-6, so we have to shift seconds left and
  -- picoseconds right
  ctime * 1000000 + pico `div` 1000000

-- | Convert a ClockTime into a (seconds-only) 'EpochTime' (AKA @time_t@).
cTimeToClockTime :: EpochTime -> ClockTime
cTimeToClockTime (CTime timet) = TOD (toInteger timet) 0

-- | A version of `diffClockTimes` that works around ghc bug #2519.
diffClockTimes :: ClockTime -> ClockTime -> TimeDiff
diffClockTimes t1 t2 =
  let delta = STime.diffClockTimes t1 t2
      secondInPicoseconds = 1000000000000
  in if tdPicosec delta < 0
       then delta { tdSec = tdSec delta - 1
                  , tdPicosec = tdPicosec delta + secondInPicoseconds
                  }
       else delta

{-| Strip a prefix from a string, allowing the last character of the prefix
(which is assumed to be a separator) to be absent from the string if the string
terminates there.

\>>> chompPrefix \"foo:bar:\" \"a:b:c\"
Nothing

\>>> chompPrefix \"foo:bar:\" \"foo:bar:baz\"
Just \"baz\"

\>>> chompPrefix \"foo:bar:\" \"foo:bar:\"
Just \"\"

\>>> chompPrefix \"foo:bar:\" \"foo:bar\"
Just \"\"

\>>> chompPrefix \"foo:bar:\" \"foo:barbaz\"
Nothing
-}
chompPrefix :: String -> String -> Maybe String
chompPrefix pfx str =
  if pfx `isPrefixOf` str || str == init pfx
    then Just $ drop (length pfx) str
    else Nothing

-- | Breaks a string in lines with length \<= maxWidth.
--
-- NOTE: The split is OK if:
--
-- * It doesn't break a word, i.e. the next line begins with space
--   (@isSpace . head $ rest@) or the current line ends with space
--   (@null revExtra@);
--
-- * It breaks a very big word that doesn't fit anyway (@null revLine@).
wrap :: Int      -- ^ maxWidth
     -> String   -- ^ string that needs wrapping
     -> [String] -- ^ string \"broken\" in lines
wrap maxWidth = filter (not . null) . map trim . wrap0
  where wrap0 :: String -> [String]
        wrap0 text
          | length text <= maxWidth = [text]
          | isSplitOK               = line : wrap0 rest
          | otherwise               = line' : wrap0 rest'
          where (line, rest) = splitAt maxWidth text
                (revExtra, revLine) = break isSpace . reverse $ line
                (line', rest') = (reverse revLine, reverse revExtra ++ rest)
                isSplitOK =
                  null revLine || null revExtra || startsWithSpace rest
                startsWithSpace (x:_) = isSpace x
                startsWithSpace _     = False

-- | Removes surrounding whitespace. Should only be used in small
-- strings.
trim :: String -> String
trim = reverse . dropWhile isSpace . reverse . dropWhile isSpace

-- | A safer head version, with a default value.
defaultHead :: a -> [a] -> a
defaultHead def []    = def
defaultHead _   (x:_) = x

-- | A 'head' version in the I/O monad, for validating parameters
-- without which we cannot continue.
exitIfEmpty :: String -> [a] -> IO a
exitIfEmpty _ (x:_) = return x
exitIfEmpty s []    = exitErr s

-- | Obtain the unique element of a list in an arbitrary monad.
monadicThe :: (Eq a, MonadFail m) => String -> [a] -> m a
monadicThe s [] = fail s
monadicThe s (x:xs)
  | all (x ==) xs = return x
  | otherwise = fail s

-- | Split an 'Either' list into two separate lists (containing the
-- 'Left' and 'Right' elements, plus a \"trail\" list that allows
-- recombination later.
--
-- This is splitter; for recombination, look at 'recombineEithers'.
-- The sum of \"left\" and \"right\" lists should be equal to the
-- original list length, and the trail list should be the same length
-- as well. The entries in the resulting lists are reversed in
-- comparison with the original list.
splitEithers :: [Either a b] -> ([a], [b], [Bool])
splitEithers = foldl' splitter ([], [], [])
  where splitter (l, r, t) e =
          case e of
            Left  v -> (v:l, r, False:t)
            Right v -> (l, v:r, True:t)

-- | Recombines two \"left\" and \"right\" lists using a \"trail\"
-- list into a single 'Either' list.
--
-- This is the counterpart to 'splitEithers'. It does the opposite
-- transformation, and the output list will be the reverse of the
-- input lists. Since 'splitEithers' also reverses the lists, calling
-- these together will result in the original list.
--
-- Mismatches in the structure of the lists (e.g. inconsistent
-- lengths) are represented via 'Bad'; normally this function should
-- not fail, if lists are passed as generated by 'splitEithers'.
recombineEithers :: (Show a, Show b) =>
                    [a] -> [b] -> [Bool] -> Result [Either a b]
recombineEithers lefts rights trail =
  foldM recombiner ([], lefts, rights) trail >>= checker
    where checker (eithers, [], []) = Ok eithers
          checker (_, lefts', rights') =
            Bad $ "Inconsistent results after recombination, l'=" ++
                show lefts' ++ ", r'=" ++ show rights'
          recombiner (es, l:ls, rs) False = Ok (Left l:es,  ls, rs)
          recombiner (es, ls, r:rs) True  = Ok (Right r:es, ls, rs)
          recombiner (_,  ls, rs) t = Bad $ "Inconsistent trail log: l=" ++
                                      show ls ++ ", r=" ++ show rs ++ ",t=" ++
                                      show t

-- | Default hints for the resolver
resolveAddrHints :: Maybe AddrInfo
resolveAddrHints =
  Just defaultHints { addrFlags = [AI_NUMERICHOST, AI_NUMERICSERV] }

-- | Resolves a numeric address.
resolveAddr :: Int -> String -> IO (Result (Family, SockAddr))
resolveAddr port str = do
  resolved <- getAddrInfo resolveAddrHints (Just str) (Just (show port))
  return $ case resolved of
             [] -> Bad "Invalid results from lookup?"
             best:_ -> Ok (addrFamily best, addrAddress best)

-- | Set the owner and the group of a file (given as names, not numeric id).
setOwnerAndGroupFromNames :: FilePath -> GanetiDaemon -> GanetiGroup -> IO ()
setOwnerAndGroupFromNames filename daemon dGroup = do
  -- TODO: it would be nice to rework this (or getEnts) so that runtimeEnts
  -- is read only once per daemon startup, and then cached for further usage.
  runtimeEnts <- runResultT getEnts
  ents <- exitIfBad "Can't find required user/groups" runtimeEnts
  -- note: we use directly ! as lookup failures shouldn't happen, due
  -- to the map construction
  let uid = reUserToUid ents M.! daemon
  let gid = reGroupToGid ents M.! dGroup
  setOwnerAndGroup filename uid gid

-- | Resets permissions so that the owner can read/write and the group only
-- read. All other permissions are cleared.
setOwnerWGroupR :: FilePath -> IO ()
setOwnerWGroupR path = setFileMode path mode
  where mode = foldl unionFileModes nullFileMode
                     [ownerReadMode, ownerWriteMode, groupReadMode]

-- | Formats an integral number, appending a suffix.
formatOrdinal :: (Integral a, Show a) => a -> String
formatOrdinal num
  | num > 10 && num < 20 = suffix "th"
  | tens == 1            = suffix "st"
  | tens == 2            = suffix "nd"
  | tens == 3            = suffix "rd"
  | otherwise            = suffix "th"
  where tens     = num `mod` 10
        suffix s = show num ++ s

-- | Attempt, in a non-blocking way, to obtain a lock on a given file; report
-- back success.
-- Returns the file descriptor so that the lock can be released by closing
lockFile :: FilePath -> IO (Result Fd)
lockFile path = runResultT . liftIO $ do
  handle <- openFile path WriteMode
  fd <- handleToFd handle
  setLock fd (WriteLock, AbsoluteSeek, 0, 0)
  return fd

-- | File stat identifier.
type FStat = (EpochTime, FileID, FileOffset)

-- | Null 'FStat' value.
nullFStat :: FStat
nullFStat = (-1, -1, -1)

-- | Computes the file cache data from a FileStatus structure.
buildFileStatus :: FileStatus -> FStat
buildFileStatus ofs =
    let modt = modificationTime ofs
        inum = fileID ofs
        fsize = fileSize ofs
    in (modt, inum, fsize)

-- | Wrapper over 'buildFileStatus'. This reads the data from the
-- filesystem and then builds our cache structure.
getFStat :: FilePath -> IO FStat
getFStat p = liftM buildFileStatus (getFileStatus p)

-- | Safe version of 'getFStat', that ignores IOErrors.
getFStatSafe :: FilePath -> IO FStat
getFStatSafe fpath = liftM (either (const nullFStat) id)
                       ((try $ getFStat fpath) :: IO (Either IOError FStat))

-- | Check if the file needs reloading
needsReload :: FStat -> FilePath -> IO (Maybe FStat)
needsReload oldstat path = do
  newstat <- getFStat path
  return $ if newstat /= oldstat
             then Just newstat
             else Nothing

-- | Until the given point in time (useconds since the epoch), wait
-- for the output of a given method to change and return the new value;
-- make use of the promise that the output only changes if the reference
-- has a value different than the given one.
watchFileEx :: (Eq b) => Integer -> b -> IORef b -> (a -> Bool) -> IO a -> IO a
watchFileEx endtime base ref check read_fn = do
  current <- getCurrentTimeUSec
  if current > endtime then read_fn else do
    val <- readIORef ref
    if val /= base
      then do
        new <- read_fn
        if check new then return new else do
          logDebug "Observed change not relevant"
          threadDelay 100000
          watchFileEx endtime val ref check read_fn
      else do
       threadDelay 100000
       watchFileEx endtime base ref check read_fn

-- | Within the given timeout (in seconds), wait for for the output
-- of the given method to satisfy a given predicate and return the new value;
-- make use of the promise that the method will only change its value, if
-- the given file changes on disk. If the file does not exist on disk, return
-- immediately.
watchFileBy :: FilePath -> Int -> (a -> Bool) -> IO a -> IO a
watchFileBy fpath timeout check read_fn = do
  current <- getCurrentTimeUSec
  let endtime = current + fromIntegral timeout * 1000000
  fstat <- getFStatSafe fpath
  ref <- newIORef fstat
  bracket initINotify killINotify $ \inotify -> do
    let do_watch e = do
                       logDebug $ "Notified of change in " ++ fpath
                                    ++ "; event: " ++ show e
                       when (e == Ignored)
                         (addWatch inotify [Modify, Delete]
                           (toInotifyPath fpath) do_watch >> return ())
                       fstat' <- getFStatSafe fpath
                       writeIORef ref fstat'
    _ <- addWatch inotify [Modify, Delete] (toInotifyPath fpath) do_watch
    newval <- read_fn
    if check newval
      then do
        logDebug $ "File " ++ fpath ++ " changed during setup of inotify"
        return newval
      else watchFileEx endtime fstat ref check read_fn

-- | Within the given timeout (in seconds), wait for for the output
-- of the given method to change and return the new value; make use of
-- the promise that the method will only change its value, if
-- the given file changes on disk. If the file does not exist on disk, return
-- immediately.
watchFile :: Eq a => FilePath -> Int -> a -> IO a -> IO a
watchFile fpath timeout old = watchFileBy fpath timeout (/= old)

-- | Type describing ownership and permissions of newly generated
-- directories and files. All parameters are optional, with nothing
-- meaning that the default value should be left untouched.

data FilePermissions = FilePermissions { fpOwner :: Maybe GanetiDaemon
                                       , fpGroup :: Maybe GanetiGroup
                                       , fpPermissions :: FileMode
                                       }

-- | Ensure that a given file or directory has the permissions, and
-- possibly ownerships, as required.
ensurePermissions :: FilePath -> FilePermissions -> IO (Result ())
ensurePermissions fpath perms = do
  -- Fetch the list of entities
  runtimeEnts <- runResultT getEnts
  ents <- exitIfBad "Can't determine user/group ids" runtimeEnts

  -- Get the existing file properties
  eitherFileStatus <- try $ getFileStatus fpath
                      :: IO (Either IOError FileStatus)

  -- And see if any modifications are needed
  (flip $ either (return . Bad . show)) eitherFileStatus $ \fstat -> do
    ownertry <- case fpOwner perms of
      Nothing -> return $ Right ()
      Just owner -> try $ do
        let ownerid = reUserToUid ents M.! owner
        unless (ownerid == fileOwner fstat) $ do
          logDebug $ "Changing owner of " ++ fpath ++ " to " ++ show owner
          setOwnerAndGroup fpath ownerid (-1)
    grouptry <- case fpGroup perms of
      Nothing -> return $ Right ()
      Just grp -> try $ do
        let groupid = reGroupToGid ents M.! grp
        unless (groupid == fileGroup fstat) $ do
          logDebug $ "Changing group of " ++ fpath ++ " to " ++ show grp
          setOwnerAndGroup fpath (-1) groupid
    let fp = fpPermissions perms
    permtry <- if fileMode fstat == fp
      then return $ Right ()
      else try $ do
        logInfo $ "Changing permissions of " ++ fpath ++ " to "
                    ++ showOct fp ""
        setFileMode fpath fp
    let errors = E.lefts ([ownertry, grouptry, permtry] :: [Either IOError ()])
    if null errors
      then return $ Ok ()
      else return . Bad $ show errors

-- | Safely rename a file, creating the target directory, if needed.
safeRenameFile :: FilePermissions -> FilePath -> FilePath -> IO (Result ())
safeRenameFile perms from to = do
  directtry <- try $ renameFile from to
  case (directtry :: Either IOError ()) of
    Right () -> return $ Ok ()
    Left _ -> do
      result <- try $ do
        let dir = takeDirectory to
        createDirectoryIfMissing True dir
        _ <- ensurePermissions dir perms
        renameFile from to
      return $ either (Bad . show) Ok (result :: Either IOError ())

-- | Removes duplicates, preserving order.
ordNub :: (Ord a) => [a] -> [a]
ordNub =
  let go _ [] = []
      go s (x:xs) = if x `S.member` s
        then go s xs
        else x : go (S.insert x s) xs
  in go S.empty

{-# ANN frequency "HLint: ignore Use alternative" #-}
-- | Returns a list of tuples of elements and the number of times they occur
-- in a list
frequency :: Ord t => [t] -> [(Int, t)]
frequency xs = map (\x -> (length x, head x)) . group . sort $ xs

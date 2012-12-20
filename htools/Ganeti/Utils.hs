{-| Utility functions. -}

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

module Ganeti.Utils
  ( debug
  , debugFn
  , debugXy
  , sepSplit
  , stdDev
  , if'
  , select
  , applyIf
  , commaJoin
  , ensureQuoted
  , tryRead
  , formatTable
  , printTable
  , parseUnit
  , plural
  , niceSort
  , niceSortKey
  , exitIfBad
  , exitErr
  , exitWhen
  , exitUnless
  , rStripSpace
  ) where

import Data.Char (toUpper, isAlphaNum, isDigit, isSpace)
import Data.Function (on)
import Data.List

import Debug.Trace

import Ganeti.BasicTypes
import System.IO
import System.Exit

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

-- | Split a list on a separator and return an array.
sepSplit :: Eq a => a -> [a] -> [[a]]
sepSplit sep s
  | null s    = []
  | null xs   = [x]
  | null ys   = [x,[]]
  | otherwise = x:sepSplit sep ys
  where (x, xs) = break (== sep) s
        ys = drop 1 xs

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
parseChoices :: (Monad m, Read a) => String -> String -> [(a, String)] -> m a
parseChoices _ _ ((v, ""):[]) = return v
parseChoices name s ((_, e):[]) =
    fail $ name ++ ": leftover characters when parsing '"
           ++ s ++ "': '" ++ e ++ "'"
parseChoices name s _ = fail $ name ++ ": cannot parse string '" ++ s ++ "'"

-- | Safe 'read' function returning data encapsulated in a Result.
tryRead :: (Monad m, Read a) => String -> String -> m a
tryRead name s = parseChoices name s $ reads s

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
parseUnitValue :: (Monad m) => String -> m Rational
parseUnitValue unit
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
        kbDecimal = 1000 :: Rational
        decToBin = kbDecimal / kbBinary -- factor for 1K conversion
        mbFactor = decToBin * decToBin -- twice the factor for just 1K

-- | Tries to extract number and scale from the given string.
--
-- Input must be in the format NUMBER+ SPACE* [UNIT]. If no unit is
-- specified, it defaults to MiB. Return value is always an integral
-- value in MiB.
parseUnit :: (Monad m, Integral a, Read a) => String -> m a
parseUnit str =
  -- TODO: enhance this by splitting the unit parsing code out and
  -- accepting floating-point numbers
  case (reads str::[(Int, String)]) of
    [(v, suffix)] ->
      let unit = dropWhile (== ' ') suffix
      in do
        scaling <- parseUnitValue unit
        return $ truncate (fromIntegral v * scaling)
    _ -> fail $ "Can't parse string '" ++ str ++ "'"

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
niceSort = map snd . sort . map (\s -> (fst $ extractKey [] s, s))

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

{-| Utility functions -}

module Ganeti.HTools.Utils
    (
      debug
    , isLeft
    , fromLeft
    , fromRight
    , sepSplit
    , swapPairs
    , varianceCoeff
    , readData
    , commaJoin
    ) where

import Data.Either
import Data.List
import Monad
import System
import System.IO

import Debug.Trace

-- | To be used only for debugging, breaks referential integrity.
debug :: Show a => a -> a
debug x = trace (show x) x

-- | Check if the given argument is Left something
isLeft :: Either a b -> Bool
isLeft val =
    case val of
      Left _ -> True
      _ -> False

fromLeft :: Either a b -> a
fromLeft = either (\x -> x) (\_ -> undefined)

fromRight :: Either a b -> b
fromRight = either (\_ -> undefined) id

-- | Comma-join a string list.
commaJoin :: [String] -> String
commaJoin = intercalate ","

-- | Split a string on a separator and return an array.
sepSplit :: Char -> String -> [String]
sepSplit sep s
    | x == "" && xs == [] = []
    | xs == []            = [x]
    | ys == []            = x:"":[]
    | otherwise           = x:(sepSplit sep ys)
    where (x, xs) = break (== sep) s
          ys = drop 1 xs

-- | Partial application of sepSplit to @'.'@
commaSplit :: String -> [String]
commaSplit = sepSplit ','

-- | Swap a list of @(a, b)@ into @(b, a)@
swapPairs :: [(a, b)] -> [(b, a)]
swapPairs = map (\ (a, b) -> (b, a))

-- Simple and slow statistical functions, please replace with better versions

-- | Mean value of a list.
meanValue :: Floating a => [a] -> a
meanValue lst = (sum lst) / (fromIntegral $ length lst)

-- | Standard deviation.
stdDev :: Floating a => [a] -> a
stdDev lst =
    let mv = meanValue lst
        square = (^ (2::Int)) -- silences "defaulting the constraint..."
        av = sum $ map square $ map (\e -> e - mv) lst
        bv = sqrt (av / (fromIntegral $ length lst))
    in bv

-- | Coefficient of variation.
varianceCoeff :: Floating a => [a] -> a
varianceCoeff lst = (stdDev lst) / (fromIntegral $ length lst)

-- | Get a Right result or print the error and exit
readData :: (String -> IO (Either String String)) -> String -> IO String
readData fn host = do
  nd <- fn host
  when (isLeft nd) $
       do
         putStrLn $ fromLeft nd
         exitWith $ ExitFailure 1
  return $ fromRight nd

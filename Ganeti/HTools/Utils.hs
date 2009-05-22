{-| Utility functions -}

module Ganeti.HTools.Utils
    (
      debug
    , sepSplit
    , varianceCoeff
    , readData
    , commaJoin
    , readEitherString
    , loadJSArray
    , fromObj
    , asJSObject
    , asObjectList
    , fromJResult
    ) where

import Data.List
import Control.Monad
import System
import System.IO
import qualified Text.JSON as J
import Text.Printf (printf)

import Ganeti.HTools.Types

import Debug.Trace

-- | To be used only for debugging, breaks referential integrity.
debug :: Show a => a -> a
debug x = trace (show x) x


fromJResult :: Monad m => J.Result a -> m a
fromJResult (J.Error x) = fail x
fromJResult (J.Ok x) = return x

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

-- | Get an Ok result or print the error and exit
readData :: Result a -> IO a
readData nd =
    (case nd of
       Bad x -> do
         putStrLn x
         exitWith $ ExitFailure 1
       Ok x -> return x)

readEitherString :: (Monad m) => J.JSValue -> m String
readEitherString v =
    case v of
      J.JSString s -> return $ J.fromJSString s
      _ -> fail "Wrong JSON type"

loadJSArray :: (Monad m) => String -> m [J.JSObject J.JSValue]
loadJSArray s = fromJResult $ J.decodeStrict s

fromObj :: (J.JSON a, Monad m) => String -> J.JSObject J.JSValue -> m a
fromObj k o =
    case lookup k (J.fromJSObject o) of
      Nothing -> fail $ printf "key '%s' not found in %s" k (show o)
      Just val -> fromJResult $ J.readJSON val

asJSObject :: (Monad m) => J.JSValue -> m (J.JSObject J.JSValue)
asJSObject (J.JSObject a) = return a
asJSObject _ = fail "not an object"

asObjectList :: (Monad m) => [J.JSValue] -> m [J.JSObject J.JSValue]
asObjectList = sequence . map asJSObject

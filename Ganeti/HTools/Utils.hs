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
    , combineEithers
    , ensureEitherList
    , eitherListHead
    , readEitherString
    , parseEitherList
    , loadJSArray
    , fromObj
    , getStringElement
    , getIntElement
    , getListElement
    , concatEitherElems
    , applyEither1
    , applyEither2
    ) where

import Data.Either
import Data.List
import Monad
import System
import System.IO
import Text.JSON
import Text.Printf (printf)

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

{-- Our cheap monad-like stuff.

Thi is needed since Either e a is already a monad instance somewhere
in the standard libraries (Control.Monad.Error) and we don't need that
entire thing.

-}
combineEithers :: (Either String a)
               -> (a -> Either String b)
               -> (Either String b)
combineEithers (Left s) _ = Left s
combineEithers (Right s) f = f s

ensureEitherList :: [Either String a] -> Either String [a]
ensureEitherList lst =
    foldr (\elem accu ->
               case (elem, accu) of
                 (Left x, _) -> Left x
                 (_, Left x) -> Left x -- should never happen
                 (Right e, Right a) -> Right (e:a)
          )
    (Right []) lst

eitherListHead :: Either String [a] -> Either String a
eitherListHead lst =
    case lst of
      Left x -> Left x
      Right (x:_) -> Right x
      Right [] -> Left "List empty"

readEitherString :: JSValue -> Either String String
readEitherString v =
    case v of
      JSString s -> Right $ fromJSString s
      _ -> Left "Wrong JSON type"

parseEitherList :: (JSObject JSValue -> Either String String)
          -> [JSObject JSValue]
          -> Either String String
parseEitherList fn idata =
    let ml = ensureEitherList $ map fn idata
    in ml `combineEithers` (Right . unlines)

loadJSArray :: String -> Either String [JSObject JSValue]
loadJSArray s = resultToEither $ decodeStrict s

fromObj :: JSON a => String -> JSObject JSValue -> Either String a
fromObj k o =
    case lookup k (fromJSObject o) of
      Nothing -> Left $ printf "key '%s' not found" k
      Just val -> resultToEither $ readJSON val

getStringElement :: String -> JSObject JSValue -> Either String String
getStringElement = fromObj

getIntElement :: String -> JSObject JSValue -> Either String Int
getIntElement = fromObj

getListElement :: String -> JSObject JSValue
               -> Either String [JSValue]
getListElement = fromObj

concatEitherElems :: Either String String
            -> Either String String
            -> Either String String
concatEitherElems = applyEither2 (\x y -> x ++ "|" ++ y)

applyEither1 :: (a -> b) -> Either String a -> Either String b
applyEither1 fn a =
    case a of
      Left x -> Left x
      Right y -> Right $ fn y

applyEither2 :: (a -> b -> c)
       -> Either String a
       -> Either String b
       -> Either String c
applyEither2 fn a b =
    case (a, b) of
      (Right x, Right y) -> Right $ fn x y
      (Left x, _) -> Left x
      (_, Left y) -> Left y

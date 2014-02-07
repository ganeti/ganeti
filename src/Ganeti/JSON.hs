{-# LANGUAGE TypeSynonymInstances, FlexibleInstances #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| JSON utility functions. -}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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

module Ganeti.JSON
  ( fromJResult
  , fromJResultE
  , readJSONWithDesc
  , readEitherString
  , JSRecord
  , loadJSArray
  , fromObj
  , maybeFromObj
  , fromObjWithDefault
  , fromKeyValue
  , fromJVal
  , fromJValE
  , jsonHead
  , getMaybeJsonHead
  , getMaybeJsonElem
  , asJSObject
  , asObjectList
  , tryFromObj
  , arrayMaybeFromJVal
  , tryArrayMaybeFromObj
  , toArray
  , optionalJSField
  , optFieldsToObj
  , readContainer
  , HasStringRepr(..)
  , GenericContainer(..)
  , Container
  , MaybeForJSON(..)
  , TimeAsDoubleJSON(..)
  )
  where

import Control.DeepSeq
import Control.Monad (liftM)
import Control.Monad.Error.Class
import Data.Maybe (fromMaybe, catMaybes)
import qualified Data.Map as Map
import System.Time (ClockTime(..))
import Text.Printf (printf)

import qualified Text.JSON as J
import Text.JSON.Pretty (pp_value)

-- Note: this module should not import any Ganeti-specific modules
-- beside BasicTypes, since it's used in THH which is used itself to
-- build many other modules.

import Ganeti.BasicTypes

-- * JSON-related functions

instance NFData J.JSValue where
  rnf J.JSNull           = ()
  rnf (J.JSBool b)       = rnf b
  rnf (J.JSRational b r) = rnf b `seq` rnf r
  rnf (J.JSString s)     = rnf $ J.fromJSString s
  rnf (J.JSArray a)      = rnf a
  rnf (J.JSObject o)     = rnf o

instance (NFData a) => NFData (J.JSObject a) where
  rnf = rnf . J.fromJSObject

-- | A type alias for a field of a JSRecord.
type JSField = (String, J.JSValue)

-- | A type alias for the list-based representation of J.JSObject.
type JSRecord = [JSField]

-- | Annotate @readJSON@ error messages with descriptions of what
-- is being parsed into what.
readJSONWithDesc :: (J.JSON a)
                 => String                    -- ^ description of @a@
                 -> Bool                      -- ^ include input in
                                              --   error messages
                 -> J.JSValue                 -- ^ input value
                 -> J.Result a
readJSONWithDesc typ incInput input =
  case J.readJSON input of
    J.Ok r    -> J.Ok r
    J.Error e -> J.Error $ if incInput then msg ++ " from " ++ show input
                                       else msg
      where msg = "Can't parse value for type " ++ typ ++ ": " ++ e

-- | Converts a JSON Result into a monadic value.
fromJResult :: Monad m => String -> J.Result a -> m a
fromJResult s (J.Error x) = fail (s ++ ": " ++ x)
fromJResult _ (J.Ok x) = return x

-- | Converts a JSON Result into a MonadError value.
fromJResultE :: (Error e, MonadError e m) => String -> J.Result a -> m a
fromJResultE s (J.Error x) = throwError . strMsg $ s ++ ": " ++ x
fromJResultE _ (J.Ok x) = return x

-- | Tries to read a string from a JSON value.
--
-- In case the value was not a string, we fail the read (in the
-- context of the current monad.
readEitherString :: (Monad m) => J.JSValue -> m String
readEitherString v =
  case v of
    J.JSString s -> return $ J.fromJSString s
    _ -> fail "Wrong JSON type"

-- | Converts a JSON message into an array of JSON objects.
loadJSArray :: (Monad m)
               => String -- ^ Operation description (for error reporting)
               -> String -- ^ Input message
               -> m [J.JSObject J.JSValue]
loadJSArray s = fromJResult s . J.decodeStrict

-- | Helper function for missing-key errors
buildNoKeyError :: JSRecord -> String -> String
buildNoKeyError o k =
  printf "key '%s' not found, object contains only %s" k (show (map fst o))

-- | Reads the value of a key in a JSON object.
fromObj :: (J.JSON a, Monad m) => JSRecord -> String -> m a
fromObj o k =
  case lookup k o of
    Nothing -> fail $ buildNoKeyError o k
    Just val -> fromKeyValue k val

-- | Reads the value of an optional key in a JSON object. Missing
-- keys, or keys that have a \'null\' value, will be returned as
-- 'Nothing', otherwise we attempt deserialisation and return a 'Just'
-- value.
maybeFromObj :: (J.JSON a, Monad m) =>
                JSRecord -> String -> m (Maybe a)
maybeFromObj o k =
  case lookup k o of
    Nothing -> return Nothing
    -- a optional key with value JSNull is the same as missing, since
    -- we can't convert it meaningfully anyway to a Haskell type, and
    -- the Python code can emit 'null' for optional values (depending
    -- on usage), and finally our encoding rules treat 'null' values
    -- as 'missing'
    Just J.JSNull -> return Nothing
    Just val -> liftM Just (fromKeyValue k val)

-- | Reads the value of a key in a JSON object with a default if
-- missing. Note that both missing keys and keys with value \'null\'
-- will cause the default value to be returned.
fromObjWithDefault :: (J.JSON a, Monad m) =>
                      JSRecord -> String -> a -> m a
fromObjWithDefault o k d = liftM (fromMaybe d) $ maybeFromObj o k

arrayMaybeFromJVal :: (J.JSON a, Monad m) => J.JSValue -> m [Maybe a]
arrayMaybeFromJVal (J.JSArray xs) =
  mapM parse xs
    where
      parse J.JSNull = return Nothing
      parse x = liftM Just $ fromJVal x
arrayMaybeFromJVal v =
  fail $ "Expecting array, got '" ++ show (pp_value v) ++ "'"

-- | Reads an array of optional items
arrayMaybeFromObj :: (J.JSON a, Monad m) =>
                     JSRecord -> String -> m [Maybe a]
arrayMaybeFromObj o k =
  case lookup k o of
    Just a -> arrayMaybeFromJVal a
    _ -> fail $ buildNoKeyError o k

-- | Wrapper for arrayMaybeFromObj with better diagnostic
tryArrayMaybeFromObj :: (J.JSON a)
                     => String     -- ^ Textual "owner" in error messages
                     -> JSRecord   -- ^ The object array
                     -> String     -- ^ The desired key from the object
                     -> Result [Maybe a]
tryArrayMaybeFromObj t o = annotateResult t . arrayMaybeFromObj o

-- | Reads a JValue, that originated from an object key.
fromKeyValue :: (J.JSON a, Monad m)
              => String     -- ^ The key name
              -> J.JSValue  -- ^ The value to read
              -> m a
fromKeyValue k val =
  fromJResult (printf "key '%s'" k) (J.readJSON val)

-- | Small wrapper over readJSON.
fromJVal :: (Monad m, J.JSON a) => J.JSValue -> m a
fromJVal v =
  case J.readJSON v of
    J.Error s -> fail ("Cannot convert value '" ++ show (pp_value v) ++
                       "', error: " ++ s)
    J.Ok x -> return x

-- | Small wrapper over 'readJSON' for 'MonadError'.
fromJValE :: (Error e, MonadError e m, J.JSON a) => J.JSValue -> m a
fromJValE v =
  case J.readJSON v of
    J.Error s -> throwError . strMsg $
                  "Cannot convert value '" ++ show (pp_value v) ++
                  "', error: " ++ s
    J.Ok x -> return x

-- | Helper function that returns Null or first element of the list.
jsonHead :: (J.JSON b) => [a] -> (a -> b) -> J.JSValue
jsonHead [] _ = J.JSNull
jsonHead (x:_) f = J.showJSON $ f x

-- | Helper for extracting Maybe values from a possibly empty list.
getMaybeJsonHead :: (J.JSON b) => [a] -> (a -> Maybe b) -> J.JSValue
getMaybeJsonHead [] _ = J.JSNull
getMaybeJsonHead (x:_) f = maybe J.JSNull J.showJSON (f x)

-- | Helper for extracting Maybe values from a list that might be too short.
getMaybeJsonElem :: (J.JSON b) => [a] -> Int -> (a -> Maybe b) -> J.JSValue
getMaybeJsonElem [] _ _ = J.JSNull
getMaybeJsonElem xs 0 f = getMaybeJsonHead xs f
getMaybeJsonElem (_:xs) n f
  | n < 0 = J.JSNull
  | otherwise = getMaybeJsonElem xs (n - 1) f

-- | Converts a JSON value into a JSON object.
asJSObject :: (Monad m) => J.JSValue -> m (J.JSObject J.JSValue)
asJSObject (J.JSObject a) = return a
asJSObject _ = fail "not an object"

-- | Coneverts a list of JSON values into a list of JSON objects.
asObjectList :: (Monad m) => [J.JSValue] -> m [J.JSObject J.JSValue]
asObjectList = mapM asJSObject

-- | Try to extract a key from an object with better error reporting
-- than fromObj.
tryFromObj :: (J.JSON a) =>
              String     -- ^ Textual "owner" in error messages
           -> JSRecord   -- ^ The object array
           -> String     -- ^ The desired key from the object
           -> Result a
tryFromObj t o = annotateResult t . fromObj o

-- | Ensure a given JSValue is actually a JSArray.
toArray :: (Monad m) => J.JSValue -> m [J.JSValue]
toArray (J.JSArray arr) = return arr
toArray o =
  fail $ "Invalid input, expected array but got " ++ show (pp_value o)

-- | Creates a Maybe JSField. If the value string is Nothing, the JSField
-- will be Nothing as well.
optionalJSField :: (J.JSON a) => String -> Maybe a -> Maybe JSField
optionalJSField name (Just value) = Just (name, J.showJSON value)
optionalJSField _ Nothing = Nothing

-- | Creates an object with all the non-Nothing fields of the given list.
optFieldsToObj :: [Maybe JSField] -> J.JSValue
optFieldsToObj = J.makeObj . catMaybes

-- * Container type (special type for JSON serialisation)

-- | Class of types that can be converted from Strings. This is
-- similar to the 'Read' class, but it's using a different
-- serialisation format, so we have to define a separate class. Mostly
-- useful for custom key types in JSON dictionaries, which have to be
-- backed by strings.
class HasStringRepr a where
  fromStringRepr :: (Monad m) => String -> m a
  toStringRepr :: a -> String

-- | Trivial instance 'HasStringRepr' for 'String'.
instance HasStringRepr String where
  fromStringRepr = return
  toStringRepr = id

-- | The container type, a wrapper over Data.Map
newtype GenericContainer a b =
  GenericContainer { fromContainer :: Map.Map a b }
  deriving (Show, Eq)

instance (NFData a, NFData b) => NFData (GenericContainer a b) where
  rnf = rnf . Map.toList . fromContainer

-- | Type alias for string keys.
type Container = GenericContainer String

-- | Container loader.
readContainer :: (Monad m, HasStringRepr a, Ord a, J.JSON b) =>
                 J.JSObject J.JSValue -> m (GenericContainer a b)
readContainer obj = do
  let kjvlist = J.fromJSObject obj
  kalist <- mapM (\(k, v) -> do
                    k' <- fromStringRepr k
                    v' <- fromKeyValue k v
                    return (k', v')) kjvlist
  return $ GenericContainer (Map.fromList kalist)

{-# ANN showContainer "HLint: ignore Use ***" #-}
-- | Container dumper.
showContainer :: (HasStringRepr a, J.JSON b) =>
                 GenericContainer a b -> J.JSValue
showContainer =
  J.makeObj . map (\(k, v) -> (toStringRepr k, J.showJSON v)) .
  Map.toList . fromContainer

instance (HasStringRepr a, Ord a, J.JSON b) =>
         J.JSON (GenericContainer a b) where
  showJSON = showContainer
  readJSON (J.JSObject o) = readContainer o
  readJSON v = fail $ "Failed to load container, expected object but got "
               ++ show (pp_value v)

-- | A Maybe newtype that allows for serialization more appropriate to the
-- semantics of Maybe and JSON in our calls. Does not produce needless
-- and confusing dictionaries.
newtype MaybeForJSON a = MaybeForJSON { unMaybeForJSON :: Maybe a }
  deriving (Show, Eq, Ord)
instance (J.JSON a) => J.JSON (MaybeForJSON a) where
  readJSON J.JSNull = return $ MaybeForJSON Nothing
  readJSON x        = (MaybeForJSON . Just) `liftM` J.readJSON x
  showJSON (MaybeForJSON (Just x)) = J.showJSON x
  showJSON (MaybeForJSON Nothing)  = J.JSNull

newtype TimeAsDoubleJSON
    = TimeAsDoubleJSON { unTimeAsDoubleJSON :: ClockTime }
  deriving (Show, Eq, Ord)
instance J.JSON TimeAsDoubleJSON where
  readJSON v = do
      t <- J.readJSON v :: J.Result Double
      return . TimeAsDoubleJSON . uncurry TOD
             $ divMod (round $ t * pico) (pico :: Integer)
    where
      pico :: (Num a) => a
      pico = 10^(12 :: Int)
  showJSON (TimeAsDoubleJSON (TOD ss ps)) = J.showJSON
      (fromIntegral ss + fromIntegral ps / 10^(12 :: Int) :: Double)

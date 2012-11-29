{-# LANGUAGE Rank2Types #-}

{-| Implementation of the Ganeti Query2 filterning.

The filtering of results should be done in two phases.

In the first phase, before contacting any remote nodes for runtime
data, the filtering should be executed with 'Nothing' for the runtime
context. This will make all non-runtime filters filter correctly,
whereas all runtime filters will respond successfully. As described in
the Python version too, this makes for example /Or/ filters very
inefficient if they contain runtime fields.

Once this first filtering phase has been done, we hopefully eliminated
some remote nodes out of the list of candidates, we run the remote
data gathering, and we evaluate the filter again, this time with a
'Just' runtime context. This will make all filters work correctly.

Note that the second run will re-evaluate the config/simple fields,
without caching; this is not perfect, but we consider config accesses
very cheap (and the configuration snapshot we have won't change
between the two runs, hence we will not get inconsistent results).

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.Query.Filter
  ( compileFilter
  , evaluateFilter
  , requestedNames
  , makeSimpleFilter
  ) where

import Control.Applicative
import Control.Monad (liftM)
import qualified Data.Map as Map
import Data.Traversable (traverse)
import Text.JSON (JSValue(..), fromJSString)
import Text.JSON.Pretty (pp_value)
import qualified Text.Regex.PCRE as PCRE

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Objects
import Ganeti.Query.Language
import Ganeti.Query.Types
import Ganeti.JSON

-- | Compiles a filter based on field names to one based on getters.
compileFilter :: FieldMap a b
              -> Filter FilterField
              -> ErrorResult (Filter (FieldGetter a b))
compileFilter fm =
  traverse (\field -> maybe
                      (Bad . ParameterError $ "Can't find field named '" ++
                           field ++ "'")
                      (Ok . snd) (field `Map.lookup` fm))

-- | Wraps a getter, filter pair. If the getter is 'FieldRuntime' but
-- we don't have a runtime context, we skip the filtering, returning
-- \"pass\". Otherwise, we pass the actual value to the filter.
wrapGetter :: ConfigData
           -> Maybe b
           -> a
           -> FieldGetter a b
           -> (JSValue -> ErrorResult Bool)
           -> ErrorResult Bool
wrapGetter cfg b a getter faction =
  case tryGetter cfg b a getter of
    Nothing -> Ok True -- runtime missing, accepting the value
    Just v ->
      case v of
        ResultEntry RSNormal (Just fval) -> faction fval
        ResultEntry RSNormal Nothing ->
          Bad $ ProgrammerError
                "Internal error: Getter returned RSNormal/Nothing"
        _ -> Ok True -- filter has no data to work, accepting it

-- | Helper to evaluate a filter getter (and the value it generates) in
-- a boolean context.
trueFilter :: JSValue -> ErrorResult Bool
trueFilter (JSBool x) = Ok $! x
trueFilter v = Bad . ParameterError $
               "Unexpected value '" ++ show (pp_value v) ++
               "' in boolean context"

-- | A type synonim for a rank-2 comparator function. This is used so
-- that we can pass the usual '<=', '>', '==' functions to 'binOpFilter'
-- and for them to be used in multiple contexts.
type Comparator = (Eq a, Ord a) => a -> a -> Bool

-- | Helper to evaluate a filder getter (and the value it generates)
-- in a boolean context. Note the order of arguments is reversed from
-- the filter definitions (due to the call chain), make sure to
-- compare in the reverse order too!.
binOpFilter :: Comparator -> FilterValue -> JSValue -> ErrorResult Bool
binOpFilter comp (QuotedString y) (JSString x) =
  Ok $! fromJSString x `comp` y
binOpFilter comp (NumericValue y) (JSRational _ x) =
  Ok $! x `comp` fromIntegral y
binOpFilter _ expr actual =
  Bad . ParameterError $ "Invalid types in comparison, trying to compare " ++
      show (pp_value actual) ++ " with '" ++ show expr ++ "'"

-- | Implements the 'RegexpFilter' matching.
regexpFilter :: FilterRegex -> JSValue -> ErrorResult Bool
regexpFilter re (JSString val) =
  Ok $! PCRE.match (compiledRegex re) (fromJSString val)
regexpFilter _ x =
  Bad . ParameterError $ "Invalid field value used in regexp matching,\
        \ expecting string but got '" ++ show (pp_value x) ++ "'"

-- | Implements the 'ContainsFilter' matching.
containsFilter :: FilterValue -> JSValue -> ErrorResult Bool
-- note: the next two implementations are the same, but we have to
-- repeat them due to the encapsulation done by FilterValue
containsFilter (QuotedString val) lst = do
  lst' <- fromJVal lst
  return $! val `elem` lst'
containsFilter (NumericValue val) lst = do
  lst' <- fromJVal lst
  return $! val `elem` lst'

-- | Verifies if a given item passes a filter. The runtime context
-- might be missing, in which case most of the filters will consider
-- this as passing the filter.
evaluateFilter :: ConfigData -> Maybe b -> a
               -> Filter (FieldGetter a b)
               -> ErrorResult Bool
evaluateFilter _ _  _ EmptyFilter = Ok True
evaluateFilter c mb a (AndFilter flts) =
  all id <$> mapM (evaluateFilter c mb a) flts
evaluateFilter c mb a (OrFilter flts)  =
  any id <$> mapM (evaluateFilter c mb a) flts
evaluateFilter c mb a (NotFilter flt)  =
  not <$> evaluateFilter c mb a flt
evaluateFilter c mb a (TrueFilter getter)  =
  wrapGetter c mb a getter trueFilter
evaluateFilter c mb a (EQFilter getter val) =
  wrapGetter c mb a getter (binOpFilter (==) val)
evaluateFilter c mb a (LTFilter getter val) =
  wrapGetter c mb a getter (binOpFilter (<) val)
evaluateFilter c mb a (LEFilter getter val) =
  wrapGetter c mb a getter (binOpFilter (<=) val)
evaluateFilter c mb a (GTFilter getter val) =
  wrapGetter c mb a getter (binOpFilter (>) val)
evaluateFilter c mb a (GEFilter getter val) =
  wrapGetter c mb a getter (binOpFilter (>=) val)
evaluateFilter c mb a (RegexpFilter getter re) =
  wrapGetter c mb a getter (regexpFilter re)
evaluateFilter c mb a (ContainsFilter getter val) =
  wrapGetter c mb a getter (containsFilter val)

-- | Runs a getter with potentially missing runtime context.
tryGetter :: ConfigData -> Maybe b -> a -> FieldGetter a b -> Maybe ResultEntry
tryGetter _   _ item (FieldSimple getter)  = Just $ getter item
tryGetter cfg _ item (FieldConfig getter)  = Just $ getter cfg item
tryGetter _  rt item (FieldRuntime getter) =
  maybe Nothing (\rt' -> Just $ getter rt' item) rt
tryGetter _   _ _    FieldUnknown          = Just $
                                             ResultEntry RSUnknown Nothing

-- | Computes the requested names, if only names were requested (and
-- with equality). Otherwise returns 'Nothing'.
requestedNames :: FilterField -> Filter FilterField -> Maybe [FilterValue]
requestedNames _ EmptyFilter = Just []
requestedNames namefield (OrFilter flts) =
  liftM concat $ mapM (requestedNames namefield) flts
requestedNames namefield (EQFilter fld val) =
  if namefield == fld
    then Just [val]
    else Nothing
requestedNames _ _ = Nothing

-- | Builds a simple filter from a list of names.
makeSimpleFilter :: String -> [String] -> Filter FilterField
makeSimpleFilter _ [] = EmptyFilter
makeSimpleFilter namefield vals =
  OrFilter $ map (EQFilter namefield . QuotedString) vals

{-# LANGUAGE RankNTypes, GADTs, StandaloneDeriving #-}

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

Copyright (C) 2012, 2013 Google Inc.
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

module Ganeti.Query.Filter
  ( compileFilter
  , evaluateQueryFilter
  , evaluateFilterM
  , evaluateFilterJSON
  , requestedNames
  , makeSimpleFilter
  , Comparator
  , Comparison(..)
  , toCompFun
  , FilterOp(..)
  ) where

import Control.Applicative
import Control.Monad (liftM, mzero)
import Control.Monad.Trans.Maybe (MaybeT, runMaybeT)
import Control.Monad.Trans.Class (lift)
import qualified Data.Map as Map
import Data.Maybe
import Data.Traversable (traverse)
import Text.JSON (JSValue(..), fromJSString)
import Text.JSON.Pretty (pp_value)
import qualified Text.Regex.PCRE as PCRE

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Objects
import Ganeti.Query.Language
import Ganeti.Query.Types
import Ganeti.Utils.Monad (anyM, allM)
import Ganeti.JSON (fromJVal)

-- | Compiles a filter based on field names to one based on getters.
compileFilter :: FieldMap a b
              -> Filter FilterField
              -> ErrorResult (Filter (FieldGetter a b, QffMode))
compileFilter fm =
  traverse (\field -> maybe
                      (Bad . ParameterError $ "Can't find field named '" ++
                           field ++ "'")
                      (\(_, g, q) -> Ok (g, q)) (field `Map.lookup` fm))

-- | Processes a field value given a QffMode.
qffField :: QffMode -> JSValue -> ErrorResult JSValue
qffField QffNormal    v = Ok v
qffField QffHostname  v = Ok v
qffField QffTimestamp v =
  case v of
    JSArray [secs@(JSRational _ _), JSRational _ _] -> return secs
    _ -> Bad $ ProgrammerError
         "Internal error: Getter returned non-timestamp for QffTimestamp"

-- | Wraps a getter, filter pair. If the getter is 'FieldRuntime' but
-- we don't have a runtime context, we skip the filtering, returning
-- `Nothing` in the MaybeT. Otherwise, we pass the actual value to the filter.
wrapGetter :: ConfigData
           -> Maybe b
           -> a
           -> (FieldGetter a b, QffMode)
           -> (JSValue -> ErrorResult Bool)
           -> MaybeT ErrorResult Bool
wrapGetter cfg b a (getter, qff) faction =
  case tryGetter cfg b a getter of
    Nothing -> mzero -- runtime missing, signalling that with MaybeT Nothing
    Just v -> lift $
      case v of
        ResultEntry RSNormal (Just fval) -> qffField qff fval >>= faction
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

-- | Equality checker.
--
-- This will handle hostnames correctly, if the mode is set to
-- 'QffHostname'.
eqFilter :: QffMode -> FilterValue -> JSValue -> ErrorResult Bool
-- send 'QffNormal' queries to 'binOpFilter'
eqFilter QffNormal    flv jsv = binOpFilter (==) flv jsv
-- and 'QffTimestamp' as well
eqFilter QffTimestamp flv jsv = binOpFilter (==) flv jsv
-- error out if we set 'QffHostname' on a non-string field
eqFilter QffHostname _ (JSRational _ _) =
  Bad . ProgrammerError $ "QffHostname field returned a numeric value"
-- test strings via 'compareNameComponent'
eqFilter QffHostname (QuotedString y) (JSString x) =
  Ok $ goodLookupResult (fromJSString x `compareNameComponent` y)
-- send all other combinations (all errors) to 'binOpFilter', which
-- has good error messages
eqFilter _ flv jsv = binOpFilter (==) flv jsv

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


-- | Ways we can compare things in the filter language.
data Comparison = Eq | Lt | Le | Gt | Ge
  deriving (Eq, Ord, Show)


-- | Turns a comparison into the corresponding Haskell function.
toCompFun :: Comparison -> Comparator
toCompFun cmp = case cmp of
  Eq -> (==)
  Lt -> (<)
  Le -> (<=)
  Gt -> (>)
  Ge -> (>=)


-- | Operations in the leaves of the Ganeti filter language.
data FilterOp field val where
  Truth    ::               FilterOp field ()
  Comp     :: Comparison -> FilterOp field FilterValue
  Regex    ::               FilterOp field FilterRegex
  Contains ::               FilterOp field FilterValue

deriving instance Eq (FilterOp field val)
deriving instance Show (FilterOp field val)


-- | Checks if a filter matches.
--
-- The leaves of the filter are evaluated against an object using the passed
-- `opFun`; that is why the object need not be passed in.
--
-- The `field` type describes the "accessors" that are used to query
-- values from the object; those values are to be matched against the
-- `val` type in the filter leaves.
--
-- Useful monads @m@ for this are `ErrorResult` and `Maybe`.
evaluateFilterM :: (Monad m, Applicative m)
                  => (forall val .
                        FilterOp field val -> field -> val -> m Bool)
                  -> Filter field
                  -> m Bool
evaluateFilterM opFun fil = case fil of
  EmptyFilter              -> return True
  AndFilter flts           -> allM recurse flts
  OrFilter flts            -> anyM recurse flts
  NotFilter flt            -> not <$> recurse flt
  TrueFilter field         -> opFun Truth     field ()
  EQFilter field val       -> opFun (Comp Eq) field val
  LTFilter field val       -> opFun (Comp Lt) field val
  LEFilter field val       -> opFun (Comp Le) field val
  GTFilter field val       -> opFun (Comp Gt) field val
  GEFilter field val       -> opFun (Comp Ge) field val
  RegexpFilter field re    -> opFun Regex     field re
  ContainsFilter field val -> opFun Contains  field val
  where
    recurse = evaluateFilterM opFun


-- | Verifies if a given item passes a filter. The runtime context
-- might be missing, in which case most of the filters will consider
-- this as passing the filter.
evaluateQueryFilter :: ConfigData -> Maybe b -> a
                    -> Filter (FieldGetter a b, QffMode)
                    -> ErrorResult Bool
evaluateQueryFilter c mb a =
  -- `Nothing` in the MaybeT means "missing but needed runtime context".
  -- Turn those cases into True (let the filter pass).
  fmap (fromMaybe True) . runMaybeT . evaluateFilterM (\op -> case op of
    Truth    -> \gQff ()  -> wrap gQff trueFilter
    -- We're special casing comparison for host names.
    -- All other comparisons behave as usual.
    Comp Eq  -> \gQff val -> wrap gQff $ eqFilter (snd gQff) val
    Comp cmp -> \gQff val -> wrap gQff $ binOpFilter (toCompFun cmp) val
    Regex    -> \gQff re  -> wrap gQff $ regexpFilter re
    Contains -> \gQff val -> wrap gQff $ containsFilter val
  )
  where
    wrap = wrapGetter c mb a


-- | Evaluates a `Filter` on a JSON object.
evaluateFilterJSON :: Filter JSValue -> ErrorResult Bool
evaluateFilterJSON =
  evaluateFilterM $ \op -> case op of
    Comp cmp -> let compFun = toCompFun cmp
                in \json fv -> pure $ json `compFun` showFilterValue fv
    Truth    -> \field () -> trueFilter field
    Regex    -> flip regexpFilter
    Contains -> flip containsFilter


-- | Runs a getter with potentially missing runtime context.
tryGetter :: ConfigData -> Maybe b -> a -> FieldGetter a b -> Maybe ResultEntry
tryGetter _    _ item (FieldSimple getter)  = Just $ getter item
tryGetter cfg  _ item (FieldConfig getter)  = Just $ getter cfg item
tryGetter _   rt item (FieldRuntime getter) =
  maybe Nothing (\rt' -> Just $ getter rt' item) rt
tryGetter cfg rt item (FieldConfigRuntime getter) =
  maybe Nothing (\rt' -> Just $ getter cfg rt' item) rt
tryGetter _   _ _    FieldUnknown = Just $ ResultEntry RSUnknown Nothing

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
makeSimpleFilter :: String -> [Either String Integer] -> Filter FilterField
makeSimpleFilter _ [] = EmptyFilter
makeSimpleFilter namefield vals =
  OrFilter $ map (EQFilter namefield . either QuotedString NumericValue) vals

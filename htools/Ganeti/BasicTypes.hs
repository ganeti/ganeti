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

module Ganeti.BasicTypes
  ( Result(..)
  , isOk
  , isBad
  , eitherToResult
  , annotateResult
  , annotateIOError
  , select
  , LookupResult(..)
  , MatchPriority(..)
  , lookupName
  , goodLookupResult
  , goodMatchPriority
  , prefixMatch
  , compareNameComponent
  ) where

import Control.Applicative
import Control.Monad
import Data.Function
import Data.List

-- | This is similar to the JSON library Result type - /very/ similar,
-- but we want to use it in multiple places, so we abstract it into a
-- mini-library here.
--
-- The failure value for this monad is simply a string.
data Result a
    = Bad String
    | Ok a
    deriving (Show, Read, Eq)

instance Monad Result where
  (>>=) (Bad x) _ = Bad x
  (>>=) (Ok x) fn = fn x
  return = Ok
  fail = Bad

instance Functor Result where
  fmap _ (Bad msg) = Bad msg
  fmap fn (Ok val) = Ok (fn val)

instance MonadPlus Result where
  mzero = Bad "zero Result when used as MonadPlus"
  -- for mplus, when we 'add' two Bad values, we concatenate their
  -- error descriptions
  (Bad x) `mplus` (Bad y) = Bad (x ++ "; " ++ y)
  (Bad _) `mplus` x = x
  x@(Ok _) `mplus` _ = x

instance Applicative Result where
  pure = Ok
  (Bad f) <*> _       = Bad f
  _       <*> (Bad x) = Bad x
  (Ok f)  <*> (Ok x)  = Ok $ f x

-- | Simple checker for whether a 'Result' is OK.
isOk :: Result a -> Bool
isOk (Ok _) = True
isOk _ = False

-- | Simple checker for whether a 'Result' is a failure.
isBad :: Result a  -> Bool
isBad = not . isOk

-- | Converter from Either String to 'Result'.
eitherToResult :: Either String a -> Result a
eitherToResult (Left s) = Bad s
eitherToResult (Right v) = Ok v

-- | Annotate a Result with an ownership information.
annotateResult :: String -> Result a -> Result a
annotateResult owner (Bad s) = Bad $ owner ++ ": " ++ s
annotateResult _ v = v

-- | Annotates and transforms IOErrors into a Result type. This can be
-- used in the error handler argument to 'catch', for example.
annotateIOError :: String -> IOError -> IO (Result a)
annotateIOError description exc =
  return . Bad $ description ++ ": " ++ show exc

-- * Misc functionality

-- | Return the first result with a True condition, or the default otherwise.
select :: a            -- ^ default result
       -> [(Bool, a)]  -- ^ list of \"condition, result\"
       -> a            -- ^ first result which has a True condition, or default
select def = maybe def snd . find fst

-- * Lookup of partial names functionality

-- | The priority of a match in a lookup result.
data MatchPriority = ExactMatch
                   | MultipleMatch
                   | PartialMatch
                   | FailMatch
                   deriving (Show, Read, Enum, Eq, Ord)

-- | The result of a name lookup in a list.
data LookupResult = LookupResult
  { lrMatchPriority :: MatchPriority -- ^ The result type
  -- | Matching value (for ExactMatch, PartialMatch), Lookup string otherwise
  , lrContent :: String
  } deriving (Show, Read)

-- | Lookup results have an absolute preference ordering.
instance Eq LookupResult where
  (==) = (==) `on` lrMatchPriority

instance Ord LookupResult where
  compare = compare `on` lrMatchPriority

-- | Check for prefix matches in names.
-- Implemented in Ganeti core utils.text.MatchNameComponent
-- as the regexp r"^%s(\..*)?$" % re.escape(key)
prefixMatch :: String  -- ^ Lookup
            -> String  -- ^ Full name
            -> Bool    -- ^ Whether there is a prefix match
prefixMatch = isPrefixOf . (++ ".")

-- | Is the lookup priority a "good" one?
goodMatchPriority :: MatchPriority -> Bool
goodMatchPriority ExactMatch = True
goodMatchPriority PartialMatch = True
goodMatchPriority _ = False

-- | Is the lookup result an actual match?
goodLookupResult :: LookupResult -> Bool
goodLookupResult = goodMatchPriority . lrMatchPriority

-- | Compares a canonical name and a lookup string.
compareNameComponent :: String        -- ^ Canonical (target) name
                     -> String        -- ^ Partial (lookup) name
                     -> LookupResult  -- ^ Result of the lookup
compareNameComponent cnl lkp =
  select (LookupResult FailMatch lkp)
  [ (cnl == lkp          , LookupResult ExactMatch cnl)
  , (prefixMatch lkp cnl , LookupResult PartialMatch cnl)
  ]

-- | Lookup a string and choose the best result.
chooseLookupResult :: String       -- ^ Lookup key
                   -> String       -- ^ String to compare to the lookup key
                   -> LookupResult -- ^ Previous result
                   -> LookupResult -- ^ New result
chooseLookupResult lkp cstr old =
  -- default: use class order to pick the minimum result
  select (min new old)
  -- special cases:
  -- short circuit if the new result is an exact match
  [ (lrMatchPriority new == ExactMatch, new)
  -- if both are partial matches generate a multiple match
  , (partial2, LookupResult MultipleMatch lkp)
  ] where new = compareNameComponent cstr lkp
          partial2 = all ((PartialMatch==) . lrMatchPriority) [old, new]

-- | Find the canonical name for a lookup string in a list of names.
lookupName :: [String]      -- ^ List of keys
           -> String        -- ^ Lookup string
           -> LookupResult  -- ^ Result of the lookup
lookupName l s = foldr (chooseLookupResult s)
                       (LookupResult FailMatch s) l

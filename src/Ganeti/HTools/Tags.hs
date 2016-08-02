{-| Tags

This module holds all the tag interpretation done by htools.

-}

{-

Copyright (C) 2014, 2015 Google Inc.
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

module Ganeti.HTools.Tags
  ( hasStandbyTag
  , getMigRestrictions
  , getRecvMigRestrictions
  , getLocations
  , getBandwidth
  , getBandwidthGraph
  , mergeByPrefixes
  ) where

import Control.Monad ((>=>))
import Data.List (isPrefixOf, isInfixOf, stripPrefix)
import Data.Maybe (mapMaybe)
import qualified Data.Set as S

import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Tags.Constants ( standbyPrefix
                                    , migrationPrefix, allowMigrationPrefix
                                    , locationPrefix, bandwidthPrefix )

-- * Predicates

-- | Predicate of having a standby tag.
hasStandbyTag :: Node.Node -> Bool
hasStandbyTag = any (standbyPrefix `isPrefixOf`) . Node.nTags

-- * Utility functions

-- | Htools standard tag extraction. Given a set of cluster tags,
-- take those starting with a specific prefix, strip the prefix
-- and append a colon, and then take those node tags starting with
-- one of those strings.
getTags :: String -> [String] -> [String] -> S.Set String
getTags prefix ctags ntags = S.fromList
  (mapMaybe (stripPrefix prefix) ctags >>= \ p ->
    filter ((p ++ ":") `isPrefixOf`) ntags)

-- * Migration restriction tags

-- | Given the cluster tags extract the migration restrictions
-- from a node tag.
getMigRestrictions :: [String] -> [String] -> S.Set String
getMigRestrictions = getTags migrationPrefix

-- | Maybe split a string on the first single occurence of "::" return
-- the parts before and after.
splitAtColons :: String -> Maybe (String, String)

splitAtColons (':':':':xs) = return ("", xs)

splitAtColons (x:xs) = do
  (as, bs) <- splitAtColons xs
  return (x:as, bs)

splitAtColons _ = Nothing

-- | Get the pairs of allowed migrations from a set of cluster tags.
migrations :: [String] -> [(String, String)]
migrations = mapMaybe $ stripPrefix allowMigrationPrefix >=> migrationPair
  where migrationPair s = case splitAtColons s of
                            Just (src, dst) -> if "::" `isInfixOf` dst
                                               then Nothing
                                               else Just (src, dst)
                            Nothing -> Nothing

-- | Given the cluster tags, extract the set of migration restrictions
-- a node is able to receive from its node tags.
getRecvMigRestrictions :: [String] -> [String] -> S.Set String
getRecvMigRestrictions ctags ntags =
  let migs = migrations ctags
      closure tag = (:) tag . map fst $ filter ((==) tag . snd) migs
  in S.fromList $ S.elems (getMigRestrictions ctags ntags) >>= closure

-- * Location tags

-- | Given the cluster tags, extract the node location tags
-- from the node tags.
getLocations :: [String] -> [String] -> S.Set String
getLocations = getTags locationPrefix

-- | Given the cluster tags extract the network bandwidth
-- from a node tag.
getBandwidth :: [String] -> [String] -> S.Set String
getBandwidth = getTags bandwidthPrefix

-- | Split given string on the  all "::" occurences
splitAtColonsList :: String -> [String]
splitAtColonsList str =
  case splitAtColons str of
    Just (f, s) -> f : splitAtColonsList s
    Nothing -> [str]

-- | Try to parse string into value
maybeRead :: Read a => String -> Maybe a
maybeRead s = case reads s of
                [(x,"")] -> Just x
                _        -> Nothing

-- | Extract bandwidth graph from cluster tags
getBandwidthGraph :: [String] -> [(String, String, Int)]
getBandwidthGraph ctags =
  let unprefTags = mapMaybe (stripPrefix bandwidthPrefix) ctags
      tupleList = mapMaybe (listToTuple . splitAtColonsList) unprefTags
  in mapMaybe parseInt tupleList
  where parseInt (a, b, s) = case maybeRead s :: Maybe Int of
          Just i -> Just (a, b, i)
          Nothing -> Nothing
        listToTuple (a:b:c:[]) = Just (a, b, c)
        listToTuple _ = Nothing

-- | Maybe extract string after first occurence of ":" return
stripFirstPrefix :: String -> Maybe String
stripFirstPrefix (':':':':_) = Nothing
stripFirstPrefix (':':_) = Just ""
stripFirstPrefix (x:xs) =
  case stripFirstPrefix xs of
    Just pref -> Just (x:pref)
    Nothing -> Nothing
stripFirstPrefix _ = Nothing

-- | Drop all victims having same prefixes from inherits, unite sets
mergeByPrefixes :: S.Set String -> S.Set String -> S.Set String
mergeByPrefixes victims inherits =
  let prefixes = mapMaybe stripFirstPrefix (S.toList inherits)
      prefixFilter s = not $ any (`isPrefixOf` s) prefixes
      filtered = S.filter prefixFilter victims
  in S.union inherits filtered

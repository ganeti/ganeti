{-# LANGUAGE TemplateHaskell #-}

{-| Some common Ganeti types.

This holds types common to both core work, and to htools. Types that
are very core specific (e.g. configuration objects) should go in
'Ganeti.Objects', while types that are specific to htools in-memory
representation should go into 'Ganeti.HTools.Types'.

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

module Ganeti.Types
  ( AllocPolicy(..)
  , allocPolicyFromRaw
  , allocPolicyToRaw
  , InstanceStatus(..)
  , instanceStatusFromRaw
  , instanceStatusToRaw
  , DiskTemplate(..)
  , diskTemplateToRaw
  , diskTemplateFromRaw
  , NonNegative
  , fromNonNegative
  , mkNonNegative
  , Positive
  , fromPositive
  , mkPositive
  , NonEmpty
  , fromNonEmpty
  , mkNonEmpty
  ) where

import qualified Text.JSON as JSON

import qualified Ganeti.Constants as C
import qualified Ganeti.THH as THH

-- * Generic types

-- | Type that holds a non-negative value.
newtype NonNegative a = NonNegative { fromNonNegative :: a }
  deriving (Show, Read, Eq)

-- | Smart constructor for 'NonNegative'.
mkNonNegative :: (Monad m, Num a, Ord a, Show a) => a -> m (NonNegative a)
mkNonNegative i | i >= 0 = return (NonNegative i)
                | otherwise = fail $ "Invalid value for non-negative type '" ++
                              show i ++ "'"

instance (JSON.JSON a, Num a, Ord a, Show a) => JSON.JSON (NonNegative a) where
  showJSON = JSON.showJSON . fromNonNegative
  readJSON v = JSON.readJSON v >>= mkNonNegative

-- | Type that holds a positive value.
newtype Positive a = Positive { fromPositive :: a }
  deriving (Show, Read, Eq)

-- | Smart constructor for 'Positive'.
mkPositive :: (Monad m, Num a, Ord a, Show a) => a -> m (Positive a)
mkPositive i | i > 0 = return (Positive i)
             | otherwise = fail $ "Invalid value for positive type '" ++
                           show i ++ "'"

instance (JSON.JSON a, Num a, Ord a, Show a) => JSON.JSON (Positive a) where
  showJSON = JSON.showJSON . fromPositive
  readJSON v = JSON.readJSON v >>= mkPositive

-- | Type that holds a non-null list.
newtype NonEmpty a = NonEmpty { fromNonEmpty :: [a] }
  deriving (Show, Read, Eq)

-- | Smart constructor for 'NonEmpty'.
mkNonEmpty :: (Monad m) => [a] -> m (NonEmpty a)
mkNonEmpty [] = fail "Received empty value for non-empty list"
mkNonEmpty xs = return (NonEmpty xs)

instance (JSON.JSON a) => JSON.JSON (NonEmpty a) where
  showJSON = JSON.showJSON . fromNonEmpty
  readJSON v = JSON.readJSON v >>= mkNonEmpty

-- * Ganeti types

-- | Instance disk template type.
$(THH.declareSADT "DiskTemplate"
       [ ("DTDiskless",   'C.dtDiskless)
       , ("DTFile",       'C.dtFile)
       , ("DTSharedFile", 'C.dtSharedFile)
       , ("DTPlain",      'C.dtPlain)
       , ("DTBlock",      'C.dtBlock)
       , ("DTDrbd8",      'C.dtDrbd8)
       , ("DTRbd",        'C.dtRbd)
       ])
$(THH.makeJSONInstance ''DiskTemplate)

-- | The Group allocation policy type.
--
-- Note that the order of constructors is important as the automatic
-- Ord instance will order them in the order they are defined, so when
-- changing this data type be careful about the interaction with the
-- desired sorting order.
$(THH.declareSADT "AllocPolicy"
       [ ("AllocPreferred",   'C.allocPolicyPreferred)
       , ("AllocLastResort",  'C.allocPolicyLastResort)
       , ("AllocUnallocable", 'C.allocPolicyUnallocable)
       ])
$(THH.makeJSONInstance ''AllocPolicy)

-- | The Instance real state type. FIXME: this could be improved to
-- just wrap a /NormalState AdminStatus | ErrorState ErrorCondition/.
$(THH.declareSADT "InstanceStatus"
       [ ("StatusDown",    'C.inststAdmindown)
       , ("StatusOffline", 'C.inststAdminoffline)
       , ("ErrorDown",     'C.inststErrordown)
       , ("ErrorUp",       'C.inststErrorup)
       , ("NodeDown",      'C.inststNodedown)
       , ("NodeOffline",   'C.inststNodeoffline)
       , ("Running",       'C.inststRunning)
       , ("WrongNode",     'C.inststWrongnode)
       ])
$(THH.makeJSONInstance ''InstanceStatus)

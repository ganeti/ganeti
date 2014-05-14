{-# LANGUAGE TemplateHaskell, RankNTypes, FlexibleContexts #-}

{-| Pure functions for manipulating reservations of temporary objects

-}

{-

Copyright (C) 2014 Google Inc.

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

module Ganeti.WConfd.TempRes
  ( TempResState(..)
  , emptyTempResState
  , NodeUUID
  , InstanceUUID
  , DRBDMinor
  , DRBDMap
  , trsDRBDL
  , computeDRBDMap
  , computeDRBDMap'
  , allocateDRBDMinor
  , releaseDRBDMinors
  ) where

import Control.Lens.At
import Control.Monad.Error
import Control.Monad.State
import qualified Data.Foldable as F
import Data.Maybe
import Data.Map (Map)
import qualified Data.Map as M
import Data.Monoid
import qualified Data.Set as S

import Ganeti.BasicTypes
import Ganeti.Config
import Ganeti.Errors
import qualified Ganeti.JSON as J
import Ganeti.Lens
import Ganeti.Objects
import Ganeti.Utils

-- * The main reservation state

-- ** Aliases to make types more meaningful:

type NodeUUID = String

type InstanceUUID = String

type DRBDMinor = Int

-- | A map of the usage of DRBD minors
type DRBDMap = Map NodeUUID (Map DRBDMinor InstanceUUID)

-- | A map of the usage of DRBD minors with possible duplicates
type DRBDMap' = Map NodeUUID (Map DRBDMinor [InstanceUUID])

-- * The state data structure

-- | The state of the temporary reservations
data TempResState = TempResState
  { trsDRBD :: DRBDMap
  }
  deriving (Eq, Show)

emptyTempResState :: TempResState
emptyTempResState = TempResState M.empty

$(makeCustomLenses ''TempResState)

-- ** Utility functions

-- | Filter values from the nested map and remove any nested maps
-- that become empty.
filterNested :: (Ord a, Ord b)
             => (c -> Bool) -> Map a (Map b c) -> Map a (Map b c)
filterNested p = M.filter (not . M.null) . fmap (M.filter p)

-- * DRBDs

-- | Converts a lens that works on maybe values into a lens that works
-- on regular ones. A missing value on the input is replaced by
-- 'mempty'.
-- The output is is @Just something@ iff @something /= mempty@.
maybeLens :: (Monoid a, Monoid b, Eq b)
          => Lens s t (Maybe a) (Maybe b) -> Lens s t a b
maybeLens l f = l (fmap (mfilter (/= mempty) . Just) . f . fromMaybe mempty)

-- * DRBD functions

-- | Compute the map of used DRBD minor/nodes, including possible
-- duplicates.
-- An error is returned if the configuration isn't consistent
-- (for example if a referenced disk is missing etc.).
computeDRBDMap' :: (MonadError GanetiException m)
                => ConfigData -> TempResState -> m DRBDMap'
computeDRBDMap' cfg trs =
    flip execStateT (fmap (fmap (: [])) (trsDRBD trs))
    $ F.forM_ (configInstances cfg) addDisks
  where
    -- | Creates a lens for modifying the list of instances
    nodeMinor :: NodeUUID -> DRBDMinor -> Lens' DRBDMap' [InstanceUUID]
    nodeMinor node minor = maybeLens (at node) . maybeLens (at minor)
    -- | Adds disks of an instance within the state monad
    addDisks inst = do
                      disks <- toError $ getDrbdMinorsForInstance cfg inst
                      forM_ disks $ \(minor, node) -> nodeMinor node minor
                                                          %= (uuidOf inst :)

-- | Compute the map of used DRBD minor/nodes.
-- Report any duplicate entries as an error.
--
-- Unlike 'computeDRBDMap'', includes entries for all nodes, even if empty.
computeDRBDMap :: (MonadError GanetiException m)
               => ConfigData -> TempResState -> m DRBDMap
computeDRBDMap cfg trs = do
  m <- computeDRBDMap' cfg trs
  let dups = filterNested ((>= 2) . length) m
  unless (M.null dups) . failError
    $ "Duplicate DRBD ports detected: " ++ show (M.toList $ fmap M.toList dups)
  return $ fmap (fmap head . M.filter ((== 1) . length)) m
           `M.union` (fmap (const mempty) . J.fromContainer . configNodes $ cfg)

-- Allocate a drbd minor.
--
-- The free minor will be automatically computed from the existing devices.
-- A node can be given multiple times in order to allocate multiple minors.
-- The result is the list of minors, in the same order as the passed nodes.
allocateDRBDMinor :: (MonadError GanetiException m, MonadState TempResState m)
                  => ConfigData -> InstanceUUID -> [NodeUUID]
                  -> m [DRBDMinor]
allocateDRBDMinor cfg inst nodes = do
  dMap <- computeDRBDMap' cfg =<< get
  let usedMap = fmap M.keysSet dMap
  let alloc :: S.Set DRBDMinor -> Map DRBDMinor InstanceUUID
            -> (DRBDMinor, Map DRBDMinor InstanceUUID)
      alloc used m = let k = findFirst 0 (M.keysSet m `S.union` used)
                      in (k, M.insert k inst m)
  forM nodes $ \node -> trsDRBDL . maybeLens (at node)
                        %%= alloc (M.findWithDefault mempty node usedMap)

-- Release temporary drbd minors allocated for a given instance using
-- 'allocateDRBDMinor'.
releaseDRBDMinors :: (MonadState TempResState m) => InstanceUUID -> m ()
releaseDRBDMinors inst = trsDRBDL %= filterNested (/= inst)

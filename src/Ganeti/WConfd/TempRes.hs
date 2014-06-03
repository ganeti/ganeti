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
  , NetworkUUID
  , DRBDMinor
  , DRBDMap
  , trsDRBDL
  , computeDRBDMap
  , computeDRBDMap'
  , allocateDRBDMinor
  , releaseDRBDMinors
  , MAC
  , generateMAC
  , reserveMAC
  , generateDRBDSecret
  , reserveLV
  , dropAllReservations
  , isReserved
  , reserve
  , dropReservationsFor
  , reserved
  , generate
  ) where

import Control.Applicative
import Control.Lens.At
import Control.Monad.Error
import Control.Monad.State
import Control.Monad.Trans.Maybe
import qualified Data.Foldable as F
import Data.Maybe
import Data.Map (Map)
import qualified Data.Map as M
import Data.Monoid
import qualified Data.Set as S
import System.Random

import Ganeti.BasicTypes
import Ganeti.Config
import qualified Ganeti.Constants as C
import Ganeti.Errors
import qualified Ganeti.JSON as J
import Ganeti.Lens
import Ganeti.Locking.Locks (ClientId)
import Ganeti.Objects
import Ganeti.Utils
import Ganeti.Utils.MonadPlus
import Ganeti.Utils.Random
import qualified Ganeti.Utils.MultiMap as MM

-- * The main reservation state

-- ** Aliases to make types more meaningful:

type NodeUUID = String

type InstanceUUID = String

type NetworkUUID = String

type DRBDMinor = Int

-- | A map of the usage of DRBD minors
type DRBDMap = Map NodeUUID (Map DRBDMinor InstanceUUID)

-- | A map of the usage of DRBD minors with possible duplicates
type DRBDMap' = Map NodeUUID (Map DRBDMinor [InstanceUUID])

-- * The state data structure

-- | A polymorphic data structure for managing temporary resources assigned
-- to jobs.
newtype TempRes j a = TempRes { getTempRes :: MM.MultiMap j a }
  deriving (Eq, Ord, Show)

instance (Ord j, Ord a) => Monoid (TempRes j a) where
  mempty = TempRes mempty
  mappend (TempRes x) (TempRes y) = TempRes $ x <> y

-- | The state of the temporary reservations
data TempResState = TempResState
  { trsDRBD :: DRBDMap
  , trsMACs :: TempRes ClientId MAC
  , trsDRBDSecrets :: TempRes ClientId DRBDSecret
  , trsLVs :: TempRes ClientId LogicalVolume
  }
  deriving (Eq, Show)

emptyTempResState :: TempResState
emptyTempResState = TempResState M.empty mempty mempty mempty

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

-- * Other temporary resources

-- | Tests if a given value is reserved for a given job.
isReserved :: (Ord a, Ord j) => a -> TempRes j a -> Bool
isReserved x = MM.elem x . getTempRes

-- | Tries to reserve a given value for a given job.
reserve :: (MonadError e m, Error e, Show a, Ord a, Ord j)
        => j -> a -> TempRes j a -> m (TempRes j a)
reserve jobid x tr = do
  when (isReserved x tr) . failError $ "Duplicate reservation for resource '"
                                       ++ show x ++ "'"
  return . TempRes . MM.insert jobid x $ getTempRes tr

dropReservationsFor :: (Ord a, Ord j) => j -> TempRes j a -> TempRes j a
dropReservationsFor jobid = TempRes . MM.deleteAll jobid . getTempRes

reserved :: (Ord a, Ord j) => TempRes j a -> S.Set a
reserved = MM.values . getTempRes

generate :: (MonadError e m, Error e, Show a, Ord a, Ord j)
         => j -> S.Set a -> m (Maybe a) -> TempRes j a -> m (a, TempRes j a)
generate jobid existing genfn tr = do
  let retries = 64
  let vals = reserved tr `S.union` existing
  xOpt <- retryMaybeN retries
                      (\_ -> mfilter (`S.notMember` vals) (MaybeT genfn))
  case xOpt of
    Nothing -> failError "Not able generate new resource"
                         -- TODO: (last tried: " ++ %s)" % new_resource
    Just x  -> (,) x `liftM` reserve jobid x tr

-- | A variant of 'generate' for randomized computations.
generateRand :: (MonadError e m, Error e, Show a, Ord a, Ord j, RandomGen g)
             => g -> j -> S.Set a -> (g -> (Maybe a, g)) -> TempRes j a
             -> m (a, TempRes j a)
generateRand rgen jobid existing genfn tr =
  evalStateT (generate jobid existing (state genfn) tr) rgen

-- ** Functions common to all reservations

-- | Removes all resources reserved by a given job.
--
-- If a new reservation resource type is added, it must be added here as well.
dropAllReservations :: ClientId -> TempResState -> TempResState
dropAllReservations jobId =
    (trsMACsL %~ dropReservationsFor jobId)
  . (trsDRBDSecretsL %~ dropReservationsFor jobId)
  . (trsLVsL %~ dropReservationsFor jobId)

-- ** IDs

-- ** MAC addresses

-- Randomly generate a MAC for an instance.
-- Checks that the generated MAC isn't used by another instance.
--
-- Note that we only consume, but not return the state of a random number
-- generator. This is because the whole operation needs to be pure (for atomic
-- 'IORef' updates) and therefore we can't use 'getStdRandom'. Therefore the
-- approach we take is to instead use 'newStdGen' and discard the split
-- generator afterwards.
generateMAC
  :: (RandomGen g, MonadError e m, Error e, Functor m)
  => g -> ClientId -> Maybe NetworkUUID -> ConfigData
  -> StateT TempResState m MAC
generateMAC rgen jobId netId cd = do
  net <- case netId of
    Just n -> Just <$> J.lookupContainer (failError $ "Network '" ++ show netId
                                             ++ "' not found")
                                         n (configNetworks cd)
    Nothing -> return Nothing
  let prefix = fromMaybe (clusterMacPrefix . configCluster $ cd)
                         (networkMacPrefix =<< net)
  let existing = S.fromList $ getAllMACs cd
  StateT
    $ traverseOf2 trsMACsL
        (generateRand rgen jobId existing
                      (over _1 Just . generateOneMAC prefix))

-- Reserves a MAC for an instance in the list of temporary reservations.
reserveMAC
  :: (MonadError GanetiException m, MonadState TempResState m, Functor m)
  => ClientId -> MAC -> ConfigData -> m ()
reserveMAC jobId mac cd = do
  let existing = S.fromList $ getAllMACs cd
  when (S.member mac existing)
    $ throwError (ReservationError "MAC already in use")
  get >>= traverseOf trsMACsL (reserve jobId mac) >>= put

-- ** DRBD secrets

generateDRBDSecret
  :: (RandomGen g, MonadError e m, Error e, Functor m)
  => g -> ClientId -> ConfigData -> StateT TempResState m DRBDSecret
generateDRBDSecret rgen jobId cd = do
  let existing = S.fromList $ getAllDrbdSecrets cd
  StateT $ traverseOf2 trsDRBDSecretsL
           (generateRand rgen jobId existing
                         (over _1 Just . generateSecret C.drbdSecretLength))

-- ** LVs

reserveLV
  :: (MonadError GanetiException m, MonadState TempResState m, Functor m)
  => ClientId -> LogicalVolume -> ConfigData -> m ()
reserveLV jobId lv cd = do
  existing <- toError $ getAllLVs cd
  when (S.member lv existing)
    $ throwError (ReservationError "MAC already in use")
  get >>= traverseOf trsLVsL (reserve jobId lv) >>= put

{-# LANGUAGE TemplateHaskell, RankNTypes, FlexibleContexts #-}

{-| Pure functions for manipulating reservations of temporary objects

NOTE: Reservations aren't released specifically, they're just all
released at the end of a job. This could be improved in the future.

-}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.WConfd.TempRes
  ( TempRes
  , mkTempRes
  , TempResState(..)
  , emptyTempResState
  , NodeUUID
  , InstanceUUID
  , DiskUUID
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
  , IPv4ResAction(..)
  , IPv4Reservation(..)
  , reserveIp
  , releaseIp
  , generateIp
  , commitReleaseIp
  , commitReservedIps
  , listReservedIps
  , dropAllReservations
  , isReserved
  , reserve
  , dropReservationsFor
  , reserved
  ) where

import Control.Lens.At
import Control.Monad.Error
import Control.Monad.State
import Control.Monad.Trans.Maybe
import qualified Data.ByteString as BS
import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.Foldable as F
import Data.Maybe
import Data.Map (Map)
import qualified Data.Map as M
import Data.Monoid
import qualified Data.Semigroup as Sem
import qualified Data.Set as S
import System.Random
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Config
import qualified Ganeti.Constants as C
import Ganeti.Errors
import qualified Ganeti.JSON as J
import Ganeti.Lens
import qualified Ganeti.Network as N
import Ganeti.Locking.Locks (ClientId)
import Ganeti.Logging
import Ganeti.Objects
import Ganeti.THH
import Ganeti.Objects.Lens (configNetworksL)
import Ganeti.Utils
import Ganeti.Utils.Monad
import Ganeti.Utils.Random
import qualified Ganeti.Utils.MultiMap as MM

-- * The main reservation state

-- ** Aliases to make types more meaningful:

type NodeUUID = BS.ByteString

type InstanceUUID = BS.ByteString

type DiskUUID = BS.ByteString

type NetworkUUID = BS.ByteString

type DRBDMinor = Int

-- | A map of the usage of DRBD minors
type DRBDMap = Map NodeUUID (Map DRBDMinor DiskUUID)

-- | A map of the usage of DRBD minors with possible duplicates
type DRBDMap' = Map NodeUUID (Map DRBDMinor [DiskUUID])

-- * The state data structure

-- | Types of IPv4 reservation actions.
data IPv4ResAction = IPv4Reserve | IPv4Release
  deriving (Eq, Ord, Show, Bounded, Enum)

instance J.JSON IPv4ResAction where
  showJSON IPv4Reserve = J.JSString . J.toJSString $ C.reserveAction
  showJSON IPv4Release = J.JSString . J.toJSString $ C.releaseAction
  readJSON = J.readEitherString
             >=> \s -> case () of
                    _ | s == C.reserveAction -> return IPv4Reserve
                      | s == C.releaseAction -> return IPv4Release
                      | otherwise -> fail $ "Invalid IP reservation action: "
                                           ++ s

-- | The values stored in the IPv4 reservation table.
data IPv4Reservation = IPv4Res
  { ipv4ResAction :: IPv4ResAction
  , ipv4ResNetwork :: NetworkUUID
  , ipv4ResAddr :: Ip4Address
  } deriving (Eq, Ord, Show)

instance J.JSON IPv4Reservation where
  -- Notice that addr and net are in a different order, to be compatible
  -- with the original Python representation (while it's used).
  showJSON (IPv4Res a net addr) = J.showJSON (a, addr, net)
  readJSON = fmap (\(a, addr, net) -> IPv4Res a net addr) . J.readJSON

-- | A polymorphic data structure for managing temporary resources assigned
-- to jobs.
newtype TempRes j a = TempRes { getTempRes :: MM.MultiMap j a }
  deriving (Eq, Ord, Show)

instance (Ord j, Ord a) => Sem.Semigroup (TempRes j a) where
  (TempRes x) <> (TempRes y) = TempRes $ x <> y

instance (Ord j, Ord a) => Monoid (TempRes j a) where
  mempty = TempRes mempty
  mappend = (Sem.<>)

instance (J.JSON j, Ord j, J.JSON a, Ord a) => J.JSON (TempRes j a) where
  showJSON = J.showJSON . getTempRes
  readJSON = liftM TempRes . J.readJSON

-- | Create a temporary reservations from a given multi-map.
mkTempRes :: MM.MultiMap j a -> TempRes j a
mkTempRes = TempRes

-- | The state of the temporary reservations
$(buildObject "TempResState" "trs"
  [ simpleField "dRBD"             [t| DRBDMap |]
  , simpleField "mACs"             [t| TempRes ClientId MAC |]
  , simpleField "dRBDSecrets"      [t| TempRes ClientId DRBDSecret |]
  , simpleField "lVs"              [t| TempRes ClientId LogicalVolume |]
  , simpleField "iPv4s"            [t| TempRes ClientId IPv4Reservation |]
  ])

emptyTempResState :: TempResState
emptyTempResState = TempResState M.empty mempty mempty mempty mempty

$(makeCustomLenses ''TempResState)

-- ** Utility functions

-- | Issues a reservation error.
resError :: (MonadError GanetiException m) => String -> m a
resError = throwError . ReservationError

-- | Converts 'GenericError' into a 'ReservationError'.
toResError :: (MonadError GanetiException m) => m a -> m a
toResError = flip catchError (throwError . f)
  where
    f (GenericError msg) = ReservationError msg
    f e = e

-- | Filter values from the nested map and remove any nested maps
-- that become empty.
filterNested :: (Ord a, Ord b)
             => (c -> Bool) -> Map a (Map b c) -> Map a (Map b c)
filterNested p = M.filter (not . M.null) . fmap (M.filter p)

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
    $ F.forM_ (configDisks cfg) addMinors
  where
    -- | Creates a lens for modifying the list of instances
    nodeMinor :: NodeUUID -> DRBDMinor -> Lens' DRBDMap' [DiskUUID]
    nodeMinor node minor = maybeLens (at node) . maybeLens (at minor)
    -- | Adds minors of a disk within the state monad
    addMinors disk = do
      let minors = getDrbdMinorsForDisk disk
      forM_ minors $ \(minor, node) ->
        nodeMinor (UTF8.fromString node) minor %=
            (UTF8.fromString (uuidOf disk) :)

-- | Compute the map of used DRBD minor/nodes.
-- Report any duplicate entries as an error.
--
-- Unlike 'computeDRBDMap'', includes entries for all nodes, even if empty.
computeDRBDMap :: (MonadError GanetiException m)
               => ConfigData -> TempResState -> m DRBDMap
computeDRBDMap cfg trs = do
  m <- computeDRBDMap' cfg trs
  let dups = filterNested ((>= 2) . length) m
  unless (M.null dups) . resError
    $ "Duplicate DRBD ports detected: " ++ show (M.toList $ fmap M.toList dups)
  return $ fmap (fmap head . M.filter ((== 1) . length)) m
           `M.union` (fmap (const mempty) . J.fromContainer . configNodes $ cfg)

-- Allocate a drbd minor.
--
-- The free minor will be automatically computed from the existing devices.
-- A node can not be given multiple times.
-- The result is the list of minors, in the same order as the passed nodes.
allocateDRBDMinor :: (MonadError GanetiException m, MonadState TempResState m)
                  => ConfigData -> DiskUUID -> [NodeUUID]
                  -> m [DRBDMinor]
allocateDRBDMinor cfg disk nodes = do
  unless (nodes == ordNub nodes) . resError
    $ "Duplicate nodes detected in list '" ++ show nodes ++ "'"
  dMap <- computeDRBDMap' cfg =<< get
  let usedMap = fmap M.keysSet dMap
  let alloc :: S.Set DRBDMinor -> Map DRBDMinor DiskUUID
            -> (DRBDMinor, Map DRBDMinor DiskUUID)
      alloc used m = let k = findFirst 0 (M.keysSet m `S.union` used)
                     in (k, M.insert k disk m)
  forM nodes $ \node -> trsDRBDL . maybeLens (at node)
                        %%= alloc (M.findWithDefault mempty node usedMap)

-- Release temporary drbd minors allocated for a given disk using
-- 'allocateDRBDMinor'.
releaseDRBDMinors :: (MonadState TempResState m) => DiskUUID -> m ()
releaseDRBDMinors disk = trsDRBDL %= filterNested (/= disk)

-- * Other temporary resources

-- | Tests if a given value is reserved for a given job.
isReserved :: (Ord a, Ord j) => a -> TempRes j a -> Bool
isReserved x = MM.elem x . getTempRes

-- | Tries to reserve a given value for a given job.
reserve :: (MonadError GanetiException m, Show a, Ord a, Ord j)
        => j -> a -> TempRes j a -> m (TempRes j a)
reserve jobid x tr = do
  when (isReserved x tr) . resError $ "Duplicate reservation for resource '"
                                       ++ show x ++ "'"
  return . TempRes . MM.insert jobid x $ getTempRes tr

dropReservationsFor :: (Ord a, Ord j) => j -> TempRes j a -> TempRes j a
dropReservationsFor jobid = TempRes . MM.deleteAll jobid . getTempRes

reservedFor :: (Ord a, Ord j) => j -> TempRes j a -> S.Set a
reservedFor jobid = MM.lookup jobid . getTempRes

reserved :: (Ord a, Ord j) => TempRes j a -> S.Set a
reserved = MM.values . getTempRes

-- | Computes the set of all reserved resources and passes it to
-- the given function.
-- This allows it to avoid resources that are already in use.
withReserved :: (MonadError GanetiException m, Show a, Ord a, Ord j)
             => j -> (S.Set a -> m a) -> TempRes j a -> m (a, TempRes j a)
withReserved jobid genfn tr = do
  x <- genfn (reserved tr)
  (,) x `liftM` reserve jobid x tr

-- | Repeatedly tries to run a given monadic function until it succeeds
-- and the returned value is free to reserve.
-- If such a value is found, it's reserved and returned.
-- Otherwise fails with an error.
generate :: (MonadError GanetiException m, Show a, Ord a, Ord j)
         => j -> S.Set a -> m (Maybe a) -> TempRes j a -> m (a, TempRes j a)
generate jobid existing genfn = withReserved jobid f
  where
    retries = 64 :: Int
    f res = do
      let vals = res `S.union` existing
      xOpt <- retryMaybeN retries
                          (\_ -> mfilter (`S.notMember` vals) (MaybeT genfn))
      maybe (resError "Not able generate new resource")
                       -- TODO: (last tried: " ++ %s)" % new_resource
            return xOpt

-- | A variant of 'generate' for randomized computations.
generateRand
  :: (MonadError GanetiException m, Show a, Ord a, Ord j, RandomGen g)
  => g -> j -> S.Set a -> (g -> (Maybe a, g)) -> TempRes j a
  -> m (a, TempRes j a)
generateRand rgen jobid existing genfn tr =
  evalStateT (generate jobid existing (state genfn) tr) rgen

-- | Embeds a stateful computation in a stateful monad.
stateM :: (MonadState s m) => (s -> m (a, s)) -> m a
stateM f = get >>= f >>= \(x, s) -> liftM (const x) (put s)

-- | Embeds a state-modifying computation in a stateful monad.
modifyM :: (MonadState s m) => (s -> m s) -> m ()
modifyM f = get >>= f >>= put

-- ** Functions common to all reservations

-- | Removes all resources reserved by a given job.
--
-- If a new reservation resource type is added, it must be added here as well.
dropAllReservations :: ClientId -> State TempResState ()
dropAllReservations jobId = modify $
    (trsMACsL %~ dropReservationsFor jobId)
  . (trsDRBDSecretsL %~ dropReservationsFor jobId)
  . (trsLVsL %~ dropReservationsFor jobId)
  . (trsIPv4sL %~ dropReservationsFor jobId)

-- | Looks up a network by its UUID.
lookupNetwork :: (MonadError GanetiException m)
              => ConfigData -> NetworkUUID -> m Network
lookupNetwork cd netId =
  J.lookupContainer (resError $ "Network '" ++ show netId ++ "' not found")
                    netId (configNetworks cd)

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
  :: (RandomGen g, MonadError GanetiException m, Functor m)
  => g -> ClientId -> Maybe NetworkUUID -> ConfigData
  -> StateT TempResState m MAC
generateMAC rgen jobId netId cd = do
  net <- case netId of
    Just n -> Just <$> lookupNetwork cd n
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
    $ resError "MAC already in use"
  modifyM $ traverseOf trsMACsL (reserve jobId mac)

-- ** DRBD secrets

generateDRBDSecret
  :: (RandomGen g, MonadError GanetiException m, Functor m)
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
    $ resError "MAC already in use"
  modifyM $ traverseOf trsLVsL (reserve jobId lv)

-- ** IPv4 addresses

-- | Lists all IPv4 addresses reserved for a given network.
usedIPv4Addrs :: NetworkUUID -> S.Set IPv4Reservation -> S.Set Ip4Address
usedIPv4Addrs netuuid =
  S.map ipv4ResAddr . S.filter ((== netuuid) . ipv4ResNetwork)

-- | Reserve a given IPv4 address for use by an instance.
reserveIp
  :: (MonadError GanetiException m, MonadState TempResState m, Functor m)
  => ClientId -> NetworkUUID -> Ip4Address
  -> Bool -- ^ whether to check externally reserved IPs
  -> ConfigData -> m ()
reserveIp jobId netuuid addr checkExt cd = toResError $ do
    net <- lookupNetwork cd netuuid
    isres <- N.isReserved N.PoolInstances addr net
    when isres . resError $ "IP address already in use"
    when checkExt $ do
      isextres <- N.isReserved N.PoolExt addr net
      when isextres . resError $ "IP is externally reserved"
    let action = IPv4Res IPv4Reserve netuuid addr
    modifyM $ traverseOf trsIPv4sL (reserve jobId action)

-- | Give a specific IP address back to an IP pool.
-- The IP address is returned to the IP pool designated by network id
-- and marked as reserved.
releaseIp
  :: (MonadError GanetiException m, MonadState TempResState m, Functor m)
  => ClientId -> NetworkUUID -> Ip4Address -> m ()
releaseIp jobId netuuid addr =
  let action = IPv4Res { ipv4ResAction = IPv4Release
                       , ipv4ResNetwork = netuuid
                       , ipv4ResAddr = addr }
  in modifyM $ traverseOf trsIPv4sL (reserve jobId action)

-- Find a free IPv4 address for an instance and reserve it.
generateIp
  :: (MonadError GanetiException m, MonadState TempResState m, Functor m)
  => ClientId -> NetworkUUID -> ConfigData -> m Ip4Address
generateIp jobId netuuid cd = toResError $ do
    net <- lookupNetwork cd netuuid
    let f res = do
          let ips = usedIPv4Addrs netuuid res
          addr <- N.findFree (`S.notMember` ips) net
          maybe (resError "Cannot generate IP. Network is full")
                (return . IPv4Res IPv4Reserve netuuid) addr
    liftM ipv4ResAddr . stateM $ traverseOf2 trsIPv4sL (withReserved jobId f)

-- | Commit a reserved/released IP address to an IP pool.
-- The IP address is taken from the network's IP pool and marked as
-- reserved/free for instances.
commitIp
  :: (MonadError GanetiException m, Functor m)
  => IPv4Reservation -> ConfigData -> m ConfigData
commitIp (IPv4Res actType netuuid addr) cd = toResError $ do
    let call = case actType of
                IPv4Reserve -> N.reserve
                IPv4Release -> N.release
        f Nothing = resError $ "Network '" ++ show netuuid ++ "' not found"
        f (Just net) = Just `liftM` call N.PoolInstances addr net
    traverseOf (configNetworksL . J.alterContainerL netuuid) f cd

-- | Immediately release an IP address, without using the reservations pool.
commitReleaseIp
  :: (MonadError GanetiException m, Functor m)
  => NetworkUUID -> Ip4Address -> ConfigData -> m ConfigData
commitReleaseIp netuuid addr =
  commitIp (IPv4Res IPv4Release netuuid addr)

-- | Commit all reserved/released IP address to an IP pool.
-- The IP addresses are taken from the network's IP pool and marked as
-- reserved/free for instances.
--
-- Note that the reservations are kept, they are supposed to be cleaned
-- when a job finishes.
commitReservedIps
  :: (MonadError GanetiException m, Functor m, MonadLog m)
  => ClientId -> TempResState -> ConfigData -> m ConfigData
commitReservedIps jobId tr cd = do
  let res = reservedFor jobId (trsIPv4s tr)
  logDebug $ "Commiting reservations: " ++ show res
  F.foldrM commitIp cd res

listReservedIps :: ClientId -> TempResState -> S.Set IPv4Reservation
listReservedIps jobid = reservedFor jobid . trsIPv4s

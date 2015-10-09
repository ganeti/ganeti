{-# LANGUAGE RankNTypes #-}

{-| Implementation of the Ganeti network objects.

This is does not (yet) cover all methods that are provided in the
corresponding python implementation (network.py).

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.
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

module Ganeti.Network
  ( PoolPart(..)
  , netIpv4NumHosts
  , ip4BaseAddr
  , getReservedCount
  , getFreeCount
  , isFull
  , getMap
  , isReserved
  , reserve
  , release
  , findFree
  , allReservations
  , reservations
  , extReservations
  ) where

import Control.Monad
import Control.Monad.Error
import Control.Monad.State
import Data.Bits ((.&.))
import Data.Function (on)

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Lens
import Ganeti.Objects
import Ganeti.Objects.Lens
import qualified Ganeti.Objects.BitArray as BA

ip4BaseAddr :: Ip4Network -> Ip4Address
ip4BaseAddr net =
  let m = ip4netMask net
      mask = 2^(32 :: Integer) - 2^(32 - m)
  in ip4AddressFromNumber .  (.&.) mask . ip4AddressToNumber $ ip4netAddr net

ipv4NumHosts :: (Integral n) => n -> Integer
ipv4NumHosts mask = 2^(32 - mask)

ipv4NetworkMinNumHosts :: Integer
ipv4NetworkMinNumHosts = ipv4NumHosts C.ipv4NetworkMinSize

ipv4NetworkMaxNumHosts :: Integer
ipv4NetworkMaxNumHosts = ipv4NumHosts C.ipv4NetworkMaxSize

data PoolPart = PoolInstances | PoolExt

addressPoolIso :: Iso' AddressPool BA.BitArray
addressPoolIso = iso apReservations AddressPool

poolLens :: PoolPart -> Lens' Network (Maybe AddressPool)
poolLens PoolInstances = networkReservationsL
poolLens PoolExt = networkExtReservationsL

poolArrayLens :: PoolPart -> Lens' Network (Maybe BA.BitArray)
poolArrayLens part = poolLens part . mapping addressPoolIso

netIpv4NumHosts :: Network -> Integer
netIpv4NumHosts = ipv4NumHosts . ip4netMask . networkNetwork

-- | Creates a new bit array pool of the appropriate size
newPoolArray :: (MonadError e m, Error e) => Network -> m BA.BitArray
newPoolArray net = do
  let numhosts = netIpv4NumHosts net
  when (numhosts > ipv4NetworkMaxNumHosts) . failError $
    "A big network with " ++ show numhosts ++ " host(s) is currently"
    ++ " not supported, please specify at most a /"
    ++ show ipv4NetworkMaxNumHosts ++ " network"
  when (numhosts < ipv4NetworkMinNumHosts) . failError $
    "A network with only " ++ show numhosts ++ " host(s) is too small,"
    ++ " please specify at least a /"
    ++ show ipv4NetworkMinNumHosts ++ " network"
  return $ BA.zeroes (fromInteger numhosts)

-- | Creates a new bit array pool of the appropriate size
newPool :: (MonadError e m, Error e) => Network -> m AddressPool
newPool = liftM AddressPool . newPoolArray

-- | A helper function that creates a bit array pool, of it's missing.
orNewPool :: (MonadError e m, Error e)
          => Network -> Maybe AddressPool -> m AddressPool
orNewPool net = maybe (newPool net) return

withPool :: (MonadError e m, Error e)
         => PoolPart -> (Network -> BA.BitArray -> m (a, BA.BitArray))
         -> StateT Network m a
withPool part f = StateT $ \n -> mapMOf2 (poolLens part) (f' n) n
  where
    f' net = liftM (over _2 Just)
             . mapMOf2 addressPoolIso (f net)
             <=< orNewPool net

withPool_ :: (MonadError e m, Error e)
          => PoolPart -> (Network -> BA.BitArray -> m BA.BitArray)
          -> Network -> m Network
withPool_ part f = execStateT $ withPool part ((liftM ((,) ()) .) . f)

readPool :: PoolPart -> Network -> Maybe BA.BitArray
readPool = view . poolArrayLens

readPoolE :: (MonadError e m, Error e)
          => PoolPart -> Network -> m BA.BitArray
readPoolE part net =
  liftM apReservations $ orNewPool net ((view . poolLens) part net)

readAllE :: (MonadError e m, Error e)
         => Network -> m BA.BitArray
readAllE net = do
  let toRes = liftM apReservations . orNewPool net
  res <- toRes $ networkReservations net
  ext <- toRes $ networkExtReservations net
  return $ res BA.-|- ext

reservations :: Network -> Maybe BA.BitArray
reservations = readPool PoolInstances

extReservations :: Network -> Maybe BA.BitArray
extReservations = readPool PoolExt

-- | Get a bit vector of all reservations (internal and external) combined.
allReservations :: Network -> Maybe BA.BitArray
allReservations a = (BA.-|-) `liftM` reservations a `ap` extReservations a

-- | Get the count of reserved addresses.
getReservedCount :: Network -> Int
getReservedCount = maybe 0 BA.count1 . allReservations

-- | Get the count of free addresses.
getFreeCount :: Network -> Int
getFreeCount = maybe 0 BA.count0 . allReservations

-- | Check whether the network is full.
isFull :: Network -> Bool
isFull = (0 ==) . getFreeCount

-- | Return a textual representation of the network's occupation status.
getMap :: Network -> String
getMap = maybe "" (BA.asString '.' 'X') . allReservations

-- * Functions used for manipulating the reservations

-- | Returns an address index wrt a network.
-- Fails if the address isn't in the network range.
addrIndex :: (MonadError e m, Error e) => Ip4Address -> Network -> m Int
addrIndex addr net = do
  let n = networkNetwork net
      i = on (-) ip4AddressToNumber addr (ip4BaseAddr n)
  when ((i < 0) || (i >= ipv4NumHosts (ip4netMask n))) . failError
    $ "Address '" ++ show addr ++ "' not in the network '" ++ show net ++ "'"
  return $ fromInteger i

-- | Returns an address of a given index wrt a network.
-- Fails if the index isn't in the network range.
addrAt :: (MonadError e m, Error e) => Int -> Network -> m Ip4Address
addrAt i net | (i' < 0) || (i' >= ipv4NumHosts (ip4netMask n)) =
    failError $ "Requested index " ++ show i
                ++ " outside the range of network '" ++ show net ++ "'"
             | otherwise =
    return $ ip4AddressFromNumber (ip4AddressToNumber (ip4BaseAddr n) + i')
  where
    n = networkNetwork net
    i' = toInteger i

-- | Checks if a given address is reserved.
-- Fails if the address isn't in the network range.
isReserved :: (MonadError e m, Error e) =>
              PoolPart -> Ip4Address -> Network -> m Bool
isReserved part addr net =
  (BA.!) `liftM` readPoolE part net `ap` addrIndex addr net

-- | Marks an address as used.
reserve :: (MonadError e m, Error e) =>
           PoolPart -> Ip4Address -> Network -> m Network
reserve part addr =
    withPool_ part $ \net ba -> do
      idx <- addrIndex addr net
      let addrs = show addr
      when (ba BA.! idx) . failError $ case part of
        PoolExt -> "IP " ++ addrs ++ " is already externally reserved"
        PoolInstances -> "IP " ++ addrs ++ " is already used by an instance"
      BA.setAt idx True ba

-- | Marks an address as unused.
release :: (MonadError e m, Error e) =>
           PoolPart -> Ip4Address -> Network -> m Network
release part addr =
    withPool_ part $ \net ba -> do
      idx <- addrIndex addr net
      let addrs = show addr
      unless (ba BA.! idx) . failError $ case part of
        PoolExt -> "IP " ++ addrs ++ " is not externally reserved"
        PoolInstances -> "IP " ++ addrs ++ " is not used by an instance"
      BA.setAt idx False ba

-- | Get the first free address in the network
-- that satisfies a given predicate.
findFree :: (MonadError e m, Error e)
         => (Ip4Address -> Bool) -> Network -> m (Maybe Ip4Address)
findFree p net = readAllE net >>= BA.foldr f (return Nothing)
  where
    addrAtEither = addrAt :: Int -> Network -> Either String Ip4Address
    f False i _ | Right a <- addrAtEither i net, p a = return (Just a)
    f _ _ x = x

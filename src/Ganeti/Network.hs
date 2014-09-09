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
  ( AddressPool(..)
  , createAddressPool
  , bitStringToBitVector
  , allReservations
  , getReservedCount
  , getFreeCount
  , isFull
  , getMap
  , networkIsValid
  ) where

import qualified Data.Vector.Unboxed as V

import Ganeti.Objects

-- | An address pool, holding a network plus internal and external
-- reservations.
data AddressPool = AddressPool { network :: Network,
                                 reservations :: V.Vector Bool,
                                 extReservations :: V.Vector Bool }
                                 deriving (Show)

-- | Create an address pool from a network.
createAddressPool :: Network -> Maybe AddressPool
createAddressPool n
  | networkIsValid n =
      let res = maybeStr2BitVec $ networkReservations n
          ext_res = maybeStr2BitVec $ networkExtReservations n
      in  Just AddressPool { reservations = res
                           , extReservations = ext_res
                           , network = n }
  | otherwise = Nothing

-- | Checks the consistency of the network object. So far, only checks the
-- length of the reservation strings.
networkIsValid :: Network -> Bool
networkIsValid n =
  sameLength (networkReservations n) (networkExtReservations n)

-- | Checks if two maybe strings are both nothing or of equal length.
sameLength :: Maybe String -> Maybe String -> Bool
sameLength Nothing Nothing = True
sameLength (Just s1) (Just s2) = length s1 == length s2
sameLength _ _ = False

-- | Converts a maybe bit string to a bit vector. Returns an empty bit vector on
-- nothing.
maybeStr2BitVec :: Maybe String -> V.Vector Bool
maybeStr2BitVec (Just s) = bitStringToBitVector s
maybeStr2BitVec Nothing = V.fromList ([]::[Bool])

-- | Converts a string to a bit vector. The character '0' is interpreted
-- as 'False', all others as 'True'.
bitStringToBitVector :: String -> V.Vector Bool
bitStringToBitVector = V.fromList . map (/= '0')

-- | Get a bit vector of all reservations (internal and external) combined.
allReservations :: AddressPool -> V.Vector Bool
allReservations a = V.zipWith (||) (reservations a) (extReservations a)

-- | Get the count of reserved addresses.
getReservedCount :: AddressPool -> Int
getReservedCount = V.length . V.filter (== True) . allReservations

-- | Get the count of free addresses.
getFreeCount :: AddressPool -> Int
getFreeCount = V.length . V.filter (== False) . allReservations

-- | Check whether the network is full.
isFull :: AddressPool -> Bool
isFull = V.and . allReservations

-- | Return a textual representation of the network's occupation status.
getMap :: AddressPool -> String
getMap = V.toList . V.map mapPixel . allReservations
  where mapPixel c = if c then 'X' else '.'

{-| Implementation of the Ganeti network objects.

This is does not (yet) cover all methods that are provided in the
corresponding python implementation (network.py).

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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
networkIsValid n = sameLength (networkReservations n) (networkExtReservations n)

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


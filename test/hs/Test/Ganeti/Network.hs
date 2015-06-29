{-# LANGUAGE TemplateHaskell, TypeSynonymInstances, FlexibleInstances #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

module Test.Ganeti.Network
  ( testNetwork
  , genBitStringMaxLen
  ) where

import Data.Maybe (fromMaybe)

import Test.QuickCheck

import Ganeti.Network as Network
import Ganeti.Objects as Objects
import Ganeti.Objects.BitArray as BA

import Test.Ganeti.Objects ( genBitStringMaxLen )
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper

-- * Test cases

-- | Check that the address pool's properties are calculated correctly.
prop_addressPoolProperties :: Network -> Property
prop_addressPoolProperties a =
  conjoin
    [ counterexample
        ("Not all reservations are included in 'allReservations' of " ++
         "address pool:" ++ show a) (allReservationsSubsumesInternal a)
    , counterexample
        ("Not all external reservations are covered by 'allReservations' " ++
         "of address pool: " ++ show a)
        (allReservationsSubsumesExternal a)
    , counterexample
        ("The counts of free and reserved addresses do not add up for " ++
         "address pool: " ++ show a)
        (checkCounts a)
    , counterexample
        ("'isFull' wrongly classified the status of the address pool: " ++
         show a) (checkIsFull a)
    , counterexample
        ("Network map is inconsistent with reservations of address pool: " ++
         show a) (checkGetMap a)
    ]

-- | Checks for the subset relation on 'Maybe' values.
subsetMaybe :: Maybe BitArray -> Maybe BitArray -> Bool
subsetMaybe (Just x) (Just y) = subset x y
subsetMaybe x y = x == y -- only if they're both Nothing

-- | Check that all internally reserved ips are included in 'allReservations'.
allReservationsSubsumesInternal :: Network -> Bool
allReservationsSubsumesInternal a =
  reservations a `subsetMaybe` allReservations a

-- | Check that all externally reserved ips are included in 'allReservations'.
allReservationsSubsumesExternal :: Network -> Bool
allReservationsSubsumesExternal a =
  extReservations a `subsetMaybe` allReservations a

-- | Check that the counts of free and reserved ips add up.
checkCounts :: Network -> Property
checkCounts a =
  netIpv4NumHosts a ==? toInteger (getFreeCount a + getReservedCount a)

-- | Check that the detection of a full network works correctly.
checkIsFull :: Network -> Property
checkIsFull a =
  isFull a ==? maybe True (and . toList) (allReservations a)

-- | Check that the map representation of the network corresponds to the
-- network's reservations.
checkGetMap :: Network -> Property
checkGetMap a =
  fromMaybe BA.empty (allReservations a)
  ==? fromList (Prelude.map (== 'X') (getMap a))

testSuite "Network"
  [ 'prop_addressPoolProperties
  ]

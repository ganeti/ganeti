{-# LANGUAGE TemplateHaskell, TypeSynonymInstances, FlexibleInstances #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

module Test.Ganeti.Network
  ( testNetwork
  ) where

import Test.QuickCheck

import Control.Monad

import Ganeti.Network as Network
import Ganeti.Objects as Objects
import Ganeti.Types

import Test.Ganeti.Query.Language (genJSValue)
import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Data.Vector.Unboxed as V
import qualified Data.Set as S

-- * Generators and arbitrary instances

-- | Generate an arbitrary string consisting of '0' and '1' of the given length.
genBitString :: Int -> Gen String
genBitString len = vectorOf len (elements "01")

-- | Generate an arbitrary string consisting of '0' and '1' of the maximum given
-- length.
genBitStringMaxLen :: Int -> Gen String
genBitStringMaxLen maxLen = choose (0, maxLen) >>= genBitString

-- | Generates an arbitrary bit vector of the given length.
genBitVector :: Int -> Gen (V.Vector Bool)
genBitVector len = do
  boolList <- vector len::Gen [Bool]
  return $ V.fromList boolList

-- | Generates a network instance with bit vectors of the given lengths for
-- reservations and external reservations.
genValidNetwork :: Int -> Gen Objects.Network
genValidNetwork maxLenBitStr = do
  lenBitStr <- choose (0, maxLenBitStr)
  name <- genName >>= mkNonEmpty
  network_type <- genMaybe genNetworkType
  mac_prefix <- genMaybe genName
  family <- arbitrary
  net <- genName >>= mkNonEmpty
  net6 <- genMaybe genName
  gateway <- genMaybe genName
  gateway6 <- genMaybe genName
  size <- genMaybe genJSValue
  res <- liftM Just (genBitString lenBitStr)
  ext_res <- liftM Just (genBitString lenBitStr)
  let n = Network name network_type mac_prefix family net net6 gateway
          gateway6 size res ext_res 0 S.empty
  return n

-- | Generates an arbitrary network type.
genNetworkType :: Gen NetworkType
genNetworkType = elements [ PrivateNetwork, PublicNetwork ]

-- | Network instances are generated arbitrarily only with short bit strings to
-- not slow down the test execution too much.
instance Arbitrary Objects.Network where
  arbitrary = genValidNetwork 256

-- | Generates address pools. The size of the network is intentionally
-- decoupled from the size of the bit vectors, to avoid slowing down
-- the tests by generating unnecessary bit strings.
genAddressPool :: Int -> Gen AddressPool
genAddressPool maxLenBitVec = do
  net <- arbitrary
  lenBitVec <- choose (0, maxLenBitVec)
  res <- genBitVector lenBitVec
  ext_res <- genBitVector lenBitVec
  return AddressPool { network = net
                     , reservations = res
                     , extReservations = ext_res }

instance Arbitrary AddressPool where
  arbitrary = genAddressPool ((2::Int)^(8::Int))

-- * Test cases

-- | Check the mapping of bit strings to bit vectors
prop_bitStringToBitVector :: Property
prop_bitStringToBitVector =
  forAll (genBitStringMaxLen 256) $ \bs ->
  let bitList = V.toList $ Network.bitStringToBitVector bs
      bitCharList = Prelude.zip bitList bs
  in  Prelude.all checkBit bitCharList

-- | Check whether an element of a bit vector is consistent with an element
-- of a bit string (containing '0' and '1' characters).
checkBit :: (Bool, Char) -> Bool
checkBit (False, '0') = True
checkBit (True, '1') = True
checkBit _ = False

-- | Check creation of an address pool when a network is given.
prop_createAddressPool :: Objects.Network -> Property
prop_createAddressPool n =
  let valid = networkIsValid n
  in  case createAddressPool n of
        Just _ -> True ==? valid
        Nothing -> False ==? valid

-- | Check that the address pool's properties are calculated correctly.
prop_addressPoolProperties :: AddressPool -> Property
prop_addressPoolProperties a =
  conjoin
    [ printTestCase
        ("Not all reservations are included in 'allReservations' of " ++
         "address pool:" ++ show a) (allReservationsSubsumesInternal a)
    , printTestCase
        ("Not all external reservations are covered by 'allReservations' " ++
         "of address pool: " ++ show a)
        (allReservationsSubsumesExternal a)
    , printTestCase
        ("The counts of free and reserved addresses do not add up for " ++
         "address pool: " ++ show a)
        (checkCounts a)
    , printTestCase
        ("'isFull' wrongly classified the status of the address pool: " ++
         show a) (checkIsFull a)
    , printTestCase
        ("Network map is inconsistent with reservations of address pool: " ++
         show a) (checkGetMap a)
    ]

-- | Check that all internally reserved ips are included in 'allReservations'.
allReservationsSubsumesInternal :: AddressPool -> Bool
allReservationsSubsumesInternal a =
  bitVectorSubsumes (allReservations a) (reservations a)

-- | Check that all externally reserved ips are included in 'allReservations'.
allReservationsSubsumesExternal :: AddressPool -> Bool
allReservationsSubsumesExternal a =
  bitVectorSubsumes (allReservations a) (extReservations a)

-- | Checks if one bit vector subsumes the other one.
bitVectorSubsumes :: V.Vector Bool -> V.Vector Bool -> Bool
bitVectorSubsumes v1 v2 = V.and $
                          V.zipWith (\a b -> not b || a) v1 v2

-- | Check that the counts of free and reserved ips add up.
checkCounts :: AddressPool -> Bool
checkCounts a =
  let res = reservations a
  in  V.length res == getFreeCount a + getReservedCount a

-- | Check that the detection of a full network works correctly.
checkIsFull :: AddressPool -> Bool
checkIsFull a = isFull a == V.notElem False (allReservations a)

-- | Check that the map representation of the network corresponds to the
-- network's reservations.
checkGetMap :: AddressPool -> Bool
checkGetMap a =
  allReservations a == V.fromList (Prelude.map (== 'X') (getMap a))

testSuite "Network"
  [ 'prop_bitStringToBitVector
  , 'prop_createAddressPool
  , 'prop_addressPoolProperties
  ]


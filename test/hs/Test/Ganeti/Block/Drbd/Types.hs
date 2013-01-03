{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for the types representing DRBD status -}

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

module Test.Ganeti.Block.Drbd.Types (testBlock_Drbd_Types) where

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Text.JSON
import Text.Printf

import Ganeti.JSON

import Ganeti.Block.Drbd.Types

{-# ANN module "HLint: ignore Use camelCase" #-}
{-# ANN module "HLint: ignore Use string literal" #-}

-- * Arbitrary instances

$(genArbitrary ''ConnState)
$(genArbitrary ''Role)
$(genArbitrary ''DiskState)
$(genArbitrary ''SizeUnit)
$(genArbitrary ''TimeUnit)

-- | Natural numbers generator.
natural :: Gen Int
natural = choose (0, maxBound :: Int)

-- | Generator of percentages.
percent :: Gen Double
percent = choose (0 :: Double, 100 :: Double)

-- | Generator of write order flags.
wOrderFlag :: Gen Char
wOrderFlag = elements ['b', 'f', 'd', 'n']

-- | Property for testing the JSON serialization of a DeviceInfo.
prop_DeviceInfo :: Property
prop_DeviceInfo = do
  minor <- natural
  state <- arbitrary
  locRole <- arbitrary
  remRole <- arbitrary
  locState <- arbitrary
  remState <- arbitrary
  alg <- choose ('A','C')
  ns <- natural
  nr <- natural
  dw <- natural
  dr <- natural
  al <- natural
  bm <- natural
  lc <- natural
  pe <- natural
  ua <- natural
  ap <- natural
  ep <- genMaybe natural
  wo <- genMaybe wOrderFlag
  oos <- genMaybe natural
  inst <- genMaybe arbitrary
  let obtained =
          showJSON $
            DeviceInfo minor state (LocalRemote locRole remRole)
              (LocalRemote locState remState) alg "r----" perfInd
              Nothing
              Nothing
              Nothing
              inst
      perfInd =
        PerfIndicators ns nr dw dr al bm lc pe ua ap ep wo oos
      expected =
        makeObj
          [ ("minor", showJSON minor)
          , ("connectionState", showJSON state)
          , ("localRole", showJSON locRole)
          , ("remoteRole", showJSON remRole)
          , ("localState", showJSON locState)
          , ("remoteState", showJSON remState)
          , ("replicationProtocol", showJSON alg)
          , ("ioFlags", showJSON "r----")
          , ("perfIndicators", showJSON perfInd)
          , ("instance", maybe JSNull showJSON inst)
          ]
  obtained ==? expected

-- | Property for testing the JSON serialization of a PerfIndicators.
prop_PerfIndicators :: Property
prop_PerfIndicators = do
  ns <- natural
  nr <- natural
  dw <- natural
  dr <- natural
  al <- natural
  bm <- natural
  lc <- natural
  pe <- natural
  ua <- natural
  ap <- natural
  ep <- genMaybe natural
  wo <- genMaybe wOrderFlag
  oos <- genMaybe natural
  let expected =
        showJSON $
          PerfIndicators ns nr dw dr al bm lc pe ua ap ep wo oos
      obtained =
        optFieldsToObj
          [ Just ("networkSend", showJSON ns)
          , Just ("networkReceive", showJSON nr)
          , Just ("diskWrite", showJSON dw)
          , Just ("diskRead", showJSON dr)
          , Just ("activityLog", showJSON al)
          , Just ("bitMap", showJSON bm)
          , Just ("localCount", showJSON lc)
          , Just ("pending", showJSON pe)
          , Just ("unacknowledged", showJSON ua)
          , Just ("applicationPending", showJSON ap)
          , optionalJSField "epochs" ep
          , optionalJSField "writeOrder" wo
          , optionalJSField "outOfSync" oos
          ]
  obtained ==? expected

-- | Function for testing the JSON serialization of a SyncStatus.
prop_SyncStatus :: Property
prop_SyncStatus = do
  perc <- percent
  numer <- natural
  denom <- natural
  sizeU1 <- arbitrary
  h <- choose (0, 23)
  m <- choose (0, 59)
  s <- choose (0, 59)
  sp <- natural
  wa <- genMaybe natural
  sizeU2 <- arbitrary
  timeU <- arbitrary
  let obtained = showJSON $
        SyncStatus perc numer denom sizeU1 (Time h m s) sp wa sizeU2 timeU
      expected = optFieldsToObj
        [ Just ("percentage", showJSON perc)
        , Just ("progress", showJSON $ show numer ++ "/" ++ show denom)
        , Just ("progressUnit", showJSON sizeU1)
        , Just ("timeToFinish", showJSON
            (printf "%02d:%02d:%02d" h m s :: String))
        , Just ("speed", showJSON sp)
        , optionalJSField "want" wa
        , Just ("speedUnit", showJSON $ show sizeU2 ++ "/" ++ show timeU)
        ]
  obtained ==? expected

testSuite "Block/Drbd/Types"
          [ 'prop_DeviceInfo
          , 'prop_PerfIndicators
          , 'prop_SyncStatus
          ]

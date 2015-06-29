{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for the types representing DRBD status -}

{-

Copyright (C) 2012 Google Inc.
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

module Test.Ganeti.Storage.Drbd.Types (testBlock_Drbd_Types) where

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Text.JSON
import Text.Printf

import Ganeti.JSON

import Ganeti.Storage.Drbd.Types

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
prop_DeviceInfo = property $ do
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
  return $ obtained ==? expected

-- | Property for testing the JSON serialization of a PerfIndicators.
prop_PerfIndicators :: Property
prop_PerfIndicators = property $ do
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
  return $ obtained ==? expected

-- | Function for testing the JSON serialization of a SyncStatus.
prop_SyncStatus :: Property
prop_SyncStatus = property $ do
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
  return $ obtained ==? expected

testSuite "Block/Drbd/Types"
          [ 'prop_DeviceInfo
          , 'prop_PerfIndicators
          , 'prop_SyncStatus
          ]

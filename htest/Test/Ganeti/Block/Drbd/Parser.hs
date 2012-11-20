{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for Attoparsec support for unicode -}

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

module Test.Ganeti.Block.Drbd.Parser (testBlock_DRBDParser) where

import Test.HUnit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon (readPythonTestData)

import qualified Data.Attoparsec.Text as A
import Data.Text (pack)

import Ganeti.Block.Drbd.Parser (drbdStatusParser, commaIntParser)
import Ganeti.Block.Drbd.Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Function for testing whether a file is parsed correctly.
testFile :: String -> DRBDStatus -> Assertion
testFile fileName expectedContent = do
    fileContent <- readPythonTestData fileName
    case A.parseOnly drbdStatusParser $ pack fileContent of
        Left msg -> assertFailure $ "Parsing failed: " ++ msg
        Right obtained -> assertEqual fileName expectedContent obtained

-- | Test a DRBD 8.0 file with an empty line inside.
case_drbd80_emptyline :: Assertion
case_drbd80_emptyline = testFile "proc_drbd80-emptyline.txt" $
  DRBDStatus
    ( VersionInfo Nothing Nothing Nothing Nothing
        (Just "5c9f89594553e32adb87d9638dce591782f947e3")
        (Just "root@node1.example.com, 2009-05-22 12:47:52")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerformanceIndicators 78728316 0 77675644 1277039 254 270 0 0 0 0
          Nothing Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 65657 135 0 0 135)
        (Just $ AdditionalInfo 0 257 11378843 254 0 0 254),
      UnconfiguredDevice 1,
      UnconfiguredDevice 2,
      UnconfiguredDevice 5,
      UnconfiguredDevice 6
    ]

-- | Test a DRBD 8.3 file with a NULL caracter inside.
case_drbd83_sync_krnl2_6_39 :: Assertion
case_drbd83_sync_krnl2_6_39 = testFile "proc_drbd83_sync_krnl2.6.39.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.3.1") (Just "88") (Just "86-89") Nothing
        (Just "fd40f4a8f9104941537d1afc8521e584a6d3003c")
        (Just "phil@fat-tyre, 2009-03-27 12:19:49")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r----"
        (PerformanceIndicators 140978 0 9906 131533 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing,
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerformanceIndicators 0 140980 140980 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 3 SyncSource (LocalRemote Primary Secondary)
        (LocalRemote UpToDate Inconsistent) 'A' "r-----"
        (PerformanceIndicators 373888 0 0 374088 0 22 7 27 7 0 (Just 1)
          (Just 'f') (Just 15358208))
        (Just $ SyncStatus 2.4 14996 15360 MegaByte (Time 0 4 8) 61736 Nothing
          KiloByte Second)
        Nothing
        Nothing,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r----"
        (PerformanceIndicators 140978 0 9906 131534 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.3 file with an ongoing synchronization.
case_drbd83_sync :: Assertion
case_drbd83_sync = testFile "proc_drbd83_sync.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.3.1") (Just "88") (Just "86-89") Nothing
        (Just "fd40f4a8f9104941537d1afc8521e584a6d3003c")
        (Just "phil@fat-tyre, 2009-03-27 12:19:49")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r----"
        (PerformanceIndicators 140978 0 9906 131533 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing,
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerformanceIndicators 0 140980 140980 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 3 SyncTarget (LocalRemote Primary Secondary)
        (LocalRemote Inconsistent UpToDate) 'C' "r----"
        (PerformanceIndicators 0 178176 178176 0 104 42 0 0 0 0 (Just 1)
          (Just 'b') (Just 346112))
        (Just $ SyncStatus 34.9 346112 524288 MegaByte (Time 0 0 5) 59392 Nothing
          KiloByte Second)
        Nothing
        Nothing,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r----"
        (PerformanceIndicators 140978 0 9906 131534 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.3 file not from git sources, with an ongoing synchronization
-- and the "want" field
case_drbd83_sync_want :: Assertion
case_drbd83_sync_want = testFile "proc_drbd83_sync_want.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.3.11") (Just "88") (Just "86-96")
        (Just "2D876214BAAD53B31ADC1D6")
        Nothing Nothing
    )
    [ DeviceInfo 0 SyncTarget (LocalRemote Secondary Primary)
        (LocalRemote Inconsistent UpToDate) 'C' "r-----"
        (PerformanceIndicators 0 460288 460160 0 0 28 2 4 1 0 (Just 1)
          (Just 'f') (Just 588416))
        (Just $ SyncStatus 44.4 588416 1048576 KiloByte (Time 0 0 8) 65736
          (Just 61440) KiloByte Second)
        Nothing
        Nothing,
      UnconfiguredDevice 1,
      UnconfiguredDevice 2,
      UnconfiguredDevice 3
    ]

-- | Test a DRBD 8.3 file.
case_drbd83 :: Assertion
case_drbd83 = testFile "proc_drbd83.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.3.1") (Just "88") (Just "86-89")
      Nothing
      (Just "fd40f4a8f9104941537d1afc8521e584a6d3003c")
      (Just "phil@fat-tyre, 2009-03-27 12:19:49")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r----"
        (PerformanceIndicators 140978 0 9906 131533 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing,
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerformanceIndicators 0 140980 140980 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r----"
        (PerformanceIndicators 140978 0 9906 131534 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing,
      DeviceInfo 5 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate Diskless) 'C' "r----"
        (PerformanceIndicators 140978 0 9906 131533 19 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing,
      DeviceInfo 6 Connected (LocalRemote Secondary Primary)
        (LocalRemote Diskless UpToDate) 'C' "r---"
        (PerformanceIndicators 0 140978 140978 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing,
      DeviceInfo 7 WFConnection (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r---"
        (PerformanceIndicators 0 140978 140978 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing,
      DeviceInfo 8 StandAlone (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) ' ' "r---"
        (PerformanceIndicators 0 140978 140978 0 0 8 0 0 0 0 (Just 1)
          (Just 'f') (Just 0))
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.0 file with a missing device.
case_drbd8 :: Assertion
case_drbd8 = testFile "proc_drbd8.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.0.12") (Just "86") (Just "86") Nothing
        (Just "5c9f89594553e32adb87d9638dce591782f947e3")
        (Just "XXX")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerformanceIndicators 4375577 0 4446279 674 1067 69 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 793749 1067 0 0 1067),
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerformanceIndicators 738320 0 738320 554400 67 0 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 92464 67 0 0 67),
      UnconfiguredDevice 2,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r---"
        (PerformanceIndicators 738320 0 738320 554400 67 0 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 92464 67 0 0 67),
      DeviceInfo 5 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate Diskless) 'C' "r---"
        (PerformanceIndicators 4375581 0 4446283 674 1069 69 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 793750 1069 0 0 1069),
      DeviceInfo 6 Connected (LocalRemote Secondary Primary)
        (LocalRemote Diskless UpToDate) 'C'  "r---"
        (PerformanceIndicators 0 4375581 5186925 327 75 214 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        Nothing
        Nothing,
      DeviceInfo 7 WFConnection (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r---"
        (PerformanceIndicators 0 0 0 0 0 0 0 0 0 0 Nothing Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 0 0 0 0 0),
      DeviceInfo 8 StandAlone (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) ' ' "r---"
        (PerformanceIndicators 0 0 0 0 0 0 0 0 0 0 Nothing Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 0 0 0 0 0)
    ]

-- | Function for testing whether a comma-separated integer is parsed correctly.
testCommaInt :: String -> Int -> Assertion
testCommaInt numString expectedResult =
  case A.parseOnly commaIntParser $ pack numString of
    Left msg -> assertFailure $ "Parsing failed: " ++ msg
    Right obtained -> assertEqual numString expectedResult obtained

-- | Test if 1 digit integers are recognized correctly.
case_commaInt_1digit :: Assertion
case_commaInt_1digit = testCommaInt "1" 1

-- | Test if 3 digits integers are recognized correctly.
case_commaInt_3digits :: Assertion
case_commaInt_3digits = testCommaInt "123" 123

-- | Test if integers with 1 comma are recognized correctly.
case_commaInt_1comma :: Assertion
case_commaInt_1comma = testCommaInt "61,736" 61736

-- | Test if integers with 2 commas are recognized correctly.
case_commaInt_2commas :: Assertion
case_commaInt_2commas = testCommaInt "61,736,123" 61736123

-- | Test if non-triplets are handled correctly (they are assumed NOT being part
-- of the number).
case_commaInt_non_triplet :: Assertion
case_commaInt_non_triplet = testCommaInt "61,736,12" 61736


testSuite "Block_DRBDParser"
          [ 'case_drbd80_emptyline,
            'case_drbd83_sync_krnl2_6_39,
            'case_drbd83_sync,
            'case_drbd83_sync_want,
            'case_drbd83,
            'case_drbd8,
            'case_commaInt_1digit,
            'case_commaInt_3digits,
            'case_commaInt_1comma,
            'case_commaInt_2commas,
            'case_commaInt_non_triplet
          ]

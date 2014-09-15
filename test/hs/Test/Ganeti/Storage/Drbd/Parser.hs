{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for the DRBD Parser -}

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

module Test.Ganeti.Storage.Drbd.Parser (testBlock_Drbd_Parser) where

import Test.QuickCheck as QuickCheck hiding (Result)
import Test.HUnit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Data.Attoparsec.Text as A
import Data.List (intercalate)
import Data.Text (pack)

import Ganeti.Storage.Drbd.Parser (drbdStatusParser, commaIntParser)
import Ganeti.Storage.Drbd.Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Test a DRBD 8.0 file with an empty line inside.
case_drbd80_emptyline :: Assertion
case_drbd80_emptyline = testParser (drbdStatusParser [])
  "proc_drbd80-emptyline.txt" $ DRBDStatus
    ( VersionInfo (Just "8.0.12") (Just "86") (Just "86") Nothing
        (Just "5c9f89594553e32adb87d9638dce591782f947e3")
        (Just "root@node1.example.com, 2009-05-22 12:47:52")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerfIndicators 78728316 0 77675644 1277039 254 270 0 0 0 0
          Nothing Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 65657 135 0 0 135)
        (Just $ AdditionalInfo 0 257 11378843 254 0 0 254)
        Nothing,
      UnconfiguredDevice 1,
      UnconfiguredDevice 2,
      UnconfiguredDevice 5,
      UnconfiguredDevice 6
    ]

-- | Test a DRBD 8.0 file with an empty version.
case_drbd80_emptyversion :: Assertion
case_drbd80_emptyversion = testParser (drbdStatusParser [])
  "proc_drbd80-emptyversion.txt" $ DRBDStatus
    ( VersionInfo Nothing Nothing Nothing Nothing
        (Just "5c9f89594553e32adb87d9638dce591782f947e3")
        (Just "root@node1.example.com, 2009-05-22 12:47:52")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerfIndicators 78728316 0 77675644 1277039 254 270 0 0 0 0
          Nothing Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 65657 135 0 0 135)
        (Just $ AdditionalInfo 0 257 11378843 254 0 0 254)
        Nothing,
      UnconfiguredDevice 1,
      UnconfiguredDevice 2,
      UnconfiguredDevice 5,
      UnconfiguredDevice 6
    ]

-- | Test a DRBD 8.4 file with an ongoing synchronization.
case_drbd84_sync :: Assertion
case_drbd84_sync = testParser (drbdStatusParser []) "proc_drbd84_sync.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.4.2") (Just "1") (Just "86-101") Nothing
        (Just "7ad5f850d711223713d6dcadc3dd48860321070c")
        (Just "root@example.com, 2013-04-10 07:45:25")
    )
    [ DeviceInfo 0 StandAlone (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) ' ' "r-----"
        (PerfIndicators 0 0 33318 730 15 0 0 0 0 0 (Just 1)
          (Just 'd') (Just 1048320))
        Nothing
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 3,
      DeviceInfo 5 SyncSource (LocalRemote Secondary Secondary)
        (LocalRemote UpToDate Inconsistent) 'C' "r---n-"
        (PerfIndicators 716992 0 0 719432 0 43 0 33 18 0 (Just 1)
          (Just 'f') (Just 335744))
        (Just $ SyncStatus 68.5 335744 1048576 KiloByte (Time 0 0 5) 64800
          Nothing KiloByte Second)
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.4 file.
case_drbd84 :: Assertion
case_drbd84 = testParser (drbdStatusParser []) "proc_drbd84.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.4.2") (Just "1") (Just "86-101") Nothing
      (Just "7ad5f850d711223713d6dcadc3dd48860321070c")
      (Just "root@example.com, 2013-04-10 07:45:25")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r-----"
        (PerfIndicators 1048576 0 0 1048776 0 64 0 0 0 0 (Just 1)
          (Just 'f') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r-----"
        (PerfIndicators 0 1048576 1048576 0 0 64 0 0 0 0 (Just 1)
          (Just 'f') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r-----"
        (PerfIndicators 0 0 0 200 0 0 0 0 0 0 (Just 1)
          (Just 'f') (Just 1048320))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 6 Connected (LocalRemote Secondary Primary)
        (LocalRemote Diskless UpToDate) 'C' "r-----"
        (PerfIndicators 0 0 0 0 0 0 0 0 0 0 (Just 1) (Just 'b')
          (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 8 StandAlone (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) ' ' "r-----"
        (PerfIndicators 0 0 0 200 0 0 0 0 0 0 (Just 1)
          (Just 'f') (Just 1048320))
        Nothing
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.4 file with the first resource empty.
case_drbd84_emptyfirst :: Assertion
case_drbd84_emptyfirst = testParser (drbdStatusParser [])
  "proc_drbd84_emptyfirst.txt" $ DRBDStatus
    ( VersionInfo (Just "8.4.2") (Just "1") (Just "86-101") Nothing
      (Just "7ad5f850d711223713d6dcadc3dd48860321070c")
      (Just "root@example.com, 2013-04-10 07:45:25")
    )
    [ DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r-----"
        (PerfIndicators 0 1048576 1048576 0 0 64 0 0 0 0 (Just 1)
          (Just 'f') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r-----"
        (PerfIndicators 0 0 0 200 0 0 0 0 0 0 (Just 1)
          (Just 'f') (Just 1048320))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 6 Connected (LocalRemote Secondary Primary)
        (LocalRemote Diskless UpToDate) 'C' "r-----"
        (PerfIndicators 0 0 0 0 0 0 0 0 0 0 (Just 1) (Just 'b')
          (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 8 StandAlone (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) ' ' "r-----"
        (PerfIndicators 0 0 0 200 0 0 0 0 0 0 (Just 1)
          (Just 'f') (Just 1048320))
        Nothing
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.3 file with a NULL caracter inside.
case_drbd83_sync_krnl2_6_39 :: Assertion
case_drbd83_sync_krnl2_6_39 = testParser (drbdStatusParser [])
  "proc_drbd83_sync_krnl2.6.39.txt" $ DRBDStatus
    ( VersionInfo (Just "8.3.1") (Just "88") (Just "86-89") Nothing
        (Just "fd40f4a8f9104941537d1afc8521e584a6d3003c")
        (Just "phil@fat-tyre, 2009-03-27 12:19:49")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r----"
        (PerfIndicators 140978 0 9906 131533 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerfIndicators 0 140980 140980 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 3 SyncSource (LocalRemote Primary Secondary)
        (LocalRemote UpToDate Inconsistent) 'A' "r-----"
        (PerfIndicators 373888 0 0 374088 0 22 7 27 7 0 (Just 1)
          (Just 'f') (Just 15358208))
        (Just $ SyncStatus 2.4 14996 15360 MegaByte (Time 0 4 8) 61736 Nothing
          KiloByte Second)
        Nothing
        Nothing
        Nothing,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r----"
        (PerfIndicators 140978 0 9906 131534 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.3 file with an ongoing synchronization.
case_drbd83_sync :: Assertion
case_drbd83_sync = testParser (drbdStatusParser []) "proc_drbd83_sync.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.3.1") (Just "88") (Just "86-89") Nothing
        (Just "fd40f4a8f9104941537d1afc8521e584a6d3003c")
        (Just "phil@fat-tyre, 2009-03-27 12:19:49")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r----"
        (PerfIndicators 140978 0 9906 131533 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerfIndicators 0 140980 140980 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 3 SyncTarget (LocalRemote Primary Secondary)
        (LocalRemote Inconsistent UpToDate) 'C' "r----"
        (PerfIndicators 0 178176 178176 0 104 42 0 0 0 0 (Just 1)
          (Just 'b') (Just 346112))
        (Just $ SyncStatus 34.9 346112 524288 MegaByte (Time 0 0 5) 59392
          Nothing KiloByte Second)
        Nothing
        Nothing
        Nothing,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r----"
        (PerfIndicators 140978 0 9906 131534 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.3 file not from git sources, with an ongoing synchronization
-- and the "want" field
case_drbd83_sync_want :: Assertion
case_drbd83_sync_want = testParser (drbdStatusParser [])
  "proc_drbd83_sync_want.txt" $ DRBDStatus
    ( VersionInfo (Just "8.3.11") (Just "88") (Just "86-96")
        (Just "2D876214BAAD53B31ADC1D6")
        Nothing Nothing
    )
    [ DeviceInfo 0 SyncTarget (LocalRemote Secondary Primary)
        (LocalRemote Inconsistent UpToDate) 'C' "r-----"
        (PerfIndicators 0 460288 460160 0 0 28 2 4 1 0 (Just 1)
          (Just 'f') (Just 588416))
        (Just $ SyncStatus 44.4 588416 1048576 KiloByte (Time 0 0 8) 65736
          (Just 61440) KiloByte Second)
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 1,
      UnconfiguredDevice 2,
      UnconfiguredDevice 3
    ]

-- | Test a DRBD 8.3 file.
case_drbd83 :: Assertion
case_drbd83 = testParser (drbdStatusParser []) "proc_drbd83.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.3.1") (Just "88") (Just "86-89")
      Nothing
      (Just "fd40f4a8f9104941537d1afc8521e584a6d3003c")
      (Just "phil@fat-tyre, 2009-03-27 12:19:49")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r----"
        (PerfIndicators 140978 0 9906 131533 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerfIndicators 0 140980 140980 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r----"
        (PerfIndicators 140978 0 9906 131534 27 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 5 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate Diskless) 'C' "r----"
        (PerfIndicators 140978 0 9906 131533 19 8 0 0 0 0 (Just 1)
          (Just 'b') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 6 Connected (LocalRemote Secondary Primary)
        (LocalRemote Diskless UpToDate) 'C' "r---"
        (PerfIndicators 0 140978 140978 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 7 WFConnection (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r---"
        (PerfIndicators 0 140978 140978 0 0 8 0 0 0 0 (Just 1) (Just 'f')
          (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 8 StandAlone (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) ' ' "r---"
        (PerfIndicators 0 140978 140978 0 0 8 0 0 0 0 (Just 1)
          (Just 'f') (Just 0))
        Nothing
        Nothing
        Nothing
        Nothing
    ]

-- | Test a DRBD 8.0 file with a missing device.
case_drbd8 :: Assertion
case_drbd8 = testParser (drbdStatusParser []) "proc_drbd8.txt" $
  DRBDStatus
    ( VersionInfo (Just "8.0.12") (Just "86") (Just "86") Nothing
        (Just "5c9f89594553e32adb87d9638dce591782f947e3")
        (Just "XXX")
    )
    [ DeviceInfo 0 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerfIndicators 4375577 0 4446279 674 1067 69 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 793749 1067 0 0 1067)
        Nothing,
      DeviceInfo 1 Connected (LocalRemote Secondary Primary)
        (LocalRemote UpToDate UpToDate) 'C' "r---"
        (PerfIndicators 738320 0 738320 554400 67 0 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 92464 67 0 0 67)
        Nothing,
      UnconfiguredDevice 2,
      DeviceInfo 4 WFConnection (LocalRemote Primary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r---"
        (PerfIndicators 738320 0 738320 554400 67 0 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 92464 67 0 0 67)
        Nothing,
      DeviceInfo 5 Connected (LocalRemote Primary Secondary)
        (LocalRemote UpToDate Diskless) 'C' "r---"
        (PerfIndicators 4375581 0 4446283 674 1069 69 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 793750 1069 0 0 1069)
        Nothing,
      DeviceInfo 6 Connected (LocalRemote Secondary Primary)
        (LocalRemote Diskless UpToDate) 'C'  "r---"
        (PerfIndicators 0 4375581 5186925 327 75 214 0 0 0 0 Nothing
          Nothing Nothing)
        Nothing
        Nothing
        Nothing
        Nothing,
      DeviceInfo 7 WFConnection (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) 'C' "r---"
        (PerfIndicators 0 0 0 0 0 0 0 0 0 0 Nothing Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 0 0 0 0 0)
        Nothing,
      DeviceInfo 8 StandAlone (LocalRemote Secondary Unknown)
        (LocalRemote UpToDate DUnknown) ' ' "r---"
        (PerfIndicators 0 0 0 0 0 0 0 0 0 0 Nothing Nothing Nothing)
        Nothing
        (Just $ AdditionalInfo 0 61 0 0 0 0 0)
        (Just $ AdditionalInfo 0 257 0 0 0 0 0)
        Nothing
    ]

-- | Function for splitting a list in chunks of a given size.
-- FIXME: an equivalent function exists in Data.List.Split, but it seems
-- pointless to add this package as a dependence just for this single
-- use. In case it is ever added, just remove this function definition
-- and use the one from the package.
splitEvery :: Int -> [e] -> [[e]]
splitEvery i l = map (take i) (splitter l (:) []) where
  splitter [] _ n = n
  splitter li c n  = li `c` splitter (drop i li) c n

-- | Function for testing whether a single comma-separated integer is
-- parsed correctly.
testCommaInt :: String -> Int -> Assertion
testCommaInt numString expectedResult =
  case A.parseOnly commaIntParser $ pack numString of
    Left msg -> assertFailure $ "Parsing failed: " ++ msg
    Right obtained -> assertEqual numString expectedResult obtained

-- | Generate a property test for CommaInt numbers in a given range.
gen_prop_CommaInt :: Int -> Int -> Property
gen_prop_CommaInt minVal maxVal =
  forAll (choose (minVal, maxVal)) $ \i ->
    case A.parseOnly commaIntParser $ pack (generateCommaInt i) of
      Left msg -> failTest $ "Parsing failed: " ++ msg
      Right obtained -> i ==? obtained
  where generateCommaInt x =
          ((reverse . intercalate ",") . splitEvery 3) . reverse $ show x

-- | Test if <4 digit integers are recognized correctly.
prop_commaInt_noCommas :: Property
prop_commaInt_noCommas = gen_prop_CommaInt 0 999

-- | Test if integers with 1 comma are recognized correctly.
prop_commaInt_1Comma :: Property
prop_commaInt_1Comma = gen_prop_CommaInt 1000 999999

-- | Test if integers with multiple commas are recognized correctly.
prop_commaInt_multipleCommas :: Property
prop_commaInt_multipleCommas = gen_prop_CommaInt 1000000 (maxBound ::
  Int)

-- | Test whether the parser is actually able to behave as intended with
-- numbers without commas. That is, if a number with more than 3 digits
-- is parsed, only up to the first 3 digits are considered (because they
-- are a valid commaInt), and the rest is ignored.
-- e.g.: parse "1234" = 123
prop_commaInt_max3WithoutComma :: Property
prop_commaInt_max3WithoutComma =
  forAll (choose (0, maxBound :: Int)) $ \i ->
    case A.parseOnly commaIntParser $ pack (show i) of
      Left msg -> failTest $ "Parsing failed: " ++ msg
      Right obtained ->
        obtained < 1000 .&&.
        getFirst3Digits i ==? obtained
  where getFirst3Digits x =
          if x >= 1000
            then getFirst3Digits $ x `div` 10
            else x

-- | Test if non-triplets are handled correctly (they are assumed NOT being part
-- of the number).
case_commaInt_non_triplet :: Assertion
case_commaInt_non_triplet = testCommaInt "61,736,12" 61736


testSuite "Block/Drbd/Parser"
          [ 'case_drbd80_emptyline,
            'case_drbd80_emptyversion,
            'case_drbd84_sync,
            'case_drbd84,
            'case_drbd84_emptyfirst,
            'case_drbd83_sync_krnl2_6_39,
            'case_drbd83_sync,
            'case_drbd83_sync_want,
            'case_drbd83,
            'case_drbd8,
            'case_commaInt_non_triplet,
            'prop_commaInt_noCommas,
            'prop_commaInt_1Comma,
            'prop_commaInt_multipleCommas,
            'prop_commaInt_max3WithoutComma
          ]

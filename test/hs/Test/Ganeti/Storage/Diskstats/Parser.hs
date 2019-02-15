{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for the @/proc/diskstats@ parser -}

{-

Copyright (C) 2013 Google Inc.
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

module Test.Ganeti.Storage.Diskstats.Parser (testBlock_Diskstats_Parser) where

import Test.QuickCheck as QuickCheck hiding (Result)
import Test.HUnit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Control.Applicative ((<*>), (<$>))
import qualified Data.Attoparsec.Text as A
import Data.Text (pack)
import Text.Printf

import Ganeti.Storage.Diskstats.Parser (diskstatsParser)
import Ganeti.Storage.Diskstats.Types

{-# ANN module "HLint: ignore Use camelCase" #-}


-- | Test a diskstats.
case_diskstats :: Assertion
case_diskstats = testParser diskstatsParser "proc_diskstats.txt"
  [ Diskstats 1 0 "ram0" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 1 "ram1" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 2 "ram2" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 3 "ram3" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 4 "ram4" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 5 "ram5" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 6 "ram6" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 7 "ram7" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 8 "ram8" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 9 "ram9" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 10 "ram10" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 11 "ram11" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 12 "ram12" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 13 "ram13" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 14 "ram14" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 1 15 "ram15" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 7 0 "loop0" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 7 1 "loop1" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 7 2 "loop2" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 7 3 "loop3" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 7 4 "loop4" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 7 5 "loop5" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 7 6 "loop6" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 7 7 "loop7" 0 0 0 0 0 0 0 0 0 0 0
  , Diskstats 8 0 "sda" 89502 4833 4433387 89244 519115 62738 16059726 465120 0
    149148 554564
  , Diskstats 8 1 "sda1" 505 2431 8526 132 478 174 124358 8500 0 340 8632
  , Diskstats 8 2 "sda2" 2 0 4 4 0 0 0 0 0 4 4
  , Diskstats 8 5 "sda5" 88802 2269 4422249 89032 453703 62564 15935368 396244 0
    90064 485500
  , Diskstats 252 0 "dm-0" 90978 0 4420002 158632 582226 0 15935368 5592012 0
  167688 5750652
  , Diskstats 252 1 "dm-1" 88775 0 4402378 157204 469594 0 15136008 4910424 0
  164556 5067640
  , Diskstats 252 2 "dm-2" 1956 0 15648 1052 99920 0 799360 682492 0 4516 683552
  , Diskstats 8 16 "sdb" 0 0 0 0 0 0 0 0 0 0 0
  ]

-- | The instance for generating arbitrary Diskstats
instance Arbitrary Diskstats where
  arbitrary =
    Diskstats <$> genNonNegative <*> genNonNegative <*> genName
              <*> genNonNegative <*> genNonNegative <*> genNonNegative
              <*> genNonNegative <*> genNonNegative <*> genNonNegative
              <*> genNonNegative <*> genNonNegative <*> genNonNegative
              <*> genNonNegative <*> genNonNegative

-- | Serialize a list of Diskstats in a parsable way
serializeDiskstatsList :: [Diskstats] -> String
serializeDiskstatsList = concatMap serializeDiskstats

-- | Serialize a Diskstats in a parsable way
serializeDiskstats :: Diskstats -> String
serializeDiskstats ds =
  printf "\t%d\t%d %s %d %d %d %d %d %d %d %d %d %d %d\n"
    (dsMajor ds) (dsMinor ds) (dsName ds) (dsReadsNum ds) (dsMergedReads ds)
    (dsSecRead ds) (dsTimeRead ds) (dsWrites ds) (dsMergedWrites ds)
    (dsSecWritten ds) (dsTimeWrite ds) (dsIos ds) (dsTimeIO ds) (dsWIOmillis ds)

-- | Test whether an arbitrary Diskstats is parsed correctly
prop_diskstats :: [Diskstats] -> Property
prop_diskstats dsList =
    case A.parseOnly diskstatsParser $ pack (serializeDiskstatsList dsList) of
      Left msg -> failTest $ "Parsing failed: " ++ msg
      Right obtained -> dsList ==? obtained

testSuite "Block/Diskstats/Parser"
          [ 'case_diskstats,
            'prop_diskstats
          ]

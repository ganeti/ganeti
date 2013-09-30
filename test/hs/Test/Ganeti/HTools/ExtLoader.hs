{-| Unittests for the MonD data parse function -}

{-

Copyright (C) 2013 Google Inc.

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

module Test.Ganeti.HTools.ExtLoader where

import Data.Ratio

import qualified Test.HUnit as HUnit
import qualified Text.JSON as J

import qualified Ganeti.BasicTypes as BT
import qualified Ganeti.DataCollectors.CPUload as CPUload

import Ganeti.Cpu.Types (CPUavgload(..))
import Ganeti.DataCollectors.Types (DCReport(..))
import Ganeti.HTools.ExtLoader
import Ganeti.JSON
import Test.Ganeti.TestCommon

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Test a MonD data file.
case_parseMonDData :: HUnit.Assertion
case_parseMonDData = do
  let mond_data_file = "mond-data.txt"
      n1 = "node1.example.com"
      n2 = "node2.example.com"
      t1 = 1379507272000000000
      t2 = 1379507280000000000
      cpu_number1 = 4
      cpu_number2 = 2
      cpus1 = [ 0.04108859597350646,0.04456554528165781
               , 0.06203619909502262,0.05595448881893895]
      cpus2 = [0.004155409618511363,0.0034586452012150787]
      cpu_total1 = 0.203643517607712
      cpu_total2 = 0.007614031289927129
      dcr1 = DCReport CPUload.dcName CPUload.dcVersion CPUload.dcFormatVersion
               t1 CPUload.dcCategory CPUload.dcKind
               (J.showJSON (CPUavgload cpu_number1 cpus1 cpu_total1))
      dcr2 = DCReport CPUload.dcName CPUload.dcVersion CPUload.dcFormatVersion
               t2 CPUload.dcCategory CPUload.dcKind
               (J.showJSON (CPUavgload cpu_number2 cpus2 cpu_total2))
      expected_list = [(n1,[dcr1]),(n2,[dcr2])]
  ans <- readTestData mond_data_file
  case pMonDData ans of
    BT.Ok l -> HUnit.assertBool ("Parsing " ++ mond_data_file ++ " failed")
                 (isAlEqual expected_list l)
    BT.Bad s -> HUnit.assertFailure $ "Parsing failed: " ++ s

-- | Check for quality two list of tuples.
isAlEqual :: [(String, [DCReport])] -> [(String, [DCReport])] -> Bool
isAlEqual a b = and (zipWith tupleIsAlEqual a b)

-- | Check a tuple for quality.
tupleIsAlEqual :: (String, [DCReport]) -> (String, [DCReport]) -> Bool
tupleIsAlEqual (na, a) (nb, b) =
  na == nb
  && and (zipWith dcReportIsAlmostEqual a b)

-- | Check if two DCReports are equal. Only reports from CPUload Data
-- Collectors are supported.
dcReportIsAlmostEqual :: DCReport -> DCReport -> Bool
dcReportIsAlmostEqual a b =
  dcReportName a == dcReportName b
  && dcReportVersion a == dcReportVersion b
  && dcReportFormatVersion a == dcReportFormatVersion b
  && dcReportTimestamp a == dcReportTimestamp b
  && dcReportCategory a == dcReportCategory b
  && dcReportKind a == dcReportKind b
  && case () of
       _ | CPUload.dcName == dcReportName a ->
             cpuavgloadDataIsAlmostEq (dcReportData a) (dcReportData b)
         | otherwise -> False

-- | Converts two JSValue objects and compares them.
cpuavgloadDataIsAlmostEq :: J.JSValue -> J.JSValue -> Bool
cpuavgloadDataIsAlmostEq a b =
  case fromJVal a :: BT.Result CPUavgload of
    BT.Bad _ -> False
    BT.Ok cavA ->
      case fromJVal b :: BT.Result CPUavgload of
           BT.Bad _ -> False
           BT.Ok cavB -> compareCPUavgload cavA cavB

-- | Compares two CPuavgload objects.
compareCPUavgload :: CPUavgload -> CPUavgload -> Bool
compareCPUavgload a b =
  let relError x y = relativeError x y <= 1e-9
  in cavCpuNumber a == cavCpuNumber b
     && relError (cavCpuTotal a) (cavCpuTotal b)
     && length (cavCpus a) == length (cavCpus b)
     && and (zipWith relError (cavCpus a) (cavCpus b))

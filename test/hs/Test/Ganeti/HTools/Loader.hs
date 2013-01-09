{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Test.Ganeti.HTools.Loader (testHTools_Loader) where

import Test.QuickCheck

import qualified Data.IntMap as IntMap
import qualified Data.Map as Map
import Data.List
import System.Time (ClockTime(..))

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.HTools.Node ()

import qualified Ganeti.BasicTypes as BasicTypes
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node

prop_lookupNode :: [(String, Int)] -> String -> String -> Property
prop_lookupNode ktn inst node =
  Loader.lookupNode nl inst node ==? Map.lookup node nl
    where nl = Map.fromList ktn

prop_lookupInstance :: [(String, Int)] -> String -> Property
prop_lookupInstance kti inst =
  Loader.lookupInstance il inst ==? Map.lookup inst il
    where il = Map.fromList kti

prop_assignIndices :: Property
prop_assignIndices =
  -- generate nodes with unique names
  forAll (arbitrary `suchThat`
          (\nodes ->
             let names = map Node.name nodes
             in length names == length (nub names))) $ \nodes ->
  let (nassoc, kt) =
        Loader.assignIndices (map (\n -> (Node.name n, n)) nodes)
  in Map.size nassoc == length nodes &&
     Container.size kt == length nodes &&
     (null nodes || maximum (IntMap.keys kt) == length nodes - 1)

-- | Checks that the number of primary instances recorded on the nodes
-- is zero.
prop_mergeData :: [Node.Node] -> Bool
prop_mergeData ns =
  let na = Container.fromList $ map (\n -> (Node.idx n, n)) ns
  in case Loader.mergeData [] [] [] [] (TOD 0 0)
         (Loader.emptyCluster {Loader.cdNodes = na}) of
    BasicTypes.Bad _ -> False
    BasicTypes.Ok (Loader.ClusterData _ nl il _ _) ->
      let nodes = Container.elems nl
          instances = Container.elems il
      in (sum . map (length . Node.pList)) nodes == 0 &&
         null instances

-- | Check that compareNameComponent on equal strings works.
prop_compareNameComponent_equal :: String -> Bool
prop_compareNameComponent_equal s =
  BasicTypes.compareNameComponent s s ==
    BasicTypes.LookupResult BasicTypes.ExactMatch s

-- | Check that compareNameComponent on prefix strings works.
prop_compareNameComponent_prefix :: NonEmptyList Char -> String -> Bool
prop_compareNameComponent_prefix (NonEmpty s1) s2 =
  BasicTypes.compareNameComponent (s1 ++ "." ++ s2) s1 ==
    BasicTypes.LookupResult BasicTypes.PartialMatch s1

testSuite "HTools/Loader"
            [ 'prop_lookupNode
            , 'prop_lookupInstance
            , 'prop_assignIndices
            , 'prop_mergeData
            , 'prop_compareNameComponent_equal
            , 'prop_compareNameComponent_prefix
            ]

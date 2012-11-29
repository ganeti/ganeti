{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for Ganeti.Htools.Graph

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

module Test.Ganeti.HTools.Graph (testHTools_Graph) where

import Test.QuickCheck
import Test.HUnit

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.HTools.Graph

import qualified Data.Graph as Graph
import qualified Data.IntMap as IntMap

{-# ANN module "HLint: ignore Use camelCase" #-}

data TestableGraph = TestableGraph Graph.Graph deriving (Show)
data TestableClique = TestableClique Graph.Graph deriving (Show)

-- | Generate node bounds and edges for an undirected graph.
-- A graph is undirected if for every (a, b) edge there is a
-- corresponding (b, a) one.
undirEdges :: Gen (Graph.Bounds, [Graph.Edge])
undirEdges = sized undirEdges'
  where
    undirEdges' 0 = return ((0, 0), [])
    undirEdges' n = do
      maxv <- choose (1, n)
      edges <- listOf1 $ do
        i <- choose (0, maxv)
        j <- choose (0, maxv) `suchThat` (/= i)
        return [(i, j), (j, i)]
      return ((0, maxv), concat edges)

-- | Generate node bounds and edges for a clique.
-- In a clique all nodes are directly connected to each other.
cliqueEdges :: Gen (Graph.Bounds, [Graph.Edge])
cliqueEdges = sized cliqueEdges'
  where
    cliqueEdges' 0 = return ((0, 0), [])
    cliqueEdges' n = do
      maxv <- choose (0, n)
      let edges = [(x, y) | x <- [0..maxv], y <- [0..maxv], x /= y]
      return ((0, maxv), edges)

instance Arbitrary TestableGraph where
  arbitrary = do
    (mybounds, myedges) <- undirEdges
    return . TestableGraph $ Graph.buildG mybounds myedges

instance Arbitrary TestableClique where
  arbitrary = do
    (mybounds, myedges) <- cliqueEdges
    return . TestableClique $ Graph.buildG mybounds myedges

-- | Check that the empty vertex color map is empty.
case_emptyVertColorMapNull :: Assertion
case_emptyVertColorMapNull = assertBool "" $ IntMap.null emptyVertColorMap

-- | Check that the empty vertex color map is zero in size.
case_emptyVertColorMapEmpty :: Assertion
case_emptyVertColorMapEmpty =
  assertEqual "" 0 $ IntMap.size emptyVertColorMap

-- | Check if each two consecutive elements on a list
-- respect a given condition.
anyTwo :: (a -> a -> Bool) -> [a] -> Bool
anyTwo _ [] = True
anyTwo _ [_] = True
anyTwo op (x:y:xs) = (x `op` y) && anyTwo op (y:xs)

-- | Check order of vertices returned by verticesByDegreeAsc.
prop_verticesByDegreeAscAsc :: TestableGraph -> Property
prop_verticesByDegreeAscAsc (TestableGraph g) =
    anyTwo (<=) (degrees asc) ==? True
    where degrees = map (length . neighbors g)
          asc = verticesByDegreeAsc g

-- | Check order of vertices returned by verticesByDegreeDesc.
prop_verticesByDegreeDescDesc :: TestableGraph -> Property
prop_verticesByDegreeDescDesc (TestableGraph g) =
    anyTwo (>=) (degrees desc) ==? True
    where degrees = map (length . neighbors g)
          desc = verticesByDegreeDesc g

-- | Check that our generated graphs are colorable
prop_isColorableTestableGraph :: TestableGraph -> Property
prop_isColorableTestableGraph (TestableGraph g) = isColorable g ==? True

-- | Check that our generated graphs are colorable
prop_isColorableTestableClique :: TestableClique -> Property
prop_isColorableTestableClique (TestableClique g) = isColorable g ==? True

-- | Check that the given algorithm colors a clique with the same number of
-- colors as the vertices number.
prop_colorClique :: (Graph.Graph -> ColorVertMap) -> TestableClique -> Property
prop_colorClique alg (TestableClique g) = numvertices ==? numcolors
    where numcolors = IntMap.size (alg g)
          numvertices = length (Graph.vertices g)

-- | Specific check for the LF algorithm.
prop_colorLFClique :: TestableClique -> Property
prop_colorLFClique = prop_colorClique colorLF

-- | Specific check for the Dsatur algorithm.
prop_colorDsaturClique :: TestableClique -> Property
prop_colorDsaturClique = prop_colorClique colorDsatur

-- Check that all nodes are colored.
prop_colorAllNodes :: (Graph.Graph -> ColorVertMap)
                   -> TestableGraph
                   -> Property
prop_colorAllNodes alg (TestableGraph g) = numvertices ==? numcolored
    where numcolored = IntMap.fold (\v l -> length v + l) 0 $ alg g
          numvertices = length (Graph.vertices g)

-- | Specific check for the LF algorithm.
prop_colorLFAllNodes :: TestableGraph -> Property
prop_colorLFAllNodes = prop_colorAllNodes colorLF

-- | Specific check for the Dsatur algorithm.
prop_colorDsaturAllNodes :: TestableGraph -> Property
prop_colorDsaturAllNodes = prop_colorAllNodes colorDsatur

-- | List of tests for the Graph module.
testSuite "HTools/Graph"
            [ 'case_emptyVertColorMapNull
            , 'case_emptyVertColorMapEmpty
            , 'prop_verticesByDegreeAscAsc
            , 'prop_verticesByDegreeDescDesc
            , 'prop_colorLFClique
            , 'prop_colorDsaturClique
            , 'prop_colorLFAllNodes
            , 'prop_colorDsaturAllNodes
            , 'prop_isColorableTestableGraph
            , 'prop_isColorableTestableClique
            ]

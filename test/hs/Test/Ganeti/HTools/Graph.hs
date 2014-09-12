{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for Ganeti.Htools.Graph

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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
prop_verticesByDegreeAscAsc :: TestableGraph -> Bool
prop_verticesByDegreeAscAsc (TestableGraph g) = anyTwo (<=) (degrees asc)
    where degrees = map (length . neighbors g)
          asc = verticesByDegreeAsc g

-- | Check order of vertices returned by verticesByDegreeDesc.
prop_verticesByDegreeDescDesc :: TestableGraph -> Bool
prop_verticesByDegreeDescDesc (TestableGraph g) = anyTwo (>=) (degrees desc)
    where degrees = map (length . neighbors g)
          desc = verticesByDegreeDesc g

-- | Check that our generated graphs are colorable
prop_isColorableTestableGraph :: TestableGraph -> Bool
prop_isColorableTestableGraph (TestableGraph g) = isColorable g

-- | Check that our generated graphs are colorable
prop_isColorableTestableClique :: TestableClique -> Bool
prop_isColorableTestableClique (TestableClique g) = isColorable g

-- | Check that the given algorithm colors a clique with the same number of
-- colors as the vertices number.
prop_colorClique :: (Graph.Graph -> VertColorMap) -> TestableClique -> Property
prop_colorClique alg (TestableClique g) = numvertices ==? numcolors
    where numcolors = (IntMap.size . colorVertMap) $ alg g
          numvertices = length (Graph.vertices g)

-- | Specific check for the LF algorithm.
prop_colorLFClique :: TestableClique -> Property
prop_colorLFClique = prop_colorClique colorLF

-- | Specific check for the Dsatur algorithm.
prop_colorDsaturClique :: TestableClique -> Property
prop_colorDsaturClique = prop_colorClique colorDsatur

-- | Specific check for the Dcolor algorithm.
prop_colorDcolorClique :: TestableClique -> Property
prop_colorDcolorClique = prop_colorClique colorDcolor

-- Check that all nodes are colored.
prop_colorAllNodes :: (Graph.Graph -> VertColorMap)
                   -> TestableGraph
                   -> Property
prop_colorAllNodes alg (TestableGraph g) = numvertices ==? numcolored
    where numcolored = IntMap.fold ((+) . length) 0 vcMap
          vcMap = colorVertMap $ alg g
          numvertices = length (Graph.vertices g)

-- | Specific check for the LF algorithm.
prop_colorLFAllNodes :: TestableGraph -> Property
prop_colorLFAllNodes = prop_colorAllNodes colorLF

-- | Specific check for the Dsatur algorithm.
prop_colorDsaturAllNodes :: TestableGraph -> Property
prop_colorDsaturAllNodes = prop_colorAllNodes colorDsatur

-- | Specific check for the Dcolor algorithm.
prop_colorDcolorAllNodes :: TestableGraph -> Property
prop_colorDcolorAllNodes = prop_colorAllNodes colorDcolor

-- | Check that no two vertices sharing the same edge have the same color.
prop_colorProper :: (Graph.Graph -> VertColorMap) -> TestableGraph -> Bool
prop_colorProper alg (TestableGraph g) = all isEdgeOk $ Graph.edges g
    where isEdgeOk :: Graph.Edge -> Bool
          isEdgeOk (v1, v2) = color v1 /= color v2
          color v = cMap IntMap.! v
          cMap = alg g

-- | Specific check for the LF algorithm.
prop_colorLFProper :: TestableGraph -> Bool
prop_colorLFProper = prop_colorProper colorLF

-- | Specific check for the Dsatur algorithm.
prop_colorDsaturProper :: TestableGraph -> Bool
prop_colorDsaturProper = prop_colorProper colorDsatur

-- | Specific check for the Dcolor algorithm.
prop_colorDcolorProper :: TestableGraph -> Bool
prop_colorDcolorProper = prop_colorProper colorDcolor

-- | List of tests for the Graph module.
testSuite "HTools/Graph"
            [ 'case_emptyVertColorMapNull
            , 'case_emptyVertColorMapEmpty
            , 'prop_verticesByDegreeAscAsc
            , 'prop_verticesByDegreeDescDesc
            , 'prop_colorLFClique
            , 'prop_colorDsaturClique
            , 'prop_colorDcolorClique
            , 'prop_colorLFAllNodes
            , 'prop_colorDsaturAllNodes
            , 'prop_colorDcolorAllNodes
            , 'prop_colorLFProper
            , 'prop_colorDsaturProper
            , 'prop_colorDcolorProper
            , 'prop_isColorableTestableGraph
            , 'prop_isColorableTestableClique
            ]

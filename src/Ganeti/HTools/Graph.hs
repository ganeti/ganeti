{-| Algorithms on Graphs.

This module contains a few graph algorithms and the transoformations
needed for them to be used on nodes.

For more information about Graph Coloring see:
<http://en.wikipedia.org/wiki/Graph_coloring>
<http://en.wikipedia.org/wiki/Greedy_coloring>

LF-coloring is described in:
Welsh, D. J. A.; Powell, M. B. (1967), "An upper bound for the chromatic number
of a graph and its application to timetabling problems", The Computer Journal
10 (1): 85-86, doi:10.1093/comjnl/10.1.85
<http://comjnl.oxfordjournals.org/content/10/1/85>

DSatur is described in:
Brelaz, D. (1979), "New methods to color the vertices of a graph",
Communications of the ACM 22 (4): 251-256, doi:10.1145/359094.359101
<http://dx.doi.org/10.1145%2F359094.359101>

Also interesting:
Klotz, W. (2002). Graph coloring algorithms. Mathematics Report, Technical
University Clausthal, 1-9.
<http://www.math.tu-clausthal.de/Arbeitsgruppen/Diskrete-Optimierung
/publications/2002/gca.pdf>

-}

{-

Copyright (C) 2012, 2013, Google Inc.
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

module Ganeti.HTools.Graph
  ( -- * Types
    Color
  , VertColorMap
  , ColorVertMap
    -- * Creation
  , emptyVertColorMap
    -- * Coloring
  , colorInOrder
  , colorLF
  , colorDsatur
  , colorDcolor
  , isColorable
    -- * Color map transformations
  , colorVertMap
    -- * Vertex characteristics
  , verticesByDegreeDesc
  , verticesByDegreeAsc
  , neighbors
  , hasLoop
  , isUndirected
  ) where

import Data.Maybe
import Data.Ord
import Data.List

import qualified Data.IntMap as IntMap
import qualified Data.IntSet as IntSet
import qualified Data.Graph as Graph
import qualified Data.Array as Array

-- * Type declarations

-- | Node colors.
type Color = Int

-- | Saturation: number of colored neighbors.
type Satur = Int

-- | Vertex to Color association.
type VertColorMap = IntMap.IntMap Color

-- | Color to Vertex association.
type ColorVertMap = IntMap.IntMap [Int]

-- * Vertices characteristics

-- | (vertex, degree) tuples on a graph.
verticesDegree :: Graph.Graph -> [(Graph.Vertex, Int)]
verticesDegree g = Array.assocs $ Graph.outdegree g

-- | vertices of a graph, sorted by ascending degree.
verticesByDegreeDesc :: Graph.Graph -> [Graph.Vertex]
verticesByDegreeDesc g =
  map fst . sortBy (flip (comparing snd)) $ verticesDegree g

-- | vertices of a graph, sorted by descending degree.
verticesByDegreeAsc :: Graph.Graph -> [Graph.Vertex]
verticesByDegreeAsc g = map fst . sortBy (comparing snd) $ verticesDegree g

-- | Get the neighbors of a vertex.
neighbors :: Graph.Graph -> Graph.Vertex -> [Graph.Vertex]
neighbors g v = g Array.! v

-- | Check whether a graph has no loops.
-- (vertices connected to themselves)
hasLoop :: Graph.Graph -> Bool
hasLoop g = any vLoops $ Graph.vertices g
    where vLoops v = v `elem` neighbors g v

-- | Check whether a graph is undirected
isUndirected :: Graph.Graph -> Bool
isUndirected g =
  (sort . Graph.edges) g == (sort . Graph.edges . Graph.transposeG) g

-- * Coloring

-- | Empty color map.
emptyVertColorMap :: VertColorMap
emptyVertColorMap = IntMap.empty

-- | Check whether a graph is colorable.
isColorable :: Graph.Graph -> Bool
isColorable g = isUndirected g && not (hasLoop g)

-- | Get the colors of a list of vertices.
-- Any uncolored vertices are ignored.
verticesColors :: VertColorMap -> [Graph.Vertex] -> [Color]
verticesColors cMap = mapMaybe (`IntMap.lookup` cMap)

-- | Get the set of colors of a list of vertices.
-- Any uncolored vertices are ignored.
verticesColorSet :: VertColorMap -> [Graph.Vertex] -> IntSet.IntSet
verticesColorSet cMap = IntSet.fromList . verticesColors cMap

-- | Get the colors of the neighbors of a vertex.
neighColors :: Graph.Graph -> VertColorMap -> Graph.Vertex -> [Color]
neighColors g cMap v = verticesColors cMap $ neighbors g v

{-# ANN colorNode "HLint: ignore Use alternative" #-}
-- | Color one node.
colorNode :: Graph.Graph -> VertColorMap -> Graph.Vertex -> Color
-- use of "head" is A-ok as the source is an infinite list
colorNode g cMap v = head $ filter notNeighColor [0..]
    where notNeighColor = (`notElem` neighColors g cMap v)

-- | Color a node returning the updated color map.
colorNodeInMap :: Graph.Graph -> Graph.Vertex -> VertColorMap -> VertColorMap
colorNodeInMap g v cMap = IntMap.insert v newcolor cMap
    where newcolor = colorNode g cMap v

-- | Color greedily all nodes in the given order.
colorInOrder :: Graph.Graph -> [Graph.Vertex] -> VertColorMap
colorInOrder g = foldr (colorNodeInMap g) emptyVertColorMap

-- | Color greedily all nodes, larger first.
colorLF :: Graph.Graph -> VertColorMap
colorLF g = colorInOrder g $ verticesByDegreeAsc g

-- | (vertex, (saturation, degree)) for a vertex.
vertexSaturation :: Graph.Graph
                 -> VertColorMap
                 -> Graph.Vertex
                 -> (Graph.Vertex, (Satur, Int))
vertexSaturation g cMap v =
  (v, (IntSet.size (verticesColorSet cMap neigh), length neigh))
    where neigh = neighbors g v

-- | (vertex, (colordegree, degree)) for a vertex.
vertexColorDegree :: Graph.Graph
                  -> VertColorMap
                  -> Graph.Vertex
                  -> (Graph.Vertex, (Int, Int))
vertexColorDegree g cMap v =
  (v, (length (verticesColors cMap neigh), length neigh))
    where neigh = neighbors g v

-- | Color all nodes in a dynamic order.
-- We have a list of vertices still uncolored, and at each round we
-- choose&delete one vertex among the remaining ones. A helper function
-- is used to induce an order so that the next vertex can be chosen.
colorDynamicOrder :: Ord a
                  =>  (Graph.Graph
                      -> VertColorMap
                      -> Graph.Vertex
                      -> (Graph.Vertex, a)) -- ^ Helper to induce the choice
                  -> Graph.Graph -- ^ Target graph
                  -> VertColorMap -- ^ Accumulating vertex color map
                  -> [Graph.Vertex] -- ^ List of remaining vertices
                  -> VertColorMap -- ^ Output vertex color map
colorDynamicOrder _ _ cMap [] = cMap
colorDynamicOrder ordind g cMap l = colorDynamicOrder ordind g newmap newlist
    where newmap = colorNodeInMap g choosen cMap
          choosen = fst . maximumBy (comparing snd) $ ordlist
          ordlist = map (ordind g cMap) l
          newlist = delete choosen l

-- | Color greedily all nodes, highest number of colored neighbors, then
-- highest degree. This is slower than "colorLF" as we must dynamically
-- recalculate which node to color next among all remaining ones but
-- produces better results.
colorDcolor :: Graph.Graph -> VertColorMap
colorDcolor g =
  colorDynamicOrder vertexColorDegree g emptyVertColorMap $ Graph.vertices g

-- | Color greedily all nodes, highest saturation, then highest degree.
-- This is slower than "colorLF" as we must dynamically recalculate
-- which node to color next among all remaining ones but produces better
-- results.
colorDsatur :: Graph.Graph -> VertColorMap
colorDsatur g =
  colorDynamicOrder vertexSaturation g emptyVertColorMap $ Graph.vertices g

-- | ColorVertMap from VertColorMap.
colorVertMap :: VertColorMap -> ColorVertMap
colorVertMap = IntMap.foldWithKey
                 (flip (IntMap.insertWith ((:) . head)) . replicate 1)
                 IntMap.empty

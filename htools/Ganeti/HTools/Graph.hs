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

-}

{-

Copyright (C) 2012, Google Inc.

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
    -- * Color map transformations
  , colorVertMap
    -- * Vertex sorting
  , verticesByDegreeDesc
  , verticesByDegreeAsc
  ) where

import Data.Maybe
import Data.Ord
import Data.List

import qualified Data.IntMap as IntMap
import qualified Data.Graph as Graph
import qualified Data.Array as Array

-- * Type declarations

-- | Node colors.
type Color = Int

-- | Vertex to Color association.
type VertColorMap = IntMap.IntMap Color

-- | Color to Vertex association.
type ColorVertMap = IntMap.IntMap [Int]

-- * Sorting of vertices

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

-- * Coloring

-- | Empty color map.
emptyVertColorMap :: VertColorMap
emptyVertColorMap = IntMap.empty

-- | Get the colors of the neighbors of a vertex.
neighColors :: Graph.Graph -> VertColorMap -> Graph.Vertex -> [Color]
neighColors g cMap v = mapMaybe (`IntMap.lookup` cMap) neighbors
    where neighbors = g Array.! v

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
colorLF :: Graph.Graph -> ColorVertMap
colorLF g = colorVertMap . colorInOrder g $ verticesByDegreeAsc g

-- | ColorVertMap from VertColorMap.
colorVertMap :: VertColorMap -> ColorVertMap
colorVertMap = IntMap.foldWithKey
                 (flip (IntMap.insertWith ((:) . head)) . replicate 1)
                 IntMap.empty

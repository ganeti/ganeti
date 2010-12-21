{-| Parsing data from a simulated description of the cluster

This module holds the code for parsing a cluster description.

-}

{-

Copyright (C) 2009, 2010 Google Inc.

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

module Ganeti.HTools.Simu
    (
      loadData
    , parseData
    ) where

import Text.Printf (printf)

import Ganeti.HTools.Utils
import Ganeti.HTools.Types
import Ganeti.HTools.Loader
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node

-- | Parse the string description into nodes.
parseDesc :: String -> Result (AllocPolicy, Int, Int, Int, Int)
parseDesc desc =
    case sepSplit ',' desc of
      [a, n, d, m, c] -> do
        apol <- apolFromString a
        ncount <- tryRead "node count" n
        disk <- tryRead "disk size" d
        mem <- tryRead "memory size" m
        cpu <- tryRead "cpu count" c
        return (apol, ncount, disk, mem, cpu)
      es -> fail $ printf
            "Invalid cluster specification, expected 5 comma-separated\
            \ sections (allocation policy, node count, disk size,\
            \ memory size, number of CPUs) but got %d: '%s'" (length es) desc

-- | Creates a node group with the given specifications.
createGroup :: Int    -- ^ The group index
            -> String -- ^ The group specification
            -> Result (Group.Group, [Node.Node])
createGroup grpIndex spec = do
  (apol, ncount, disk, mem, cpu) <- parseDesc spec
  let nodes = map (\idx ->
                       Node.create (printf "node-%02d-%03d" grpIndex idx)
                               (fromIntegral mem) 0 mem
                               (fromIntegral disk) disk
                               (fromIntegral cpu) False grpIndex
                  ) [1..ncount]
      grp = Group.create (printf "group-%02d" grpIndex)
            (printf "fake-uuid-%02d" grpIndex) apol
  return (grp, nodes)

-- | Builds the cluster data from node\/instance files.
parseData :: [String] -- ^ Cluster description in text format
          -> Result ClusterData
parseData ndata = do
  grpNodeData <- mapM (uncurry createGroup) $ zip [1..] ndata
  let (groups, nodes) = unzip grpNodeData
      nodes' = concat nodes
  let ktn = map (\(idx, n) -> (idx, Node.setIdx n idx))
            $ zip [1..] nodes'
      ktg = map (\g -> (Group.idx g, g)) groups
  return (ClusterData (Container.fromAssocList ktg)
                      (Container.fromAssocList ktn) Container.empty [])

-- | Builds the cluster data from node\/instance files.
loadData :: [String] -- ^ Cluster description in text format
         -> IO (Result ClusterData)
loadData = -- IO monad, just for consistency with the other loaders
  return . parseData

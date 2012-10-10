{-| Parsing data from a simulated description of the cluster.

This module holds the code for parsing a cluster description.

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

module Ganeti.HTools.Simu
  ( loadData
  , parseData
  ) where

import Control.Monad (mplus)
import Text.Printf (printf)

import Ganeti.HTools.Utils
import Ganeti.HTools.Types
import Ganeti.HTools.Loader
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node

-- | Parse a shortened policy string (for command line usage).
apolAbbrev :: String -> Result AllocPolicy
apolAbbrev c | c == "p"  = return AllocPreferred
             | c == "a"  = return AllocLastResort
             | c == "u"  = return AllocUnallocable
             | otherwise = fail $ "Cannot parse AllocPolicy abbreviation '"
                           ++ c ++ "'"

-- | Parse the string description into nodes.
parseDesc :: String -> [String]
          -> Result (AllocPolicy, Int, Int, Int, Int, Int)
parseDesc _ [a, n, d, m, c, s] = do
  apol <- allocPolicyFromRaw a `mplus` apolAbbrev a
  ncount <- tryRead "node count" n
  disk <- annotateResult "disk size" (parseUnit d)
  mem <- annotateResult "memory size" (parseUnit m)
  cpu <- tryRead "cpu count" c
  spindles <- tryRead "spindles" s
  return (apol, ncount, disk, mem, cpu, spindles)

parseDesc desc [a, n, d, m, c] = parseDesc desc [a, n, d, m, c, "1"]

parseDesc desc es =
  fail $ printf
         "Invalid cluster specification, expected 6 comma-separated\
         \ sections (allocation policy, node count, disk size,\
         \ memory size, number of CPUs, spindles) but got %d: '%s'"
         (length es) desc

-- | Creates a node group with the given specifications.
createGroup :: Int    -- ^ The group index
            -> String -- ^ The group specification
            -> Result (Group.Group, [Node.Node])
createGroup grpIndex spec = do
  (apol, ncount, disk, mem, cpu, spindles) <- parseDesc spec $
                                              sepSplit ',' spec
  let nodes = map (\idx ->
                     Node.create (printf "node-%02d-%03d" grpIndex idx)
                           (fromIntegral mem) 0 mem
                           (fromIntegral disk) disk
                           (fromIntegral cpu) False spindles grpIndex
                  ) [1..ncount]
      grp = Group.create (printf "group-%02d" grpIndex)
            (printf "fake-uuid-%02d" grpIndex) apol defIPolicy []
  return (Group.setIdx grp grpIndex, nodes)

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
  return (ClusterData (Container.fromList ktg)
                      (Container.fromList ktn) Container.empty [] defIPolicy)

-- | Builds the cluster data from node\/instance files.
loadData :: [String] -- ^ Cluster description in text format
         -> IO (Result ClusterData)
loadData = -- IO monad, just for consistency with the other loaders
  return . parseData

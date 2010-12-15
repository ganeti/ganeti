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
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

-- | Parse the string description into nodes
parseDesc :: String -> Result (Int, Int, Int, Int)
parseDesc desc =
    case sepSplit ',' desc of
      [n, d, m, c] -> do
        ncount <- tryRead "node count" n
        disk <- tryRead "disk size" d
        mem <- tryRead "memory size" m
        cpu <- tryRead "cpu count" c
        return (ncount, disk, mem, cpu)
      _ -> fail "Invalid cluster specification"

-- | Builds the cluster data from node\/instance files.
parseData :: String -- ^ Cluster description in text format
         -> Result (Group.List, Node.List, Instance.List, [String])
parseData ndata = do
  (cnt, disk, mem, cpu) <- parseDesc ndata
  let defgroup = Group.create "default" defaultGroupID AllocPreferred
  let nodes = map (\idx ->
                    let n = Node.create (printf "node%03d" idx)
                            (fromIntegral mem) 0 mem
                            (fromIntegral disk) disk
                            (fromIntegral cpu) False 0
                    in (idx, Node.setIdx n idx)
                  ) [1..cnt]
  return (Container.fromAssocList [(0, Group.setIdx defgroup 0)],
          Container.fromAssocList nodes, Container.empty, [])

-- | Builds the cluster data from node\/instance files.
loadData :: String -- ^ Cluster description in text format
         -> IO (Result (Group.List, Node.List, Instance.List, [String]))
loadData = -- IO monad, just for consistency with the other loaders
  return . parseData

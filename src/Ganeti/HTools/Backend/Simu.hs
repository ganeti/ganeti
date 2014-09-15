{-| Parsing data from a simulated description of the cluster.

This module holds the code for parsing a cluster description.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Ganeti.HTools.Backend.Simu
  ( loadData
  , parseData
  ) where

import Control.Monad (mplus, zipWithM)
import Text.Printf (printf)

import Ganeti.BasicTypes
import Ganeti.Utils
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
          -> Result (AllocPolicy, Int, Int, Int, Int, Int, Bool)
parseDesc _ [a, n, d, m, c, s, exstor] = do
  apol <- allocPolicyFromRaw a `mplus` apolAbbrev a
  ncount <- tryRead "node count" n
  disk <- annotateResult "disk size" (parseUnit d)
  mem <- annotateResult "memory size" (parseUnit m)
  cpu <- tryRead "cpu count" c
  spindles <- tryRead "spindles" s
  excl_stor <- tryRead "exclusive storage" exstor
  return (apol, ncount, disk, mem, cpu, spindles, excl_stor)

parseDesc desc [a, n, d, m, c] = parseDesc desc [a, n, d, m, c, "1"]

parseDesc desc [a, n, d, m, c, s] = parseDesc desc [a, n, d, m, c, s, "False"]

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
  (apol, ncount, disk, mem, cpu, spindles, excl_stor) <- parseDesc spec $
                                                         sepSplit ',' spec
  let nodes = map (\idx ->
                    flip Node.setMaster (grpIndex == 1 && idx == 1) $
                    Node.create (printf "node-%02d-%03d" grpIndex idx)
                      (fromIntegral mem) 0 mem
                      (fromIntegral disk) disk
                      (fromIntegral cpu) 1 False spindles 0 grpIndex excl_stor
                  ) [1..ncount]
      -- TODO: parse networks to which this group is connected
      grp = Group.create (printf "group-%02d" grpIndex)
            (printf "fake-uuid-%02d" grpIndex) apol [] defIPolicy []
  return (Group.setIdx grp grpIndex, nodes)

-- | Builds the cluster data from node\/instance files.
parseData :: [String] -- ^ Cluster description in text format
          -> Result ClusterData
parseData ndata = do
  grpNodeData <- zipWithM createGroup [1..] ndata
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

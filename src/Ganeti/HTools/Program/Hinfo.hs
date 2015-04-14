{-| Cluster information printer.

-}

{-

Copyright (C) 2012 Google Inc.
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

module Ganeti.HTools.Program.Hinfo
  ( main
  , options
  , arguments
  ) where

import Control.Monad
import Data.List
import System.IO

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Utils as ClusterUtils
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance

import Ganeti.Common
import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Loader
import Ganeti.Utils

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ oPrintNodes
    , oPrintInsts
    , oDataFile
    , oRapiMaster
    , luxi
    , oIAllocSrc
    , oVerbose
    , oQuiet
    , oOfflineNode
    , oIgnoreDyn
    , oMonD
    , oMonDDataFile
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Group information data-type.
data GroupInfo = GroupInfo { giName      :: String
                           , giNodeCount :: Int
                           , giInstCount :: Int
                           , giBadNodes  :: Int
                           , giBadInsts  :: Int
                           , giN1Status  :: Bool
                           , giScore     :: Double
                           }

-- | Node group statistics.
calcGroupInfo :: Group.Group
              -> Node.List
              -> Instance.List
              -> GroupInfo
calcGroupInfo g nl il =
  let nl_size                    = Container.size nl
      il_size                    = Container.size il
      (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
      bn_size                    = length bad_nodes
      bi_size                    = length bad_instances
      n1h                        = bn_size == 0
      score                      = Metrics.compCV nl
  in GroupInfo (Group.name g) nl_size il_size bn_size bi_size n1h score

-- | Helper to format one group row result.
groupRowFormatHelper :: GroupInfo -> [String]
groupRowFormatHelper gi =
  [ giName gi
  , printf "%d" $ giNodeCount gi
  , printf "%d" $ giInstCount gi
  , printf "%d" $ giBadNodes gi
  , printf "%d" $ giBadInsts gi
  , show $ giN1Status gi
  , printf "%.8f" $ giScore gi
  ]

-- | Print node group information.
showGroupInfo :: Int -> Group.List -> Node.List -> Instance.List -> IO ()
showGroupInfo verbose gl nl il = do
  let cgrs   = map (\(gdx, (gnl, gil)) ->
                 calcGroupInfo (Container.find gdx gl) gnl gil) $
                 ClusterUtils.splitCluster nl il
      cn1h   = all giN1Status cgrs
      grs    = map groupRowFormatHelper cgrs
      header = ["Group", "Nodes", "Instances", "Bad_Nodes", "Bad_Instances",
                "N+1", "Score"]

  when (verbose > 1) $
    printf "Node group information:\n%s"
           (printTable "  " header grs [False, True, True, True, True,
                                        False, True])

  printf "Cluster is N+1 %s\n" $ if cn1h then "happy" else "unhappy"

-- | Gather and print split instances.
splitInstancesInfo :: Int -> Node.List -> Instance.List -> IO ()
splitInstancesInfo verbose nl il = do
  let split_insts = Cluster.findSplitInstances nl il
  if null split_insts
    then
      when (verbose > 1) $
        putStrLn "No split instances found"::IO ()
    else do
      putStrLn "Found instances belonging to multiple node groups:"
      mapM_ (\i -> hPutStrLn stderr $ "  " ++ Instance.name i) split_insts

-- | Print common (interesting) information.
commonInfo :: Int -> Group.List -> Node.List -> Instance.List -> IO ()
commonInfo verbose gl nl il = do
  when (Container.null il && verbose > 1) $
    printf "Cluster is empty.\n"::IO ()

  let nl_size = Container.size nl
      il_size = Container.size il
      gl_size = Container.size gl
  printf "Loaded %d %s, %d %s, %d %s\n"
             nl_size (plural nl_size "node" "nodes")
             il_size (plural il_size "instance" "instances")
             gl_size (plural gl_size "node group" "node groups")::IO ()

  let csf = commonSuffix nl il
  when (not (null csf) && verbose > 2) $
       printf "Note: Stripping common suffix of '%s' from names\n" csf

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ exitErr "This program doesn't take any arguments."

  let verbose = optVerbose opts
      shownodes = optShowNodes opts
      showinsts = optShowInsts opts

  (ClusterData gl fixed_nl ilf ctags ipol) <- loadExternalData opts

  putStrLn $ "Loaded cluster tags: " ++ intercalate "," ctags

  when (verbose > 2) .
       putStrLn $ "Loaded cluster ipolicy: " ++ show ipol

  nlf <- setNodeStatus opts fixed_nl

  commonInfo verbose gl nlf ilf

  splitInstancesInfo verbose nlf ilf

  showGroupInfo verbose gl nlf ilf

  maybePrintInsts showinsts "Instances" (Cluster.printInsts nlf ilf)

  maybePrintNodes shownodes "Cluster" (Cluster.printNodes nlf)

  printf "Cluster coefficients:\n%s" (Metrics.printStats "  " nlf)::IO ()
  printf "Cluster score: %.8f\n" (Metrics.compCV nlf)

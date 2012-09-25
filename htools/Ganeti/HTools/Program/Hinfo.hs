{-| Cluster information printer.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.HTools.Program.Hinfo (main, options) where

import Control.Monad
import Data.List
import System.Exit
import System.IO

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance

import Ganeti.HTools.Utils
import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Loader

-- | Options list and functions.
options :: [OptType]
options =
  [ oPrintNodes
  , oPrintInsts
  , oDataFile
  , oRapiMaster
  , oLuxiSocket
  , oIAllocSrc
  , oVerbose
  , oQuiet
  , oOfflineNode
  ]

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
      score                      = Cluster.compCV nl
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
                 Cluster.splitCluster nl il
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
  unless (null args) $ do
         hPutStrLn stderr "Error: this program doesn't take any arguments."
         exitWith $ ExitFailure 1

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

  printf "Cluster coefficients:\n%s" (Cluster.printStats "  " nlf)::IO ()
  printf "Cluster score: %.8f\n" (Cluster.compCV nlf)

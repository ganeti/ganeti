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
import qualified Ganeti.HTools.Instance as Instance

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
  , oVerbose
  , oQuiet
  , oOfflineNode
  , oShowVer
  , oShowHelp
  ]

-- | Do a few checks on the cluster data.
checkCluster :: Int -> Node.List -> Instance.List -> IO ()
checkCluster verbose nl il = do
  -- nothing to do on an empty cluster
  when (Container.null il) $ do
         printf "Cluster is empty, exiting.\n"::IO ()
         exitWith ExitSuccess

  -- hbal doesn't currently handle split clusters
  let split_insts = Cluster.findSplitInstances nl il
  unless (null split_insts) $ do
    hPutStrLn stderr "Found instances belonging to multiple node groups:"
    mapM_ (\i -> hPutStrLn stderr $ "  " ++ Instance.name i) split_insts
    hPutStrLn stderr "Aborting."
    exitWith $ ExitFailure 1

  printf "Loaded %d nodes, %d instances\n"
             (Container.size nl)
             (Container.size il)::IO ()

  let csf = commonSuffix nl il
  when (not (null csf) && verbose > 1) $
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

  when (verbose > 1) $ do
       putStrLn $ "Loaded cluster tags: " ++ intercalate "," ctags
       putStrLn $ "Loaded cluster ipolicy: " ++ show ipol
       putStrLn $ "Loaded node groups: " ++ show gl

  nlf <- setNodeStatus opts fixed_nl
  checkCluster verbose nlf ilf

  printf "Cluster has %d node group(s)\n" (Container.size gl)::IO ()

  maybePrintInsts showinsts "Instances" (Cluster.printInsts nlf ilf)

  maybePrintNodes shownodes "Cluster" (Cluster.printNodes nlf)

  printf "Cluster coefficients:\n%s" (Cluster.printStats "  " nlf)::IO ()
  printf "Cluster score: %.8f\n" (Cluster.compCV nlf)

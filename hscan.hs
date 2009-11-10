{-| Scan clusters via RAPI and write instance/node data files.

-}

{-

Copyright (C) 2009 Google Inc.

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

module Main (main) where

import Data.List
import Data.Function
import Data.Maybe (isJust, fromJust)
import Monad
import System
import System.IO
import System.FilePath
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Rapi as Rapi
import qualified Ganeti.HTools.Loader as Loader

import Ganeti.HTools.CLI
import Ganeti.HTools.Types

-- | Options list and functions
options :: [OptType]
options =
    [ oPrintNodes
    , oOutputDir
    , oVerbose
    , oNoHeaders
    , oShowVer
    , oShowHelp
    ]

-- | Serialize a single node
serializeNode :: String -> Node.Node -> String
serializeNode csf node =
    printf "%s|%.0f|%d|%d|%.0f|%d|%.0f|%c" (Node.name node ++ csf)
               (Node.tMem node) (Node.nMem node) (Node.fMem node)
               (Node.tDsk node) (Node.fDsk node) (Node.tCpu node)
               (if Node.offline node then 'Y' else 'N')

-- | Generate node file data from node objects
serializeNodes :: String -> Node.List -> String
serializeNodes csf =
    unlines . map (serializeNode csf) . Container.elems

-- | Serialize a single instance
serializeInstance :: String -> Node.List -> Instance.Instance -> String
serializeInstance csf nl inst =
    let
        iname = Instance.name inst ++ csf
        pnode = Container.nameOf nl (Instance.pNode inst) ++ csf
        sidx = Instance.sNode inst
        snode = (if sidx == Node.noSecondary
                    then ""
                    else Container.nameOf nl sidx ++ csf)
    in
      printf "%s|%d|%d|%d|%s|%s|%s"
             iname (Instance.mem inst) (Instance.dsk inst)
             (Instance.vcpus inst) (Instance.runSt inst)
             pnode snode

-- | Generate instance file data from instance objects
serializeInstances :: String -> Node.List -> Instance.List -> String
serializeInstances csf nl =
    unlines . map (serializeInstance csf nl) . Container.elems

-- | Return a one-line summary of cluster state
printCluster :: Node.List -> Instance.List
             -> String
printCluster nl il =
    let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
        ccv = Cluster.compCV nl
        nodes = Container.elems nl
        insts = Container.elems il
        t_ram = sum . map Node.tMem $ nodes
        t_dsk = sum . map Node.tDsk $ nodes
        f_ram = sum . map Node.fMem $ nodes
        f_dsk = sum . map Node.fDsk $ nodes
    in
      printf "%5d %5d %5d %5d %6.0f %6d %6.0f %6d %.8f"
                 (length nodes) (length insts)
                 (length bad_nodes) (length bad_instances)
                 t_ram f_ram
                 (t_dsk / 1024) (f_dsk `div` 1024)
                 ccv


-- | Replace slashes with underscore for saving to filesystem

fixSlash :: String -> String
fixSlash = map (\x -> if x == '/' then '_' else x)

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, clusters) <- parseOpts cmd_args "hscan" options

  let odir = optOutPath opts
      nlen = maximum . map length $ clusters
      shownodes = optShowNodes opts

  unless (optNoHeaders opts) $
         printf "%-*s %5s %5s %5s %5s %6s %6s %6s %6s %10s\n" nlen
                "Name" "Nodes" "Inst" "BNode" "BInst" "t_mem" "f_mem"
                "t_disk" "f_disk" "Score"

  mapM_ (\ name ->
            do
              printf "%-*s " nlen name
              hFlush stdout
              input_data <- Rapi.loadData name
              let ldresult = input_data >>= Loader.mergeData []
              (case ldresult of
                 Bad err -> printf "\nError: failed to load data. \
                                   \Details:\n%s\n" err
                 Ok x -> do
                   let (nl, il, csf) = x
                       (_, fix_nl) = Loader.checkData nl il
                   putStrLn $ printCluster fix_nl il
                   when (isJust shownodes) $
                        putStr $ Cluster.printNodes fix_nl (fromJust shownodes)
                   let ndata = serializeNodes csf nl
                       idata = serializeInstances csf nl il
                       oname = odir </> fixSlash name
                   writeFile (oname <.> "nodes") ndata
                   writeFile (oname <.> "instances") idata)
       ) clusters

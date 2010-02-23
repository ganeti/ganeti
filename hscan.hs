{-# LANGUAGE CPP #-}

{-| Scan clusters via RAPI or LUXI and write state data files.

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
#ifndef NO_CURL
import qualified Ganeti.HTools.Rapi as Rapi
#endif
import qualified Ganeti.HTools.Luxi as Luxi
import qualified Ganeti.HTools.Loader as Loader

import Ganeti.HTools.CLI
import Ganeti.HTools.Types

-- | Options list and functions
options :: [OptType]
options =
    [ oPrintNodes
    , oOutputDir
    , oLuxiSocket
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
      printf "%s|%d|%d|%d|%s|%s|%s|%s"
             iname (Instance.mem inst) (Instance.dsk inst)
             (Instance.vcpus inst) (Instance.runSt inst)
             pnode snode (intercalate "," (Instance.tags inst))

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


-- | Generates serialized data from loader input
processData :: Result (Node.AssocList, Instance.AssocList, [String])
            -> Result (Node.List, Instance.List, String)
processData input_data = do
  (nl, il, _, csf) <- input_data >>= Loader.mergeData [] [] []
  let (_, fix_nl) = Loader.checkData nl il
  let ndata = serializeNodes csf nl
      idata = serializeInstances csf nl il
      adata = ndata ++ ['\n'] ++ idata
  return (fix_nl, il, adata)

-- | Writes cluster data out
writeData :: Int
          -> String
          -> Options
          -> Result (Node.List, Instance.List, String)
          -> IO ()
writeData _ name _ (Bad err) =
    printf "\nError for %s: failed to load data. Details:\n%s\n" name err

writeData nlen name opts (Ok (nl, il, adata)) = do
  printf "%-*s " nlen name
  hFlush stdout
  let shownodes = optShowNodes opts
      odir = optOutPath opts
      oname = odir </> fixSlash name
  putStrLn $ printCluster nl il
  hFlush stdout
  when (isJust shownodes) $
       putStr $ Cluster.printNodes nl (fromJust shownodes)
  writeFile (oname <.> "data") adata


-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, clusters) <- parseOpts cmd_args "hscan" options
  let local = "LOCAL"

  let nlen = if null clusters
             then length local
             else maximum . map length $ clusters

  unless (optNoHeaders opts) $
         printf "%-*s %5s %5s %5s %5s %6s %6s %6s %6s %10s\n" nlen
                "Name" "Nodes" "Inst" "BNode" "BInst" "t_mem" "f_mem"
                "t_disk" "f_disk" "Score"

  when (null clusters) $ do
         let lsock = case optLuxi opts of
                       Just s -> s
                       Nothing -> defaultLuxiSocket
         let name = local
         input_data <- Luxi.loadData lsock
         writeData nlen name opts (processData input_data)

#ifndef NO_CURL
  mapM_ (\ name ->
            do
              input_data <- Rapi.loadData name
              writeData nlen name opts (processData input_data)
        ) clusters
#else
  when (not $ null clusters) $ do
    putStrLn "RAPI/curl backend disabled at compile time, cannot scan clusters"
    exitWith $ ExitFailure 1
#endif

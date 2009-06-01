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
import Monad
import System
import System.IO
import System.FilePath
import System.Console.GetOpt
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Rapi as Rapi
import qualified Ganeti.HTools.Loader as Loader
import Ganeti.HTools.Types

-- | Command line options structure.
data Options = Options
    { optShowNodes :: Bool     -- ^ Whether to show node status
    , optOutPath   :: FilePath -- ^ Path to the output directory
    , optVerbose   :: Int      -- ^ Verbosity level
    , optNoHeader  :: Bool     -- ^ Do not show a header line
    , optShowVer   :: Bool     -- ^ Just show the program version
    , optShowHelp  :: Bool     -- ^ Just show the help
    } deriving Show

instance CLI.CLIOptions Options where
    showVersion = optShowVer
    showHelp    = optShowHelp

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowNodes = False
 , optOutPath   = "."
 , optVerbose   = 0
 , optNoHeader  = False
 , optShowVer   = False
 , optShowHelp  = False
 }

-- | Options list and functions
options :: [OptDescr (Options -> Options)]
options =
    [ Option ['p']     ["print-nodes"]
      (NoArg (\ opts -> opts { optShowNodes = True }))
      "print the final node list"
    , Option ['d']     ["output-dir"]
      (ReqArg (\ d opts -> opts { optOutPath = d }) "PATH")
      "directory in which to write output files"
    , Option ['v']     ["verbose"]
      (NoArg (\ opts -> opts { optVerbose = (optVerbose opts) + 1 }))
      "increase the verbosity level"
    , Option []        ["no-headers"]
      (NoArg (\ opts -> opts { optNoHeader = True }))
      "do not show a header line"
    , Option ['V']     ["version"]
      (NoArg (\ opts -> opts { optShowVer = True}))
      "show the version of the program"
    , Option ['h']     ["help"]
      (NoArg (\ opts -> opts { optShowHelp = True}))
      "show help"
    ]

-- | Generate node file data from node objects
serializeNodes :: Node.List -> String -> String
serializeNodes nl csf =
    let nodes = Container.elems nl
        nlines = map
                 (\node ->
                      let name = Node.name node ++ csf
                          t_mem = (truncate $ Node.t_mem node)::Int
                          t_dsk = (truncate $ Node.t_dsk node)::Int
                      in
                        printf "%s|%d|%d|%d|%d|%d|%c" name
                                   t_mem (Node.n_mem node) (Node.f_mem node)
                                   t_dsk (Node.f_dsk node)
                                   (if Node.offline node then 'Y' else 'N')
                 )
                 nodes
    in unlines nlines

-- | Generate instance file data from instance objects
serializeInstances :: Node.List -> Instance.List
                   -> String -> String
serializeInstances nl il csf =
    let instances = Container.elems il
        nlines = map
                 (\inst ->
                      let
                          iname = Instance.name inst ++ csf
                          pnode = Container.nameOf nl $ Instance.pnode inst
                          snode = Container.nameOf nl $ Instance.snode inst
                      in
                        printf "%s|%d|%d|%s|%s|%s"
                               iname (Instance.mem inst) (Instance.dsk inst)
                               (Instance.run_st inst)
                               pnode snode
                 )
                 instances
    in unlines nlines

-- | Return a one-line summary of cluster state
printCluster :: Node.List -> Instance.List
             -> String
printCluster nl il =
    let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
        ccv = Cluster.compCV nl
        nodes = Container.elems nl
        insts = Container.elems il
        t_ram = truncate . sum . map Node.t_mem $ nodes
        t_dsk = truncate . sum . map Node.t_dsk $ nodes
        f_ram = sum . map Node.f_mem $ nodes
        f_dsk = sum . map Node.f_dsk $ nodes
    in
      printf "%5d %5d %5d %5d %6d %6d %6d %6d %.8f"
                 (length nodes) (length insts)
                 (length bad_nodes) (length bad_instances)
                 (t_ram::Integer) f_ram
                 ((t_dsk::Integer) `div` 1024) (f_dsk `div` 1024)
                 ccv


-- | Replace slashes with underscore for saving to filesystem

fixSlash :: String -> String
fixSlash = map (\x -> if x == '/' then '_' else x)

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, clusters) <- CLI.parseOpts cmd_args "hscan" options
                      defaultOptions

  let odir = optOutPath opts
      nlen = maximum . map length $ clusters

  unless (optNoHeader opts) $
         printf "%-*s %5s %5s %5s %5s %6s %6s %6s %6s %10s\n" nlen
                "Name" "Nodes" "Inst" "BNode" "BInst" "t_mem" "f_mem"
                "t_disk" "f_disk" "Score"

  mapM_ (\ name ->
            do
              printf "%-*s " nlen name
              hFlush stdout
              input_data <- Rapi.loadData name
              let ldresult = input_data >>= Loader.mergeData
              (case ldresult of
                 Bad err -> printf "\nError: failed to load data. \
                                   \Details:\n%s\n" err
                 Ok x -> do
                   let (nl, il, csf) = x
                       (_, fix_nl) = Loader.checkData nl il
                   putStrLn $ printCluster fix_nl il
                   when (optShowNodes opts) $ do
                           putStr $ Cluster.printNodes fix_nl
                   let ndata = serializeNodes nl csf
                       idata = serializeInstances nl il csf
                       oname = odir </> (fixSlash name)
                   writeFile (oname <.> "nodes") ndata
                   writeFile (oname <.> "instances") idata)
       ) clusters

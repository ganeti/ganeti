{-| Cluster space sizing

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
import Data.Maybe (isJust, fromJust, isNothing)
import Monad
import System
import System.IO
import System.Console.GetOpt
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.CLI as CLI

import Ganeti.HTools.Utils

-- | Command line options structure.
data Options = Options
    { optShowNodes :: Bool           -- ^ Whether to show node status
    , optNodef     :: FilePath       -- ^ Path to the nodes file
    , optNodeSet   :: Bool           -- ^ The nodes have been set by options
    , optInstf     :: FilePath       -- ^ Path to the instances file
    , optInstSet   :: Bool           -- ^ The insts have been set by options
    , optMaster    :: String         -- ^ Collect data from RAPI
    , optVerbose   :: Int            -- ^ Verbosity level
    , optOffline   :: [String]       -- ^ Names of offline nodes
    , optIMem      :: Int            -- ^ Instance memory
    , optIDsk      :: Int            -- ^ Instance disk
    , optIVCPUs    :: Int            -- ^ Instance VCPUs
    , optINodes    :: Int            -- ^ Nodes required for an instance
    , optMcpu      :: Double         -- ^ Max cpu ratio for nodes
    , optMdsk      :: Double         -- ^ Max disk usage ratio for nodes
    , optShowVer   :: Bool           -- ^ Just show the program version
    , optShowHelp  :: Bool           -- ^ Just show the help
    } deriving Show

instance CLI.CLIOptions Options where
    showVersion = optShowVer
    showHelp    = optShowHelp

instance CLI.EToolOptions Options where
    nodeFile   = optNodef
    nodeSet    = optNodeSet
    instFile   = optInstf
    instSet    = optInstSet
    masterName = optMaster
    silent a   = (optVerbose a) == 0

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowNodes = False
 , optNodef     = "nodes"
 , optNodeSet   = False
 , optInstf     = "instances"
 , optInstSet   = False
 , optMaster    = ""
 , optVerbose   = 1
 , optOffline   = []
 , optIMem      = 4096
 , optIDsk      = 102400
 , optIVCPUs    = 1
 , optINodes    = 2
 , optMcpu      = -1
 , optMdsk      = -1
 , optShowVer   = False
 , optShowHelp  = False
 }

-- | Options list and functions
options :: [OptDescr (Options -> Options)]
options =
    [ Option ['p']     ["print-nodes"]
      (NoArg (\ opts -> opts { optShowNodes = True }))
      "print the final node list"
    , Option ['n']     ["nodes"]
      (ReqArg (\ f opts -> opts { optNodef = f, optNodeSet = True }) "FILE")
      "the node list FILE"
    , Option ['i']     ["instances"]
      (ReqArg (\ f opts -> opts { optInstf =  f, optInstSet = True }) "FILE")
      "the instance list FILE"
    , Option ['m']     ["master"]
      (ReqArg (\ m opts -> opts { optMaster = m }) "ADDRESS")
      "collect data via RAPI at the given ADDRESS"
    , Option ['v']     ["verbose"]
      (NoArg (\ opts -> opts { optVerbose = (optVerbose opts) + 1 }))
      "increase the verbosity level"
    , Option ['q']     ["quiet"]
      (NoArg (\ opts -> opts { optVerbose = (optVerbose opts) - 1 }))
      "decrease the verbosity level"
    , Option ['O']     ["offline"]
      (ReqArg (\ n opts -> opts { optOffline = n:optOffline opts }) "NODE")
      "set node as offline"
    , Option []        ["memory"]
      (ReqArg (\ m opts -> opts { optIMem = read m }) "MEMORY")
      "memory size for instances"
    , Option []        ["disk"]
      (ReqArg (\ d opts -> opts { optIDsk = read d }) "DISK")
      "disk size for instances"
    , Option []        ["vcpus"]
      (ReqArg (\ p opts -> opts { optIVCPUs = read p }) "NUM")
      "number of virtual cpus for instances"
    , Option []        ["req-nodes"]
      (ReqArg (\ n opts -> opts { optINodes = read n }) "NODES")
      "number of nodes for the new instances (1=plain, 2=mirrored)"
    , Option []        ["max-cpu"]
      (ReqArg (\ n opts -> opts { optMcpu = read n }) "RATIO")
      "maximum virtual-to-physical cpu ratio for nodes"
    , Option []        ["min-disk"]
      (ReqArg (\ n opts -> opts { optMdsk = read n }) "RATIO")
      "minimum free disk space for nodes (between 0 and 1)"
    , Option ['V']     ["version"]
      (NoArg (\ opts -> opts { optShowVer = True}))
      "show the version of the program"
    , Option ['h']     ["help"]
      (NoArg (\ opts -> opts { optShowHelp = True}))
      "show help"
    ]

filterFails :: Cluster.AllocSolution
            -> Maybe [(Node.List, Instance.Instance, [Node.Node])]
filterFails sols =
    if null sols then Nothing -- No nodes onto which to allocate at all
    else let sols' = filter (isJust . fst3) sols
         in if null sols' then
                Nothing -- No valid allocation solutions
            else
                return $ map (\(x, y, z) -> (fromJust x, y, z)) sols'

processResults :: (Monad m) => [(Node.List, Instance.Instance, [Node.Node])]
               -> m (Node.List, Instance.Instance, [Node.Node])
processResults sols =
    let sols' = map (\e@(nl', _, _) -> (Cluster.compCV  nl', e)) sols
        sols'' = sortBy (compare `on` fst) sols'
    in return $ snd $ head sols''

iterateDepth :: Node.List
             -> Instance.List
             -> Instance.Instance
             -> Int
             -> [Instance.Instance]
             -> (Node.List, [Instance.Instance])
iterateDepth nl il newinst nreq ixes =
      let depth = length ixes
          newname = (printf "new-%d" depth)::String
          newidx = (length $ Container.elems il) + depth
          newi2 = Instance.setIdx (Instance.setName newinst newname) newidx
          sols = (Cluster.tryAlloc nl il newi2 nreq)::
                 Maybe Cluster.AllocSolution
          orig = (nl, ixes)
      in
        if isNothing sols then orig
        else let sols' = fromJust sols
                 sols'' = filterFails sols'
             in if isNothing sols'' then orig
                else let (xnl, xi, _) = fromJust $ processResults $
                                        fromJust sols''
                     in iterateDepth xnl il newinst nreq (xi:ixes)

printStats :: String -> Cluster.CStats -> IO ()
printStats kind cs = do
  printf "%s free RAM: %d\n" kind (Cluster.cs_fmem cs)
  printf "%s allocatable RAM: %d\n" kind (Cluster.cs_amem cs)
  printf "%s reserved RAM: %d\n" kind ((Cluster.cs_fmem cs) -
                                       (Cluster.cs_amem cs))
  printf "%s free disk: %d\n" kind (Cluster.cs_fdsk cs)
  printf "%s allocatable disk: %d\n" kind (Cluster.cs_adsk cs)
  printf "%s reserved disk: %d\n" kind ((Cluster.cs_fdsk cs) -
                                        (Cluster.cs_adsk cs))
  printf "%s max node allocatable RAM: %d\n" kind (Cluster.cs_mmem cs)
  printf "%s max node allocatable disk: %d\n" kind (Cluster.cs_mdsk cs)

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, args) <- CLI.parseOpts cmd_args "hspace" options defaultOptions

  unless (null args) $ do
         hPutStrLn stderr "Error: this program doesn't take any arguments."
         exitWith $ ExitFailure 1

  let verbose = optVerbose opts

  (fixed_nl, il, csf) <- CLI.loadExternalData opts
  let num_instances = length $ Container.elems il

  let offline_names = optOffline opts
      all_nodes = Container.elems fixed_nl
      all_names = map Node.name all_nodes
      offline_wrong = filter (\n -> not $ elem n all_names) offline_names
      offline_indices = map Node.idx $
                        filter (\n -> elem (Node.name n) offline_names)
                               all_nodes
      req_nodes = optINodes opts
      m_cpu = optMcpu opts
      m_dsk = optMdsk opts

  when (length offline_wrong > 0) $ do
         printf "Error: Wrong node name(s) set as offline: %s\n"
                (commaJoin offline_wrong)
         exitWith $ ExitFailure 1

  when (req_nodes /= 1 && req_nodes /= 2) $ do
         printf "Error: Invalid required nodes (%d)\n" req_nodes
         exitWith $ ExitFailure 1

  let nm = Container.map (\n -> if elem (Node.idx n) offline_indices
                                then Node.setOffline n True
                                else n) fixed_nl
      nl = Container.map (flip Node.setMdsk m_dsk . flip Node.setMcpu m_cpu)
           nm

  when (length csf > 0 && verbose > 1) $ do
         printf "Note: Stripping common suffix of '%s' from names\n" csf

  let bad_nodes = fst $ Cluster.computeBadItems nl il
  when (length bad_nodes > 0) $ do
         putStrLn "Error: Cluster not N+1, no space to allocate."
         exitWith $ ExitFailure 1

  when (optShowNodes opts) $
       do
         putStrLn "Initial cluster status:"
         putStrLn $ Cluster.printNodes nl

  let ini_cv = Cluster.compCV nl
      ini_stats = Cluster.totalResources nl

  (if verbose > 2 then
       printf "Initial coefficients: overall %.8f, %s\n"
       ini_cv (Cluster.printStats nl)
   else
       printf "Initial score: %.8f\n" ini_cv)
  printf "Initial instances: %d\n" num_instances
  printStats "Initial" ini_stats

  let nmlen = Container.maxNameLen nl
      newinst = Instance.create "new" (optIMem opts) (optIDsk opts)
                (optIVCPUs opts) "ADMIN_down" (-1) (-1)

  let (fin_nl, ixes) = iterateDepth nl il newinst req_nodes []
      allocs = length ixes
      fin_instances = num_instances + allocs
      fin_ixes = reverse ixes
      ix_namelen = maximum . map (length . Instance.name) $ fin_ixes
      fin_stats = Cluster.totalResources fin_nl

  printf "Final score: %.8f\n" (Cluster.compCV fin_nl)
  printf "Final instances: %d\n" (num_instances + allocs)
  printStats "Final" fin_stats
  printf "Usage: %.5f\n" (((fromIntegral num_instances)::Double) /
                          (fromIntegral fin_instances))
  printf "Allocations: %d\n" allocs
  when (verbose > 1) $ do
         putStr . unlines . map (\i -> printf "Inst: %*s %-*s %-*s"
                     ix_namelen (Instance.name i)
                     nmlen (Container.nameOf fin_nl $ Instance.pnode i)
                     nmlen (let sdx = Instance.snode i
                            in if sdx == Node.noSecondary then ""
                               else Container.nameOf fin_nl sdx))
         $ fin_ixes

  when (optShowNodes opts) $
       do
         putStrLn ""
         putStrLn "Final cluster status:"
         putStrLn $ Cluster.printNodes fin_nl

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
import Monad
import System
import System.IO
import System.Console.GetOpt
import qualified System

import Text.Printf (printf, hPrintf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.CLI as CLI

import Ganeti.HTools.Utils
import Ganeti.HTools.Types

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
    silent a   = optVerbose a == 0

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
      (NoArg (\ opts -> opts { optVerbose = optVerbose opts + 1 }))
      "increase the verbosity level"
    , Option ['q']     ["quiet"]
      (NoArg (\ opts -> opts { optVerbose = optVerbose opts - 1 }))
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

-- | Build failure stats out of a list of failure reasons
concatFailure :: [(FailMode, Int)] -> FailMode -> [(FailMode, Int)]
concatFailure flst reason =
    let cval = lookup reason flst
    in case cval of
         Nothing -> (reason, 1):flst
         Just val -> let plain = filter (\(x, _) -> x /= reason) flst
                     in (reason, val+1):plain

-- | Build list of failures and placements out of an list of possible
-- | allocations
filterFails :: Cluster.AllocSolution
            -> ([(FailMode, Int)],
                [(Node.List, Instance.Instance, [Node.Node])])
filterFails sols =
    let (alst, blst) = unzip . map (\ (onl, i, nn) ->
                                        case onl of
                                          OpFail reason -> ([reason], [])
                                          OpGood gnl -> ([], [(gnl, i, nn)])
                                   ) $ sols
        aval = concat alst
        bval = concat blst
    in (foldl' concatFailure [] aval, bval)

-- | Get the placement with best score out of a list of possible placements
processResults :: [(Node.List, Instance.Instance, [Node.Node])]
               -> (Node.List, Instance.Instance, [Node.Node])
processResults sols =
    let sols' = map (\e@(nl', _, _) -> (Cluster.compCV  nl', e)) sols
        sols'' = sortBy (compare `on` fst) sols'
    in snd $ head sols''

-- | Recursively place instances on the cluster until we're out of space
iterateDepth :: Node.List
             -> Instance.List
             -> Instance.Instance
             -> Int
             -> [Instance.Instance]
             -> ([(FailMode, Int)], Node.List, [Instance.Instance])
iterateDepth nl il newinst nreq ixes =
      let depth = length ixes
          newname = printf "new-%d" depth::String
          newidx = length (Container.elems il) + depth
          newi2 = Instance.setIdx (Instance.setName newinst newname) newidx
          sols = Cluster.tryAlloc nl il newi2 nreq::
                 OpResult Cluster.AllocSolution
      in case sols of
           OpFail _ -> ([], nl, ixes)
           OpGood sols' ->
               let (errs, sols3) = filterFails sols'
               in if null sols3
                  then (errs, nl, ixes)
                  else let (xnl, xi, _) = processResults sols3
                       in iterateDepth xnl il newinst nreq (xi:ixes)

-- | Function to print stats for a given phase
printStats :: String -> Cluster.CStats -> IO ()
printStats kind cs = do
  printf "%s score: %.8f\n" kind (Cluster.cs_score cs)
  printf "%s instances: %d\n" kind (Cluster.cs_ninst cs)
  printf "%s free RAM: %d\n" kind (Cluster.cs_fmem cs)
  printf "%s allocatable RAM: %d\n" kind (Cluster.cs_amem cs)
  printf "%s reserved RAM: %d\n" kind (Cluster.cs_fmem cs -
                                       Cluster.cs_amem cs)
  printf "%s instance RAM: %d\n" kind (Cluster.cs_imem cs)
  printf "%s overhead RAM: %d\n" kind (Cluster.cs_xmem cs + Cluster.cs_nmem cs)
  printf "%s RAM usage efficiency: %.8f\n"
         kind (fromIntegral (Cluster.cs_imem cs) / Cluster.cs_tmem cs)
  printf "%s free disk: %d\n" kind (Cluster.cs_fdsk cs)
  printf "%s allocatable disk: %d\n" kind (Cluster.cs_adsk cs)
  printf "%s reserved disk: %d\n" kind (Cluster.cs_fdsk cs -
                                        Cluster.cs_adsk cs)
  printf "%s instance disk: %d\n" kind (Cluster.cs_idsk cs)
  printf "%s disk usage efficiency: %.8f\n"
         kind (fromIntegral (Cluster.cs_idsk cs) / Cluster.cs_tdsk cs)
  printf "%s instance cpus: %d\n" kind (Cluster.cs_icpu cs)
  printf "%s cpu usage efficiency: %.8f\n"
         kind (fromIntegral (Cluster.cs_icpu cs) / Cluster.cs_tcpu cs)
  printf "%s max node allocatable RAM: %d\n" kind (Cluster.cs_mmem cs)
  printf "%s max node allocatable disk: %d\n" kind (Cluster.cs_mdsk cs)

-- | Print final stats and related metrics
printResults :: Node.List -> Int -> Int -> [(FailMode, Int)] -> IO ()
printResults fin_nl num_instances allocs sreason = do
  let fin_stats = Cluster.totalResources fin_nl
      fin_instances = num_instances + allocs

  when (num_instances + allocs /= Cluster.cs_ninst fin_stats) $
       do
         hPrintf stderr "ERROR: internal inconsistency, allocated (%d)\
                        \ != counted (%d)\n" (num_instances + allocs)
                                 (Cluster.cs_ninst fin_stats)
         exitWith $ ExitFailure 1

  printStats "Final" fin_stats
  printf "Usage: %.5f\n" ((fromIntegral num_instances::Double) /
                          fromIntegral fin_instances)
  printf "Allocations: %d\n" allocs
  putStr (unlines . map (\(x, y) -> printf "%s: %d" (show x) y) $ sreason)
  printf "Most likely fail reason: %s\n" (show . fst . head $ sreason)

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

  printf "Spec RAM: %d\n" (optIMem opts)
  printf "Spec disk: %d\n" (optIDsk opts)
  printf "Spec CPUs: %d\n" (optIVCPUs opts)
  printf "Spec nodes: %d\n" (optINodes opts)

  let num_instances = length $ Container.elems il

  let offline_names = optOffline opts
      all_nodes = Container.elems fixed_nl
      all_names = map Node.name all_nodes
      offline_wrong = filter (flip notElem all_names) offline_names
      offline_indices = map Node.idx $
                        filter (\n -> elem (Node.name n) offline_names)
                               all_nodes
      req_nodes = optINodes opts
      m_cpu = optMcpu opts
      m_dsk = optMdsk opts

  when (length offline_wrong > 0) $ do
         hPrintf stderr "Error: Wrong node name(s) set as offline: %s\n"
                     (commaJoin offline_wrong)
         exitWith $ ExitFailure 1

  when (req_nodes /= 1 && req_nodes /= 2) $ do
         hPrintf stderr "Error: Invalid required nodes (%d)\n" req_nodes
         exitWith $ ExitFailure 1

  let nm = Container.map (\n -> if elem (Node.idx n) offline_indices
                                then Node.setOffline n True
                                else n) fixed_nl
      nl = Container.map (flip Node.setMdsk m_dsk . flip Node.setMcpu m_cpu)
           nm

  when (length csf > 0 && verbose > 1) $
       printf "Note: Stripping common suffix of '%s' from names\n" csf

  when (optShowNodes opts) $
       do
         putStrLn "Initial cluster status:"
         putStrLn $ Cluster.printNodes nl

  let ini_cv = Cluster.compCV nl
      ini_stats = Cluster.totalResources nl

  when (verbose > 2) $ do
         printf "Initial coefficients: overall %.8f, %s\n"
                ini_cv (Cluster.printStats nl)

  printf "Cluster RAM: %.0f\n" (Cluster.cs_tmem ini_stats)
  printf "Cluster disk: %.0f\n" (Cluster.cs_tdsk ini_stats)
  printf "Cluster cpus: %.0f\n" (Cluster.cs_tcpu ini_stats)
  printStats "Initial" ini_stats

  let bad_nodes = fst $ Cluster.computeBadItems nl il
  when (length bad_nodes > 0) $ do
         -- This is failn1 case, so we print the same final stats and
         -- exit early
         printResults nl num_instances 0 [(FailN1, 1)]
         exitWith ExitSuccess

  let nmlen = Container.maxNameLen nl
      newinst = Instance.create "new" (optIMem opts) (optIDsk opts)
                (optIVCPUs opts) "ADMIN_down" (-1) (-1)

  let (ereason, fin_nl, ixes) = iterateDepth nl il newinst req_nodes []
      allocs = length ixes
      fin_ixes = reverse ixes
      ix_namelen = maximum . map (length . Instance.name) $ fin_ixes
      sreason = reverse $ sortBy (compare `on` snd) ereason

  printResults fin_nl num_instances allocs sreason

  when (verbose > 1) $
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

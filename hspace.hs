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

import Data.Char (toUpper)
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

data Phase = PInitial | PFinal

statsData :: [(String, Cluster.CStats -> String)]
statsData = [ ("SCORE", printf "%.8f" . Cluster.cs_score)
            , ("INST_CNT", printf "%d" . Cluster.cs_ninst)
            , ("MEM_FREE", printf "%d" . Cluster.cs_fmem)
            , ("MEM_AVAIL", printf "%d" . Cluster.cs_amem)
            , ("MEM_RESVD",
               \cs -> printf "%d" (Cluster.cs_fmem cs - Cluster.cs_amem cs))
            , ("MEM_INST", printf "%d" . Cluster.cs_imem)
            , ("MEM_OVERHEAD",
               \cs -> printf "%d" (Cluster.cs_xmem cs + Cluster.cs_nmem cs))
            , ("MEM_EFF",
               \cs -> printf "%.8f" (fromIntegral (Cluster.cs_imem cs) /
                                     Cluster.cs_tmem cs))
            , ("DSK_FREE", printf "%d" . Cluster.cs_fdsk)
            , ("DSK_AVAIL", printf "%d ". Cluster.cs_adsk)
            , ("DSK_RESVD",
               \cs -> printf "%d" (Cluster.cs_fdsk cs - Cluster.cs_adsk cs))
            , ("DSK_INST", printf "%d" . Cluster.cs_idsk)
            , ("DSK_EFF",
               \cs -> printf "%.8f" (fromIntegral (Cluster.cs_idsk cs) /
                                    Cluster.cs_tdsk cs))
            , ("CPU_INST", printf "%d" . Cluster.cs_icpu)
            , ("CPU_EFF",
               \cs -> printf "%.8f" (fromIntegral (Cluster.cs_icpu cs) /
                                     Cluster.cs_tcpu cs))
            , ("MNODE_MEM_AVAIL", printf "%d" . Cluster.cs_mmem)
            , ("MNODE_DSK_AVAIL", printf "%d" . Cluster.cs_mdsk)
            ]

specData :: [(String, Options -> String)]
specData = [ ("MEM", printf "%d" . optIMem)
           , ("DSK", printf "%d" . optIDsk)
           , ("CPU", printf "%d" . optIVCPUs)
           , ("RQN", printf "%d" . optINodes)
           ]

clusterData :: [(String, Cluster.CStats -> String)]
clusterData = [ ("MEM", printf "%.0f" . Cluster.cs_tmem)
              , ("DSK", printf "%.0f" . Cluster.cs_tdsk)
              , ("CPU", printf "%.0f" . Cluster.cs_tcpu)
              ]

-- | Recursively place instances on the cluster until we're out of space
iterateDepth :: Node.List
             -> Instance.List
             -> Instance.Instance
             -> Int
             -> [Instance.Instance]
             -> Result (FailStats, Node.List, [Instance.Instance])
iterateDepth nl il newinst nreq ixes =
      let depth = length ixes
          newname = printf "new-%d" depth::String
          newidx = length (Container.elems il) + depth
          newi2 = Instance.setIdx (Instance.setName newinst newname) newidx
      in case Cluster.tryAlloc nl il newi2 nreq of
           Bad s -> Bad s
           Ok (errs, _, sols3) ->
               case sols3 of
                 Nothing -> Ok (Cluster.collapseFailures errs, nl, ixes)
                 Just (_, (xnl, xi, _)) ->
                     iterateDepth xnl il newinst nreq $! (xi:ixes)

-- | Function to print stats for a given phase
printStats :: Phase -> Cluster.CStats -> [(String, String)]
printStats ph cs =
  map (\(s, fn) -> (printf "%s_%s" kind s, fn cs)) statsData
  where kind = case ph of
                 PInitial -> "INI"
                 PFinal -> "FIN"

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

  printKeys $ printStats PFinal fin_stats
  printKeys [ ("ALLOC_USAGE", printf "%.8f"
                                ((fromIntegral num_instances::Double) /
                                 fromIntegral fin_instances))
            , ("ALLOC_INSTANCES", printf "%d" allocs)
            , ("ALLOC_FAIL_REASON", map toUpper . show . fst $ head sreason)
            ]
  printKeys $ map (\(x, y) -> (printf "ALLOC_%s_CNT" (show x),
                               printf "%d" y)) sreason
  -- this should be the final entry
  printKeys [("OK", "1")]

-- | Format a list of key/values as a shell fragment
printKeys :: [(String, String)] -> IO ()
printKeys = mapM_ (\(k, v) -> printf "HTS_%s=%s\n" (map toUpper k) v)

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

  printKeys $ map (\(a, fn) -> ("SPEC_" ++ a, fn opts)) specData

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
       hPrintf stderr "Note: Stripping common suffix of '%s' from names\n" csf

  when (optShowNodes opts) $
       do
         hPutStrLn stderr "Initial cluster status:"
         hPutStrLn stderr $ Cluster.printNodes nl

  let ini_cv = Cluster.compCV nl
      ini_stats = Cluster.totalResources nl

  when (verbose > 2) $ do
         hPrintf stderr "Initial coefficients: overall %.8f, %s\n"
                 ini_cv (Cluster.printStats nl)

  printKeys $ map (\(a, fn) -> ("CLUSTER_" ++ a, fn ini_stats)) clusterData
  printKeys [("CLUSTER_NODES", printf "%d" (length all_nodes))]
  printKeys $ printStats PInitial ini_stats

  let bad_nodes = fst $ Cluster.computeBadItems nl il
  when (length bad_nodes > 0) $ do
         -- This is failn1 case, so we print the same final stats and
         -- exit early
         printResults nl num_instances 0 [(FailN1, 1)]
         exitWith ExitSuccess

  let nmlen = Container.maxNameLen nl
      newinst = Instance.create "new" (optIMem opts) (optIDsk opts)
                (optIVCPUs opts) "ADMIN_down" (-1) (-1)

  let result = iterateDepth nl il newinst req_nodes []
  (ereason, fin_nl, ixes) <- (case result of
                                Bad s -> do
                                  hPrintf stderr "Failure: %s\n" s
                                  exitWith $ ExitFailure 1
                                Ok x -> return x)
  let allocs = length ixes
      fin_ixes = reverse ixes
      ix_namelen = maximum . map (length . Instance.name) $ fin_ixes
      sreason = reverse $ sortBy (compare `on` snd) ereason

  when (verbose > 1) $
         hPutStr stderr . unlines $
         map (\i -> printf "Inst: %*s %-*s %-*s"
                    ix_namelen (Instance.name i)
                    nmlen (Container.nameOf fin_nl $ Instance.pnode i)
                    nmlen (let sdx = Instance.snode i
                           in if sdx == Node.noSecondary then ""
                              else Container.nameOf fin_nl sdx)
             ) fin_ixes

  when (optShowNodes opts) $
       do
         hPutStrLn stderr ""
         hPutStrLn stderr "Final cluster status:"
         hPutStrLn stderr $ Cluster.printNodes fin_nl

  printResults fin_nl num_instances allocs sreason

{-| Cluster rebalancer

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
import Data.Maybe (isJust, fromJust, fromMaybe)
import Monad
import System
import System.IO
import System.Console.GetOpt
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.CLI as CLI

import Ganeti.HTools.Utils

-- | Command line options structure.
data Options = Options
    { optShowNodes :: Bool           -- ^ Whether to show node status
    , optShowCmds  :: Maybe FilePath -- ^ Whether to show the command list
    , optOneline   :: Bool           -- ^ Switch output to a single line
    , optNodef     :: FilePath       -- ^ Path to the nodes file
    , optNodeSet   :: Bool           -- ^ The nodes have been set by options
    , optInstf     :: FilePath       -- ^ Path to the instances file
    , optInstSet   :: Bool           -- ^ The insts have been set by options
    , optMaxLength :: Int            -- ^ Stop after this many steps
    , optMaster    :: String         -- ^ Collect data from RAPI
    , optVerbose   :: Int            -- ^ Verbosity level
    , optOffline   :: [String]       -- ^ Names of offline nodes
    , optMinScore  :: Cluster.Score  -- ^ The minimum score we aim for
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
 , optShowCmds  = Nothing
 , optOneline   = False
 , optNodef     = "nodes"
 , optNodeSet   = False
 , optInstf     = "instances"
 , optInstSet   = False
 , optMaxLength = -1
 , optMaster    = ""
 , optVerbose   = 1
 , optOffline   = []
 , optMinScore  = 1e-9
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
    , Option ['C']     ["print-commands"]
      (OptArg ((\ f opts -> opts { optShowCmds = Just f }) . fromMaybe "-")
                  "FILE")
      "print the ganeti command list for reaching the solution,\
      \if an argument is passed then write the commands to a file named\
      \ as such"
    , Option ['o']     ["oneline"]
      (NoArg (\ opts -> opts { optOneline = True }))
      "print the ganeti command list for reaching the solution"
    , Option ['n']     ["nodes"]
      (ReqArg (\ f opts -> opts { optNodef = f, optNodeSet = True }) "FILE")
      "the node list FILE"
    , Option ['i']     ["instances"]
      (ReqArg (\ f opts -> opts { optInstf =  f, optInstSet = True }) "FILE")
      "the instance list FILE"
    , Option ['m']     ["master"]
      (ReqArg (\ m opts -> opts { optMaster = m }) "ADDRESS")
      "collect data via RAPI at the given ADDRESS"
    , Option ['l']     ["max-length"]
      (ReqArg (\ i opts -> opts { optMaxLength =  (read i)::Int }) "N")
      "cap the solution at this many moves (useful for very unbalanced \
      \clusters)"
    , Option ['v']     ["verbose"]
      (NoArg (\ opts -> opts { optVerbose = (optVerbose opts) + 1 }))
      "increase the verbosity level"
    , Option ['q']     ["quiet"]
      (NoArg (\ opts -> opts { optVerbose = (optVerbose opts) - 1 }))
      "decrease the verbosity level"
    , Option ['O']     ["offline"]
      (ReqArg (\ n opts -> opts { optOffline = n:optOffline opts }) "NODE")
      " set node as offline"
    , Option ['e']     ["min-score"]
      (ReqArg (\ e opts -> opts { optMinScore = read e }) "EPSILON")
      " mininum score to aim for"
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

{- | Start computing the solution at the given depth and recurse until
we find a valid solution or we exceed the maximum depth.

-}
iterateDepth :: Cluster.Table    -- ^ The starting table
             -> Int              -- ^ Remaining length
             -> Int              -- ^ Max node name len
             -> Int              -- ^ Max instance name len
             -> [[String]]       -- ^ Current command list
             -> Bool             -- ^ Wheter to be silent
             -> Cluster.Score    -- ^ Score at which to stop
             -> IO (Cluster.Table, [[String]]) -- ^ The resulting table and
                                               -- commands
iterateDepth ini_tbl max_rounds nmlen imlen
             cmd_strs oneline min_score =
    let Cluster.Table ini_nl ini_il ini_cv ini_plc = ini_tbl
        all_inst = Container.elems ini_il
        node_idx = map Node.idx . filter (not . Node.offline) $
                   Container.elems ini_nl
        fin_tbl = Cluster.checkMove node_idx ini_tbl all_inst
        (Cluster.Table _ _ fin_cv fin_plc) = fin_tbl
        ini_plc_len = length ini_plc
        fin_plc_len = length fin_plc
        allowed_next = (max_rounds < 0 || length fin_plc < max_rounds)
    in
      do
        let
            (sol_line, cmds) = Cluster.printSolutionLine ini_nl ini_il
                               nmlen imlen (head fin_plc) fin_plc_len
            upd_cmd_strs = cmds:cmd_strs
        unless (oneline || fin_plc_len == ini_plc_len) $ do
          putStrLn sol_line
          hFlush stdout
        (if fin_cv < ini_cv then -- this round made success, try deeper
             if allowed_next && fin_cv > min_score
             then iterateDepth fin_tbl max_rounds
                  nmlen imlen upd_cmd_strs oneline min_score
             -- don't go deeper, but return the better solution
             else return (fin_tbl, upd_cmd_strs)
         else
             return (ini_tbl, cmd_strs))

-- | Formats the solution for the oneline display
formatOneline :: Double -> Int -> Double -> String
formatOneline ini_cv plc_len fin_cv =
    printf "%.8f %d %.8f %8.3f" ini_cv plc_len fin_cv
               (if fin_cv == 0 then 1 else (ini_cv / fin_cv))

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, args) <- CLI.parseOpts cmd_args "hbal" options defaultOptions

  unless (null args) $ do
         hPutStrLn stderr "Error: this program doesn't take any arguments."
         exitWith $ ExitFailure 1

  let oneline = optOneline opts
      verbose = optVerbose opts

  (fixed_nl, il, csf) <- CLI.loadExternalData opts

  let offline_names = optOffline opts
      all_nodes = Container.elems fixed_nl
      all_names = map Node.name all_nodes
      offline_wrong = filter (\n -> not $ elem n all_names) offline_names
      offline_indices = map Node.idx $
                        filter (\n -> elem (Node.name n) offline_names)
                               all_nodes
      m_cpu = optMcpu opts
      m_dsk = optMdsk opts

  when (length offline_wrong > 0) $ do
         printf "Wrong node name(s) set as offline: %s\n"
                (commaJoin offline_wrong)
         exitWith $ ExitFailure 1

  let nm = Container.map (\n -> if elem (Node.idx n) offline_indices
                                then Node.setOffline n True
                                else n) fixed_nl
      nl = Container.map (flip Node.setMdsk m_dsk . flip Node.setMcpu m_cpu)
           nm

  when (Container.size il == 0) $ do
         (if oneline then putStrLn $ formatOneline 0 0 0
          else printf "Cluster is empty, exiting.\n")
         exitWith ExitSuccess

  unless oneline $ printf "Loaded %d nodes, %d instances\n"
             (Container.size nl)
             (Container.size il)

  when (length csf > 0 && not oneline && verbose > 1) $ do
         printf "Note: Stripping common suffix of '%s' from names\n" csf

  let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
  unless (oneline || verbose == 0) $ printf
             "Initial check done: %d bad nodes, %d bad instances.\n"
             (length bad_nodes) (length bad_instances)

  when (length bad_nodes > 0) $ do
         putStrLn "Cluster is not N+1 happy, continuing but no guarantee \
                  \that the cluster will end N+1 happy."

  when (optShowNodes opts) $
       do
         putStrLn "Initial cluster status:"
         putStrLn $ Cluster.printNodes nl

  let ini_cv = Cluster.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
      min_cv = optMinScore opts

  when (ini_cv < min_cv) $ do
         (if oneline then
              putStrLn $ formatOneline ini_cv 0 ini_cv
          else printf "Cluster is already well balanced (initial score %.6g,\n\
                      \minimum score %.6g).\nNothing to do, exiting\n"
                      ini_cv min_cv)
         exitWith ExitSuccess

  unless oneline (if verbose > 2 then
                      printf "Initial coefficients: overall %.8f, %s\n"
                      ini_cv (Cluster.printStats nl)
                  else
                      printf "Initial score: %.8f\n" ini_cv)

  unless oneline $ putStrLn "Trying to minimize the CV..."
  let imlen = Container.maxNameLen il
      nmlen = Container.maxNameLen nl

  (fin_tbl, cmd_strs) <- iterateDepth ini_tbl (optMaxLength opts)
                         nmlen imlen [] oneline min_cv
  let (Cluster.Table fin_nl _ fin_cv fin_plc) = fin_tbl
      ord_plc = reverse fin_plc
      sol_msg = (if null fin_plc
                 then printf "No solution found\n"
                 else (if verbose > 2
                       then printf "Final coefficients:   overall %.8f, %s\n"
                            fin_cv (Cluster.printStats fin_nl)
                       else printf "Cluster score improved from %.8f to %.8f\n"
                            ini_cv fin_cv
                      ))::String

  unless oneline $ putStr sol_msg

  unless (oneline || verbose == 0) $
         printf "Solution length=%d\n" (length ord_plc)

  let cmd_data = Cluster.formatCmds . reverse $ cmd_strs

  when (isJust $ optShowCmds opts) $
       do
         let out_path = fromJust $ optShowCmds opts
         putStrLn ""
         (if out_path == "-" then
              printf "Commands to run to reach the above solution:\n%s"
                     (unlines . map ("  " ++) .
                      filter (/= "check") .
                      lines $ cmd_data)
          else do
            writeFile out_path (CLI.shTemplate ++ cmd_data)
            printf "The commands have been written to file '%s'\n" out_path)

  when (optShowNodes opts) $
       do
         let ini_cs = Cluster.totalResources nl
             fin_cs = Cluster.totalResources fin_nl
         putStrLn ""
         putStrLn "Final cluster status:"
         putStrLn $ Cluster.printNodes fin_nl
         when (verbose > 3) $
              do
                printf "Original: mem=%d disk=%d\n"
                       (Cluster.cs_fmem ini_cs) (Cluster.cs_fdsk ini_cs)
                printf "Final:    mem=%d disk=%d\n"
                       (Cluster.cs_fmem fin_cs) (Cluster.cs_fdsk fin_cs)
  when oneline $
         putStrLn $ formatOneline ini_cv (length ord_plc) fin_cv

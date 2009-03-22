{-| Solver for N+1 cluster errors

-}

module Main (main) where

import Data.List
import Data.Function
import Monad
import System
import System.IO
import System.Console.GetOpt
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.CLI as CLI
import Ganeti.HTools.Rapi
import Ganeti.HTools.Utils

-- | Command line options structure.
data Options = Options
    { optShowNodes   :: Bool
    , optShowCmds    :: Bool
    , optNodef       :: FilePath
    , optInstf       :: FilePath
    , optMinDepth    :: Int
    , optMaxRemovals :: Int
    , optMinDelta    :: Int
    , optMaxDelta    :: Int
    , optMaster      :: String
    , optShowVer     :: Bool     -- ^ Just show the program version
    , optShowHelp    :: Bool     -- ^ Just show the help
    } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions    = Options
 { optShowNodes   = False
 , optShowCmds    = False
 , optNodef       = "nodes"
 , optInstf       = "instances"
 , optMinDepth    = 1
 , optMaxRemovals = -1
 , optMinDelta    = 0
 , optMaxDelta    = -1
 , optMaster    = ""
 , optShowVer   = False
 , optShowHelp  = False
 }

{- | Start computing the solution at the given depth and recurse until
we find a valid solution or we exceed the maximum depth.

-}
iterateDepth :: Cluster.NodeList
             -> [Instance.Instance]
             -> Int
             -> Int
             -> Int
             -> Int
             -> IO (Maybe Cluster.Solution)
iterateDepth nl bad_instances depth max_removals min_delta max_delta =
    let
        max_depth = length bad_instances
        sol = Cluster.computeSolution nl bad_instances depth
              max_removals min_delta max_delta
    in
      do
        printf "%d " depth
        hFlush stdout
        case sol `seq` sol of
          Nothing ->
              if depth > max_depth then
                  return Nothing
              else
                  iterateDepth nl bad_instances (depth + 1)
                               max_removals min_delta max_delta
          _ -> return sol

-- | Options list and functions
options :: [OptDescr (Options -> Options)]
options =
    [ Option ['p']     ["print-nodes"]
      (NoArg (\ opts -> opts { optShowNodes = True }))
      "print the final node list"
    , Option ['C']     ["print-commands"]
      (NoArg (\ opts -> opts { optShowCmds = True }))
      "print the ganeti command list for reaching the solution"
    , Option ['n']     ["nodes"]
      (ReqArg (\ f opts -> opts { optNodef = f }) "FILE")
      "the node list FILE"
    , Option ['i']     ["instances"]
      (ReqArg (\ f opts -> opts { optInstf =  f }) "FILE")
      "the instance list FILE"
    , Option ['d']     ["depth"]
      (ReqArg (\ i opts -> opts { optMinDepth =  (read i)::Int }) "D")
      "start computing the solution at depth D"
    , Option ['r']     ["max-removals"]
      (ReqArg (\ i opts -> opts { optMaxRemovals =  (read i)::Int }) "R")
      "do not process more than R removal sets (useful for high depths)"
    , Option ['L']     ["max-delta"]
      (ReqArg (\ i opts -> opts { optMaxDelta =  (read i)::Int }) "L")
      "refuse solutions with delta higher than L"
    , Option ['l']     ["min-delta"]
      (ReqArg (\ i opts -> opts { optMinDelta =  (read i)::Int }) "L")
      "return once a solution with delta L or lower has been found"
    , Option ['m']     ["master"]
      (ReqArg (\ m opts -> opts { optMaster = m }) "ADDRESS")
      "collect data via RAPI at the given ADDRESS"
    , Option ['V']     ["version"]
      (NoArg (\ opts -> opts { optShowVer = True}))
      "show the version of the program"
    , Option ['h']     ["help"]
      (NoArg (\ opts -> opts { optShowHelp = True}))
      "show help"
    ]

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, _) <- CLI.parseOpts cmd_args "hn1" options defaultOptions optShowHelp

  when (optShowVer opts) $ do
         printf $ CLI.showVersion "hn1"
         exitWith ExitSuccess

  let min_depth = optMinDepth opts
  let (node_data, inst_data) =
          case optMaster opts of
            "" -> (readFile $ optNodef opts,
                   readFile $ optInstf opts)
            host -> (readData getNodes host,
                     readData getInstances host)

  (nl, il, csf, ktn, kti) <- liftM2 Cluster.loadData node_data inst_data

  printf "Loaded %d nodes, %d instances\n"
             (Container.size nl)
             (Container.size il)

  when (length csf > 0) $ do
         printf "Note: Stripping common suffix of '%s' from names\n" csf

  let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
  printf "Initial check done: %d bad nodes, %d bad instances.\n"
             (length bad_nodes) (length bad_instances)

  when (null bad_instances) $ do
         putStrLn "Happy time! Cluster is fine, no need to burn CPU."
         exitWith ExitSuccess

  when (length bad_instances < min_depth) $ do
         printf "Error: depth %d is higher than the number of bad instances.\n"
                min_depth
         exitWith $ ExitFailure 2

  let ini_cv = Cluster.compCV nl
  printf "Initial coefficients: overall %.8f, %s\n"
         ini_cv (Cluster.printStats nl)

  putStr "Computing solution: depth "
  hFlush stdout

  result <- iterateDepth nl bad_instances min_depth (optMaxRemovals opts)
            (optMinDelta opts) (optMaxDelta opts)
  let (min_d, solution) =
          case result of
            Just (Cluster.Solution a b) -> (a, reverse b)
            Nothing -> (-1, [])
  when (min_d == -1) $ do
         putStrLn "failed. Try to run with higher depth."
         exitWith $ ExitFailure 1

  printf "found.\n"

  let
      ns = Cluster.applySolution nl il solution
      fin_cv = Cluster.compCV ns

  printf "Final coefficients:   overall %.8f, %s\n"
         fin_cv
         (Cluster.printStats ns)

  printf "Solution (delta=%d):\n" $! min_d
  let (sol_strs, cmd_strs) = Cluster.printSolution il ktn kti solution
  putStr $ unlines $ sol_strs
  when (optShowCmds opts) $
       do
         putStrLn ""
         putStrLn "Commands to run to reach the above solution:"
         putStr . Cluster.formatCmds . reverse $ cmd_strs

  when (optShowNodes opts) $
       do
         let (orig_mem, orig_disk) = Cluster.totalResources nl
             (final_mem, final_disk) = Cluster.totalResources ns
         putStrLn ""
         putStrLn "Final cluster status:"
         putStrLn $ Cluster.printNodes ktn ns
         printf "Original: mem=%d disk=%d\n" orig_mem orig_disk
         printf "Final:    mem=%d disk=%d\n" final_mem final_disk

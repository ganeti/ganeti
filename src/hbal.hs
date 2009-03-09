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

import qualified Container
import qualified Cluster
import Rapi
import Utils

-- | Command line options structure.
data Options = Options
    { optShowNodes :: Bool
    , optShowCmds  :: Bool
    , optOneline   :: Bool
    , optNodef     :: FilePath
    , optInstf     :: FilePath
    , optMaxRounds :: Int
    , optMaster    :: String
    } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowNodes = False
 , optShowCmds  = False
 , optOneline   = False
 , optNodef     = "nodes"
 , optInstf     = "instances"
 , optMaxRounds = -1
 , optMaster    = ""
 }

{- | Start computing the solution at the given depth and recurse until
we find a valid solution or we exceed the maximum depth.

-}
iterateDepth :: Cluster.Table    -- The starting table
             -> Int              -- ^ Current round
             -> Int              -- ^ Max rounds
             -> Bool             -- ^ Wheter to be silent
             -> IO Cluster.Table -- The resulting table
iterateDepth ini_tbl cur_round max_rounds oneline =
    let Cluster.Table ini_nl ini_il ini_cv ini_plc = ini_tbl
        all_inst = Container.elems ini_il
        node_idx = Container.keys ini_nl
        fin_tbl = Cluster.checkMove node_idx ini_tbl all_inst
        (Cluster.Table _ _ fin_cv fin_plc) = fin_tbl
        ini_plc_len = length ini_plc
        fin_plc_len = length fin_plc
        allowed_next = (max_rounds < 0 || cur_round < max_rounds)
    in
      do
        unless oneline $ printf "  - round %d: " cur_round
        hFlush stdout
        let msg =
                if fin_cv < ini_cv then
                    if not allowed_next then
                        printf "%.8f, %d moves (stopping due to round limit)\n"
                               fin_cv
                               (fin_plc_len - ini_plc_len)
                    else
                        printf "%.8f, %d moves\n" fin_cv
                                   (fin_plc_len - ini_plc_len)
                else
                    "no improvement, stopping\n"
        unless oneline $ do
          putStr msg
          hFlush stdout
        (if fin_cv < ini_cv then -- this round made success, try deeper
             if allowed_next
             then iterateDepth fin_tbl (cur_round + 1) max_rounds oneline
             -- don't go deeper, but return the better solution
             else return fin_tbl
         else
             return ini_tbl)

-- | Options list and functions
options :: [OptDescr (Options -> Options)]
options =
    [ Option ['p']     ["print-nodes"]
      (NoArg (\ opts -> opts { optShowNodes = True }))
      "print the final node list"
    , Option ['C']     ["print-commands"]
      (NoArg (\ opts -> opts { optShowCmds = True }))
      "print the ganeti command list for reaching the solution"
    , Option ['o']     ["oneline"]
      (NoArg (\ opts -> opts { optOneline = True }))
      "print the ganeti command list for reaching the solution"
     , Option ['n']     ["nodes"]
      (ReqArg (\ f opts -> opts { optNodef = f }) "FILE")
      "the node list FILE"
     , Option ['i']     ["instances"]
      (ReqArg (\ f opts -> opts { optInstf =  f }) "FILE")
      "the instance list FILE"
     , Option ['m']     ["master"]
      (ReqArg (\ m opts -> opts { optMaster = m }) "ADDRESS")
      "collect data via RAPI at the given ADDRESS"
     , Option ['r']     ["max-rounds"]
      (ReqArg (\ i opts -> opts { optMaxRounds =  (read i)::Int }) "N")
      "do not run for more than R rounds(useful for very unbalanced clusters)"
     ]

-- | Command line parser, using the 'options' structure.
parseOpts :: [String] -> IO (Options, [String])
parseOpts argv =
    case getOpt Permute options argv of
      (o,n,[]  ) ->
          return (foldl (flip id) defaultOptions o, n)
      (_,_,errs) ->
          ioError (userError (concat errs ++ usageInfo header options))
      where header = "Usage: hbal [OPTION...]"

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, _) <- parseOpts cmd_args

  let oneline = optOneline opts
  let (node_data, inst_data) =
          case optMaster opts of
            "" -> (readFile $ optNodef opts,
                   readFile $ optInstf opts)
            host -> (readData getNodes host,
                     readData getInstances host)

  (nl, il, csf, ktn, kti) <- liftM2 Cluster.loadData node_data inst_data

  unless oneline $ printf "Loaded %d nodes, %d instances\n"
             (Container.size nl)
             (Container.size il)

  when (length csf > 0 && not oneline) $ do
         printf "Note: Stripping common suffix of '%s' from names\n" csf

  let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
  unless oneline $ printf
             "Initial check done: %d bad nodes, %d bad instances.\n"
             (length bad_nodes) (length bad_instances)

  when (length bad_nodes > 0) $ do
         putStrLn "Cluster is not N+1 happy, continuing but no guarantee that cluster will end N+1 happy."

  when (optShowNodes opts) $
       do
         putStrLn "Initial cluster status:"
         putStrLn $ Cluster.printNodes ktn nl

  let ini_cv = Cluster.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
  unless oneline $ printf "Initial coefficients: overall %.8f, %s\n"
         ini_cv (Cluster.printStats nl)

  unless oneline $ putStrLn "Trying to minimize the CV..."
  fin_tbl <- iterateDepth ini_tbl 1 (optMaxRounds opts) oneline
  let (Cluster.Table fin_nl _ fin_cv fin_plc) = fin_tbl
      ord_plc = reverse fin_plc
  unless oneline $ printf "Final coefficients:   overall %.8f, %s\n"
         fin_cv
         (Cluster.printStats fin_nl)

  unless oneline $ printf "Solution length=%d\n" (length ord_plc)

  let (sol_strs, cmd_strs) = Cluster.printSolution il ktn kti ord_plc
  unless oneline $ putStr $ unlines $ sol_strs
  when (optShowCmds opts) $
       do
         putStrLn ""
         putStrLn "Commands to run to reach the above solution:"
         putStr $ unlines $ map ("  echo gnt-instance " ++) $ concat cmd_strs
  when (optShowNodes opts) $
       do
         let (orig_mem, orig_disk) = Cluster.totalResources nl
             (final_mem, final_disk) = Cluster.totalResources fin_nl
         putStrLn ""
         putStrLn "Final cluster status:"
         putStrLn $ Cluster.printNodes ktn fin_nl
         printf "Original: mem=%d disk=%d\n" orig_mem orig_disk
         printf "Final:    mem=%d disk=%d\n" final_mem final_disk
  when oneline $ do
         printf "%.8f %d %.8f %8.3f\n"
                ini_cv (length ord_plc) fin_cv (ini_cv / fin_cv)

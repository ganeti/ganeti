{-| Cluster rebalancer.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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

module Ganeti.HTools.Program.Hbal
  ( main
  , options
  , arguments
  , iterateDepth
  ) where

import Control.Exception (bracket)
import Control.Monad
import Data.List
import Data.Maybe (isJust, isNothing, fromJust)
import Data.IORef
import System.Exit
import System.IO
import System.Posix.Process
import System.Posix.Signals

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Types
import Ganeti.HTools.Loader
import Ganeti.OpCodes (wrapOpCode, setOpComment, setOpPriority,
                       OpCode, MetaOpCode)
import Ganeti.Jobs as Jobs
import Ganeti.Types
import Ganeti.Utils

import qualified Ganeti.Luxi as L
import Ganeti.Version (version)

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ oPrintNodes
    , oPrintInsts
    , oPrintCommands
    , oDataFile
    , oEvacMode
    , oRapiMaster
    , luxi
    , oIAllocSrc
    , oExecJobs
    , oGroup
    , oMaxSolLength
    , oVerbose
    , oQuiet
    , oOfflineNode
    , oMinScore
    , oMaxCpu
    , oMinDisk
    , oMinGain
    , oMinGainLim
    , oDiskMoves
    , oSelInst
    , oInstMoves
    , oDynuFile
    , oExTags
    , oExInst
    , oSaveCluster
    , oPriority
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | A simple type alias for clearer signature.
type Annotator = OpCode -> MetaOpCode

-- | Wraps an 'OpCode' in a 'MetaOpCode' while also adding a comment
-- about what generated the opcode.
annotateOpCode :: Annotator
annotateOpCode =
  setOpComment ("rebalancing via hbal " ++ version) . wrapOpCode

{- | Start computing the solution at the given depth and recurse until
we find a valid solution or we exceed the maximum depth.

-}
iterateDepth :: Bool             -- ^ Whether to print moves
             -> Cluster.Table    -- ^ The starting table
             -> Int              -- ^ Remaining length
             -> Bool             -- ^ Allow disk moves
             -> Bool             -- ^ Allow instance moves
             -> Int              -- ^ Max node name len
             -> Int              -- ^ Max instance name len
             -> [MoveJob]        -- ^ Current command list
             -> Score            -- ^ Score at which to stop
             -> Score            -- ^ Min gain limit
             -> Score            -- ^ Min score gain
             -> Bool             -- ^ Enable evacuation mode
             -> IO (Cluster.Table, [MoveJob]) -- ^ The resulting table
                                              -- and commands
iterateDepth printmove ini_tbl max_rounds disk_moves inst_moves nmlen imlen
             cmd_strs min_score mg_limit min_gain evac_mode =
  let Cluster.Table ini_nl ini_il _ _ = ini_tbl
      allowed_next = Cluster.doNextBalance ini_tbl max_rounds min_score
      m_fin_tbl = if allowed_next
                    then Cluster.tryBalance ini_tbl disk_moves inst_moves
                         evac_mode mg_limit min_gain
                    else Nothing
  in case m_fin_tbl of
       Just fin_tbl ->
         do
           let (Cluster.Table _ _ _ fin_plc) = fin_tbl
           cur_plc@(idx, _, _, move, _) <-
             exitIfEmpty "Empty placement list returned for solution?!" fin_plc
           let fin_plc_len = length fin_plc
               (sol_line, cmds) = Cluster.printSolutionLine ini_nl ini_il
                                  nmlen imlen cur_plc fin_plc_len
               afn = Cluster.involvedNodes ini_il cur_plc
               upd_cmd_strs = (afn, idx, move, cmds):cmd_strs
           when printmove $ do
               putStrLn sol_line
               hFlush stdout
           iterateDepth printmove fin_tbl max_rounds disk_moves inst_moves
                        nmlen imlen upd_cmd_strs min_score
                        mg_limit min_gain evac_mode
       Nothing -> return (ini_tbl, cmd_strs)

-- | Displays the cluster stats.
printStats :: Node.List -> Node.List -> IO ()
printStats ini_nl fin_nl = do
  let ini_cs = Cluster.totalResources ini_nl
      fin_cs = Cluster.totalResources fin_nl
  printf "Original: mem=%d disk=%d\n"
             (Cluster.csFmem ini_cs) (Cluster.csFdsk ini_cs) :: IO ()
  printf "Final:    mem=%d disk=%d\n"
             (Cluster.csFmem fin_cs) (Cluster.csFdsk fin_cs)

-- | Saves the rebalance commands to a text file.
saveBalanceCommands :: Options -> String -> IO ()
saveBalanceCommands opts cmd_data = do
  let out_path = fromJust $ optShowCmds opts
  putStrLn ""
  if out_path == "-"
    then printf "Commands to run to reach the above solution:\n%s"
           (unlines . map ("  " ++) .
            filter (/= "  check") .
            lines $ cmd_data)
    else do
      writeFile out_path (shTemplate ++ cmd_data)
      printf "The commands have been written to file '%s'\n" out_path

-- | Wrapper over execJobSet checking for early termination via an IORef.
execCancelWrapper :: Annotator -> String -> Node.List
                  -> Instance.List -> IORef Int -> [JobSet] -> IO (Result ())
execCancelWrapper _    _      _  _  _    [] = return $ Ok ()
execCancelWrapper anno master nl il cref alljss = do
  cancel <- readIORef cref
  if cancel > 0
    then return . Bad $ "Exiting early due to user request, " ++
                        show (length alljss) ++ " jobset(s) remaining."
    else execJobSet anno master nl il cref alljss

-- | Execute an entire jobset.
execJobSet :: Annotator -> String -> Node.List
           -> Instance.List -> IORef Int -> [JobSet] -> IO (Result ())
execJobSet _    _      _  _  _    [] = return $ Ok ()
execJobSet anno master nl il cref (js:jss) = do
  -- map from jobset (htools list of positions) to [[opcodes]]
  let jobs = map (\(_, idx, move, _) ->
                    map anno $ Cluster.iMoveToJob nl il idx move) js
      descr = map (\(_, idx, _, _) -> Container.nameOf il idx) js
      logfn = putStrLn . ("Got job IDs" ++) . commaJoin . map (show . fromJobId)
  putStrLn $ "Executing jobset for instances " ++ commaJoin descr
  jrs <- bracket (L.getClient master) L.closeClient $
         Jobs.execJobsWait jobs logfn
  case jrs of
    Bad x -> return $ Bad x
    Ok x -> if null failures
              then execCancelWrapper anno master nl il cref jss
              else return . Bad . unlines $ [
                "Not all jobs completed successfully: " ++ show failures,
                "Aborting."]
      where
        failures = filter ((/= JOB_STATUS_SUCCESS) . snd) x

-- | Executes the jobs, if possible and desired.
maybeExecJobs :: Options
              -> [a]
              -> Node.List
              -> Instance.List
              -> [JobSet]
              -> IO (Result ())
maybeExecJobs opts ord_plc fin_nl il cmd_jobs =
  if optExecJobs opts && not (null ord_plc)
    then (case optLuxi opts of
            Nothing ->
              return $ Bad "Execution of commands possible only on LUXI"
            Just master ->
              let annotator = maybe id setOpPriority (optPriority opts) .
                              annotateOpCode
              in execWithCancel annotator master fin_nl il cmd_jobs)
    else return $ Ok ()

-- | Signal handler for graceful termination.
handleSigInt :: IORef Int -> IO ()
handleSigInt cref = do
  writeIORef cref 1
  putStrLn ("Cancel request registered, will exit at" ++
            " the end of the current job set...")

-- | Signal handler for immediate termination.
handleSigTerm :: IORef Int -> IO ()
handleSigTerm cref = do
  -- update the cref to 2, just for consistency
  writeIORef cref 2
  putStrLn "Double cancel request, exiting now..."
  exitImmediately $ ExitFailure 2

-- | Prepares to run a set of jobsets with handling of signals and early
-- termination.
execWithCancel :: Annotator -> String -> Node.List -> Instance.List -> [JobSet]
               -> IO (Result ())
execWithCancel anno master fin_nl il cmd_jobs = do
  cref <- newIORef 0
  mapM_ (\(hnd, sig) -> installHandler sig (Catch (hnd cref)) Nothing)
    [(handleSigTerm, softwareTermination), (handleSigInt, keyboardSignal)]
  execCancelWrapper anno master fin_nl il cref cmd_jobs

-- | Select the target node group.
selectGroup :: Options -> Group.List -> Node.List -> Instance.List
            -> IO (String, (Node.List, Instance.List))
selectGroup opts gl nlf ilf = do
  let ngroups = Cluster.splitCluster nlf ilf
  when (length ngroups > 1 && isNothing (optGroup opts)) $ do
    hPutStrLn stderr "Found multiple node groups:"
    mapM_ (hPutStrLn stderr . ("  " ++) . Group.name .
           flip Container.find gl . fst) ngroups
    exitErr "Aborting."

  case optGroup opts of
    Nothing -> do
      (gidx, cdata) <- exitIfEmpty "No groups found by splitCluster?!" ngroups
      let grp = Container.find gidx gl
      return (Group.name grp, cdata)
    Just g -> case Container.findByName gl g of
      Nothing -> do
        hPutStrLn stderr $ "Node group " ++ g ++
          " not found. Node group list is:"
        mapM_ (hPutStrLn stderr . ("  " ++) . Group.name ) (Container.elems gl)
        exitErr "Aborting."
      Just grp ->
          case lookup (Group.idx grp) ngroups of
            Nothing ->
              -- This will only happen if there are no nodes assigned
              -- to this group
              return (Group.name grp, (Container.empty, Container.empty))
            Just cdata -> return (Group.name grp, cdata)

-- | Do a few checks on the cluster data.
checkCluster :: Int -> Node.List -> Instance.List -> IO ()
checkCluster verbose nl il = do
  -- nothing to do on an empty cluster
  when (Container.null il) $ do
         printf "Cluster is empty, exiting.\n"::IO ()
         exitSuccess

  -- hbal doesn't currently handle split clusters
  let split_insts = Cluster.findSplitInstances nl il
  unless (null split_insts || verbose <= 1) $ do
    hPutStrLn stderr "Found instances belonging to multiple node groups:"
    mapM_ (\i -> hPutStrLn stderr $ "  " ++ Instance.name i) split_insts
    hPutStrLn stderr "These instances will not be moved."

  printf "Loaded %d nodes, %d instances\n"
             (Container.size nl)
             (Container.size il)::IO ()

  let csf = commonSuffix nl il
  when (not (null csf) && verbose > 1) $
       printf "Note: Stripping common suffix of '%s' from names\n" csf

-- | Do a few checks on the selected group data.
checkGroup :: Int -> String -> Node.List -> Instance.List -> IO ()
checkGroup verbose gname nl il = do
  printf "Group size %d nodes, %d instances\n"
             (Container.size nl)
             (Container.size il)::IO ()

  putStrLn $ "Selected node group: " ++ gname

  let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
  unless (verbose == 0) $ printf
             "Initial check done: %d bad nodes, %d bad instances.\n"
             (length bad_nodes) (length bad_instances)

  unless (null bad_nodes) $
         putStrLn "Cluster is not N+1 happy, continuing but no guarantee \
                  \that the cluster will end N+1 happy."

-- | Check that we actually need to rebalance.
checkNeedRebalance :: Options -> Score -> IO ()
checkNeedRebalance opts ini_cv = do
  let min_cv = optMinScore opts
  when (ini_cv < min_cv) $ do
         printf "Cluster is already well balanced (initial score %.6g,\n\
                \minimum score %.6g).\nNothing to do, exiting\n"
                ini_cv min_cv:: IO ()
         exitSuccess

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ exitErr "This program doesn't take any arguments."

  let verbose = optVerbose opts
      shownodes = optShowNodes opts
      showinsts = optShowInsts opts

  ini_cdata@(ClusterData gl fixed_nl ilf ctags ipol) <- loadExternalData opts

  when (verbose > 1) $ do
       putStrLn $ "Loaded cluster tags: " ++ intercalate "," ctags
       putStrLn $ "Loaded cluster ipolicy: " ++ show ipol

  nlf <- setNodeStatus opts fixed_nl
  checkCluster verbose nlf ilf

  maybeSaveData (optSaveCluster opts) "original" "before balancing" ini_cdata

  (gname, (nl, il)) <- selectGroup opts gl nlf ilf

  checkGroup verbose gname nl il

  maybePrintInsts showinsts "Initial" (Cluster.printInsts nl il)

  maybePrintNodes shownodes "Initial cluster" (Cluster.printNodes nl)

  let ini_cv = Cluster.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
      min_cv = optMinScore opts

  checkNeedRebalance opts ini_cv

  if verbose > 2
    then printf "Initial coefficients: overall %.8f\n%s"
           ini_cv (Cluster.printStats "  " nl)::IO ()
    else printf "Initial score: %.8f\n" ini_cv

  putStrLn "Trying to minimize the CV..."
  let imlen = maximum . map (length . Instance.alias) $ Container.elems il
      nmlen = maximum . map (length . Node.alias) $ Container.elems nl

  (fin_tbl, cmd_strs) <- iterateDepth True ini_tbl (optMaxLength opts)
                         (optDiskMoves opts)
                         (optInstMoves opts)
                         nmlen imlen [] min_cv
                         (optMinGainLim opts) (optMinGain opts)
                         (optEvacMode opts)
  let (Cluster.Table fin_nl fin_il fin_cv fin_plc) = fin_tbl
      ord_plc = reverse fin_plc
      sol_msg = case () of
                  _ | null fin_plc -> printf "No solution found\n"
                    | verbose > 2 ->
                        printf "Final coefficients:   overall %.8f\n%s"
                        fin_cv (Cluster.printStats "  " fin_nl)
                    | otherwise ->
                        printf "Cluster score improved from %.8f to %.8f\n"
                        ini_cv fin_cv ::String

  putStr sol_msg

  unless (verbose == 0) $
         printf "Solution length=%d\n" (length ord_plc)

  let cmd_jobs = Cluster.splitJobs cmd_strs

  when (isJust $ optShowCmds opts) .
       saveBalanceCommands opts $ Cluster.formatCmds cmd_jobs

  maybeSaveData (optSaveCluster opts) "balanced" "after balancing"
                ini_cdata { cdNodes = fin_nl, cdInstances = fin_il }

  maybePrintInsts showinsts "Final" (Cluster.printInsts fin_nl fin_il)

  maybePrintNodes shownodes "Final cluster" (Cluster.printNodes fin_nl)

  when (verbose > 3) $ printStats nl fin_nl

  exitIfBad "hbal" =<< maybeExecJobs opts ord_plc fin_nl il cmd_jobs

{-| Cluster rebalancer.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}

module Ganeti.HTools.Program.Hbal
  ( main
  , options
  , arguments
  , iterateDepth
  ) where

import Control.Arrow ((&&&))
import Control.Lens (over)
import Control.Monad
import Data.List
import Data.Maybe (isNothing, fromMaybe)
import System.Exit
import System.IO

import Text.Printf (printf)

import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..), fromCLIOptions)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import qualified Ganeti.HTools.Cluster.Utils as ClusterUtils
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Types
import Ganeti.HTools.Loader
import Ganeti.OpCodes (wrapOpCode, setOpComment, setOpPriority)
import Ganeti.OpCodes.Lens (metaParamsL, opReasonL)
import Ganeti.JQueue (currentTimestamp, reasonTrailTimestamp)
import Ganeti.JQueue.Objects (Timestamp)
import Ganeti.Jobs as Jobs
import Ganeti.Utils

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
    , oRestrictedMigrate
    , oRapiMaster
    , luxi
    , oIAllocSrc
    , oExecJobs
    , oFirstJobGroup
    , oReason
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
    , oIgnoreSoftErrors
    , oDynuFile
    , oIgnoreDyn 
    , oMonD
    , oMonDDataFile
    , oMonDExitMissing
    , oMonDXen
    , oExTags
    , oExInst
    , oSaveCluster
    , oPriority
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Wraps an 'OpCode' in a 'MetaOpCode' while also adding a comment
-- about what generated the opcode.
annotateOpCode :: Maybe String -> Timestamp -> Jobs.Annotator
annotateOpCode reason ts =
  over (metaParamsL . opReasonL)
      (++ [( "hbal", fromMaybe ("hbal " ++ version ++ " called") reason
           , reasonTrailTimestamp ts)])
  . setOpComment ("rebalancing via hbal " ++ version)
  . wrapOpCode

{- | Start computing the solution at the given depth and recurse until
we find a valid solution or we exceed the maximum depth.

-}
iterateDepth :: Bool             -- ^ Whether to print moves
             -> AlgorithmOptions -- ^ Algorithmic options to apply
             -> Cluster.Table    -- ^ The starting table
             -> Int              -- ^ Remaining length
             -> Int              -- ^ Max node name len
             -> Int              -- ^ Max instance name len
             -> [MoveJob]        -- ^ Current command list
             -> Score            -- ^ Score at which to stop
             -> IO (Cluster.Table, [MoveJob]) -- ^ The resulting table
                                              -- and commands
iterateDepth printmove algOpts ini_tbl max_rounds nmlen imlen cmd_strs
             min_score =
  let Cluster.Table ini_nl ini_il _ _ = ini_tbl
      allowed_next = Cluster.doNextBalance ini_tbl max_rounds min_score
      m_fin_tbl = if allowed_next
                    then Cluster.tryBalance algOpts ini_tbl
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
           iterateDepth printmove algOpts fin_tbl max_rounds
                        nmlen imlen upd_cmd_strs min_score
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
            Just master -> do
              ts <- currentTimestamp
              let annotator = maybe id setOpPriority (optPriority opts) .
                              annotateOpCode (optReason opts) ts
              execWithCancel annotator master $
                zip (map toOpcodes cmd_jobs) (map toDescr cmd_jobs))
    else return $ Ok ()
  where toOpcodes = map (\(_, idx, move, _) ->
                          Cluster.iMoveToJob fin_nl il idx move)
        toDescr job = "Executing jobset for instances " ++ commaJoin
                       (map (\(_, idx, _, _) -> Container.nameOf il idx) job)

-- | Select the target node group.
selectGroup :: Options -> Group.List -> Node.List -> Instance.List
            -> IO (String, (Node.List, Instance.List))
selectGroup opts gl nlf ilf = do
  let ngroups = ClusterUtils.splitCluster nlf ilf
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
checkGroup :: Bool -> Int -> String -> Node.List -> Instance.List -> IO ()
checkGroup force verbose gname nl il = do
  printf "Group size %d nodes, %d instances\n"
             (Container.size nl)
             (Container.size il)::IO ()

  putStrLn $ "Selected node group: " ++ gname

  let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
  unless (verbose < 1) $ printf
             "Initial check done: %d bad nodes, %d bad instances.\n"
             (length bad_nodes) (length bad_instances)

  let other_nodes = filter (not . (`elem` bad_nodes)) $ Container.elems nl
      node_status = map (Node.name &&& Node.getPolicyHealth) other_nodes
      policy_bad = filter (isBad . snd) node_status

  when (verbose > 4) $ do
    printf "Bad nodes: %s\n" . show $ map Node.name bad_nodes :: IO ()
    printf "N+1 happy nodes: %s\n" . show $ map Node.name other_nodes :: IO ()
    printf "Node policy status: %s\n" $ show node_status :: IO ()

  unless (null bad_nodes) $
         putStrLn "Cluster is not N+1 happy, continuing but no guarantee \
                  \that the cluster will end N+1 happy."

  unless (null policy_bad) $ do
    printf "The cluster contains %d policy-violating nodes.\n"
      $ length policy_bad :: IO ()
    putStrLn $ if force
      then "Continuing, ignoring soft errors."
      else "Continuing, but the set of moves might be too restricted;\
           \ consider using the --ignore-soft-errors option."

-- | Check that we actually need to rebalance.
checkNeedRebalance :: Options -> Score -> Score -> IO ()
checkNeedRebalance opts ini_cv opt_cv = do
  let min_cv = optMinScore opts
  when (ini_cv - opt_cv < min_cv) $ do
         printf "Cluster is already well balanced (initial score %.6g,\n\
                \optimum score due to N+1 reservations %.6g,\n\
                \minimum score %.6g).\nNothing to do, exiting\n"
                ini_cv opt_cv min_cv:: IO ()
         exitSuccess

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ exitErr "This program doesn't take any arguments."

  let verbose = optVerbose opts
      shownodes = optShowNodes opts
      showinsts = optShowInsts opts
      force = optIgnoreSoftErrors opts

  ini_cdata@(ClusterData gl fixed_nl ilf ctags ipol) <- loadExternalData opts

  when (verbose > 1) $ do
       putStrLn $ "Loaded cluster tags: " ++ intercalate "," ctags
       putStrLn $ "Loaded cluster ipolicy: " ++ show ipol

  nlf <- setNodeStatus opts fixed_nl
  checkCluster verbose nlf ilf

  maybeSaveData (optSaveCluster opts) "original" "before balancing" ini_cdata

  (gname, (nl, il)) <- selectGroup opts gl nlf ilf

  checkGroup force verbose gname nl il

  maybePrintInsts showinsts "Initial" (Cluster.printInsts nl il)

  maybePrintNodes shownodes "Initial cluster" (Cluster.printNodes nl)

  let ini_cv = Metrics.compCV nl
      opt_cv = Metrics.optimalCVScore nl
      ini_tbl = Cluster.Table nl il ini_cv []
      min_cv = optMinScore opts

  if verbose > 2
    then printf "Initial coefficients: overall %.8f\n%s"
           ini_cv (Metrics.printStats "  " nl)::IO ()
    else printf "Initial score: %.8f\n" ini_cv

  checkNeedRebalance opts ini_cv opt_cv

  putStrLn "Trying to minimize the CV..."
  let imlen = maximum . map (length . Instance.alias) $ Container.elems il
      nmlen = maximum . map (length . Node.alias) $ Container.elems nl

  (fin_tbl, cmd_strs) <- iterateDepth True (fromCLIOptions opts) ini_tbl
                         (optMaxLength opts)
                         nmlen imlen [] (opt_cv + min_cv)
  let (Cluster.Table fin_nl fin_il fin_cv fin_plc) = fin_tbl
      ord_plc = reverse fin_plc
      sol_msg = case () of
                  _ | null fin_plc -> printf "No solution found\n"
                    | verbose > 2 ->
                        printf "Final coefficients:   overall %.8f\n%s"
                        fin_cv (Metrics.printStats "  " fin_nl)
                    | otherwise ->
                        printf "Cluster score improved from %.8f to %.8f\n"
                        ini_cv fin_cv ::String

  putStr sol_msg

  unless (verbose < 1) $
         printf "Solution length=%d\n" (length ord_plc)

  let cmd_jobs = (if optFirstJobGroup opts then take 1 else id)
                 $ Cluster.splitJobs cmd_strs

  maybeSaveCommands (if optFirstJobGroup opts
                        then "First set of jobs:"
                        else "Commands to run to reach the above solution:")
                    opts
    $ Cluster.formatCmds cmd_jobs

  maybeSaveData (optSaveCluster opts) "balanced" "after balancing"
                ini_cdata { cdNodes = fin_nl, cdInstances = fin_il }

  maybePrintInsts showinsts "Final" (Cluster.printInsts fin_nl fin_il)

  maybePrintNodes shownodes "Final cluster" (Cluster.printNodes fin_nl)

  when (verbose > 3) $ printStats nl fin_nl

  exitIfBad "hbal" =<< maybeExecJobs opts ord_plc fin_nl il cmd_jobs

{-| Cluster checker.

-}

{-

Copyright (C) 2012 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU Gene52al Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.HTools.Program.Hcheck (main, options) where

import Control.Monad
import List (transpose)
import System.Exit
import System.IO
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

import qualified Ganeti.HTools.Program.Hbal as Hbal

import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Loader
import Ganeti.HTools.Types

-- | Options list and functions.
options :: [OptType]
options =
  [ oDataFile
  , oDiskMoves
  , oDynuFile
  , oEvacMode
  , oExInst
  , oExTags
  , oIAllocSrc
  , oInstMoves
  , oLuxiSocket
  , oMachineReadable
  , oMaxCpu
  , oMaxSolLength
  , oMinDisk
  , oMinGain
  , oMinGainLim
  , oMinScore
  , oNoSimulation
  , oOfflineNode
  , oQuiet
  , oRapiMaster
  , oSelInst
  , oShowHelp
  , oShowVer
  , oVerbose
  ]

-- | Check phase - are we before (initial) or after rebalance.
data Phase = Initial
           | Rebalanced

-- | Level of presented statistics.
data Level = GroupLvl
           | ClusterLvl

-- | Prefix for machine readable names
htcPrefix :: String
htcPrefix = "HCHECK"

-- | Data showed both per group and per cluster.
commonData :: [(String, String)]
commonData =[ ("N1_FAIL", "Nodes not N+1 happy")
            , ("CONFLICT_TAGS", "Nodes with conflicting instances")
            , ("OFFLINE_PRI", "Instances with primary on an offline node")
            , ("OFFLINE_SEC", "Instances with seondary on an offline node")
            ]

-- | Data showed per group.
groupData :: [(String, String)]
groupData = commonData ++ [("SCORE", "Group score")]

-- | Data showed per cluster.
clusterData :: [(String, String)]
clusterData = commonData ++
              [ ("NEED_REBALANCE", "Cluster is not healthy")
              , ("CAN_REBALANCE", "Possible to run rebalance")
              ]

-- | Phase-specific prefix for machine readable version.
phasePrefix :: Phase -> String
phasePrefix Initial = "INIT"
phasePrefix Rebalanced = "FINAL"

-- | Level-specific prefix for machine readable version.
levelPrefix :: Level -> String
levelPrefix GroupLvl = "GROUP"
levelPrefix ClusterLvl = "CLUSTER"

-- | Machine-readable keys to show depending on given level.
keysData :: Level -> [String]
keysData GroupLvl = map fst groupData
keysData ClusterLvl = map fst clusterData

-- | Description of phases for human readable version.
phaseDescr :: Phase -> String
phaseDescr Initial = "initially"
phaseDescr Rebalanced = "after rebalancing"

-- | Description to show depending on given level.
descrData :: Level -> [String]
descrData GroupLvl = map snd groupData
descrData ClusterLvl = map snd clusterData

-- | Human readable prefix for statistics.
phaseLevelDescr :: Phase -> Level -> Maybe String -> String
phaseLevelDescr phase GroupLvl (Just name) =
    printf "Statistics for group %s %s\n" name $ phaseDescr phase
phaseLevelDescr phase GroupLvl Nothing =
    printf "Statistics for group %s\n" $ phaseDescr phase
phaseLevelDescr phase ClusterLvl _ =
    printf "Cluster statistics %s\n" $ phaseDescr phase

-- | Format a list of key, value as a shell fragment.
printKeysHTC :: [(String, String)] -> IO ()
printKeysHTC = printKeys htcPrefix

-- | Prepare string from boolean value.
printBool :: Bool    -- ^ Whether the result should be machine readable
          -> Bool    -- ^ Value to be converted to string
          -> String
printBool True True = "1"
printBool True False = "0"
printBool False b = show b

-- | Print mapping from group idx to group uuid (only in machine readable mode).
printGroupsMappings :: Group.List -> IO ()
printGroupsMappings gl = do
    let extract_vals = \g -> (printf "GROUP_UUID_%d" $ Group.idx g :: String,
                              printf "%s" $ Group.uuid g :: String)
        printpairs = map extract_vals (Container.elems gl)
    printKeysHTC printpairs

-- | Prepare a single key given a certain level and phase of simulation.
prepareKey :: Level -> Phase -> Maybe String -> String -> String
prepareKey level phase Nothing suffix =
  printf "%s_%s_%s" (phasePrefix phase) (levelPrefix level) suffix
prepareKey level phase (Just idx) suffix =
  printf "%s_%s_%s_%s" (phasePrefix phase) (levelPrefix level) idx suffix

-- | Print all the statistics for given level and phase.
printStats :: Int            -- ^ Verbosity level
           -> Bool           -- ^ If the output should be machine readable
           -> Level          -- ^ Level on which we are printing
           -> Phase          -- ^ Current phase of simulation
           -> [String]       -- ^ Values to print
           -> Maybe String   -- ^ Additional data for groups
           -> IO ()
printStats _ True level phase values gidx = do
  let keys = map (prepareKey level phase gidx) (keysData level)
  printKeysHTC $ zip keys values

printStats verbose False level phase values name = do
  let prefix = phaseLevelDescr phase level name
      descr = descrData level
  unless (verbose == 0) $ do
    printf "\n%s" prefix :: IO ()
    mapM_ (\(a,b) -> printf "    %s: %s\n" a b) (zip descr values)

-- | Extract name or idx from group.
extractGroupData :: Bool -> Group.Group -> String
extractGroupData True grp = printf "%d" $ Group.idx grp
extractGroupData False grp = Group.name grp

-- | Prepare values for group.
prepareGroupValues :: [Int] -> Double -> [String]
prepareGroupValues stats score =
  map (printf "%d") stats ++ [printf "%.8f" score]

-- | Prepare values for cluster.
prepareClusterValues :: Bool -> [Int] -> [Bool] -> [String]
prepareClusterValues machineread stats bstats =
  map (printf "%d")  stats ++ map (printBool machineread) bstats

-- | Print all the statistics on a group level.
printGroupStats :: Int -> Bool -> Phase -> Group.Group -> [Int] -> Double
                -> IO ()
printGroupStats verbose machineread phase grp stats score = do
  let values = prepareGroupValues stats score
      extradata = extractGroupData machineread grp
  printStats verbose machineread GroupLvl phase values (Just extradata)

-- | Print all the statistics on a cluster (global) level.
printClusterStats :: Int -> Bool -> Phase -> [Int] -> Bool -> Bool -> IO ()
printClusterStats verbose machineread phase stats needhbal canhbal = do
  let values = prepareClusterValues machineread stats [needhbal, canhbal]
  printStats verbose machineread ClusterLvl phase values Nothing

-- | Check if any of cluster metrics is non-zero.
clusterNeedsRebalance :: [Int] -> Bool
clusterNeedsRebalance stats = sum stats > 0

{- | Check group for N+1 hapiness, conflicts of primaries on nodes and
instances residing on offline nodes.

-}
perGroupChecks :: Int -> Bool -> Phase -> Group.List ->
                  (Gdx, (Node.List, Instance.List)) -> IO ([Int])
perGroupChecks verbose machineread phase gl (gidx, (nl, il)) = do
  let grp = Container.find gidx gl
      offnl = filter Node.offline (Container.elems nl)
      n1violated = length $ fst $ Cluster.computeBadItems nl il
      conflicttags = length $ filter (>0)
                     (map Node.conflictingPrimaries (Container.elems nl))
      offline_pri = sum . map length $ map Node.pList offnl
      offline_sec = length $ map Node.sList offnl
      score = Cluster.compCV nl
      groupstats = [ n1violated
                   , conflicttags
                   , offline_pri
                   , offline_sec
                   ]
  printGroupStats verbose machineread phase grp groupstats score
  return groupstats

-- | Use Hbal's iterateDepth to simulate group rebalance.
executeSimulation :: Options -> Cluster.Table -> Double ->
                     Gdx -> Node.List -> Instance.List ->
                     IO ( (Gdx, (Node.List, Instance.List)) )
executeSimulation opts ini_tbl min_cv gidx nl il = do
  let imlen = maximum . map (length . Instance.alias) $ Container.elems il
      nmlen = maximum . map (length . Node.alias) $ Container.elems nl

  (fin_tbl, _) <- Hbal.iterateDepth False ini_tbl
                                    (optMaxLength opts)
                                    (optDiskMoves opts)
                                    (optInstMoves opts)
                                    nmlen imlen [] min_cv
                                    (optMinGainLim opts) (optMinGain opts)
                                    (optEvacMode opts)

  let (Cluster.Table fin_nl fin_il _ _) = fin_tbl
  return (gidx, (fin_nl, fin_il))

-- | Simulate group rebalance if group's score is not good
maybeSimulateGroupRebalance :: Options -> (Gdx, (Node.List, Instance.List))
                               -> IO ((Gdx, (Node.List, Instance.List)))
maybeSimulateGroupRebalance opts (gidx, (nl, il)) = do
  let ini_cv = Cluster.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
      min_cv = optMinScore opts
  if (ini_cv < min_cv)
    then return (gidx, (nl, il))
    else executeSimulation opts ini_tbl min_cv gidx nl il

-- | Decide whether to simulate rebalance.
maybeSimulateRebalance :: Bool             -- ^ Whether to simulate rebalance
                       -> Options          -- ^ Command line options
                       -> [(Gdx, (Node.List, Instance.List))] -- ^ Group data
                       -> IO([(Gdx, (Node.List, Instance.List))])
maybeSimulateRebalance True opts cluster =
    mapM (maybeSimulateGroupRebalance opts) cluster
maybeSimulateRebalance False _ cluster = return cluster

-- | Prints the final @OK@ marker in machine readable output.
printFinalHTC :: Bool -> IO ()
printFinalHTC = printFinal htcPrefix

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ do
         hPutStrLn stderr "Error: this program doesn't take any arguments."
         exitWith $ ExitFailure 1

  let verbose = optVerbose opts
      machineread = optMachineReadable opts
      nosimulation = optNoSimulation opts

  (ClusterData gl fixed_nl ilf _ _) <- loadExternalData opts
  nlf <- setNodeStatus opts fixed_nl

  let splitinstances = Cluster.findSplitInstances nlf ilf
      splitcluster = Cluster.splitCluster nlf ilf

  when machineread $ printGroupsMappings gl

  groupsstats <- mapM (perGroupChecks verbose machineread Initial gl) splitcluster
  let clusterstats = map sum (transpose groupsstats) :: [Int]
      needrebalance = clusterNeedsRebalance clusterstats
      canrebalance = length splitinstances == 0
  printClusterStats verbose machineread Initial clusterstats needrebalance
                    canrebalance

  when nosimulation $ do
    unless (verbose == 0 || machineread) $
      printf "Running in no-simulation mode. Exiting.\n"

  when (length splitinstances > 0) $ do
    unless (verbose == 0 || machineread) $
       printf "Split instances found, simulation of re-balancing not possible\n"

  unless needrebalance $ do
    unless (verbose == 0 || machineread) $
      printf "No need to rebalance cluster, no problems found. Exiting.\n"

  let exitOK = nosimulation || not needrebalance
      simulate = not nosimulation && length splitinstances == 0 && needrebalance

  rebalancedcluster <- maybeSimulateRebalance simulate opts splitcluster

  when (simulate || machineread) $ do
    newgroupstats <- mapM (perGroupChecks verbose machineread Rebalanced gl)
                     rebalancedcluster
    -- We do not introduce new split instances during rebalance
    let newsplitinstances = splitinstances
        newclusterstats = map sum (transpose newgroupstats) :: [Int]
        newneedrebalance = clusterNeedsRebalance clusterstats
        newcanrebalance = length newsplitinstances == 0

    printClusterStats verbose machineread Rebalanced newclusterstats
                           newneedrebalance newcanrebalance

  printFinalHTC machineread

  unless exitOK $ exitWith $ ExitFailure 1

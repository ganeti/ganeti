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

-- | Phase-specific prefix for machine readable version.
phasePrefix :: Phase -> String
phasePrefix Initial = "INIT"
phasePrefix Rebalanced = "FINAL"

-- | Description of phases for human readable version.
phaseDescription :: Phase -> String
phaseDescription Initial = "initially"
phaseDescription Rebalanced = "after rebalancing"

-- | Level-specific prefix for machine readable version.
levelPrefix :: Level -> String
levelPrefix GroupLvl = "GROUP"
levelPrefix ClusterLvl = "CLUSTER"

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
clusterData = commonData ++ [("NEED_REBALANCE", "Cluster is not healthy")]

-- | Format a list of key, value as a shell fragment.
printKeysHTC :: [(String, String)] -> IO ()
printKeysHTC = printKeys htcPrefix

-- | Print all the statistics on a group level.
printGroupStats :: Int -> Bool -> Phase -> Gdx -> [Int] -> Double -> IO ()
printGroupStats _ True phase gidx stats score = do
  let printstats = map (printf "%d") stats ++ [printf "%.8f" score] :: [String]
      printkeys = map (printf "%s_%s_%d_%s"
                                  (phasePrefix phase)
                                  (levelPrefix GroupLvl)
                                  gidx)
                       (map fst groupData) :: [String]
  printKeysHTC (zip printkeys printstats)

printGroupStats verbose False phase gidx stats score = do
  let printstats = map (printf "%d") stats ++ [printf "%.8f" score] :: [String]

  unless (verbose == 0) $ do
    printf "\nStatistics for group %d %s\n"
               gidx (phaseDescription phase) :: IO ()
    mapM_ (\(a,b) -> printf "    %s: %s\n" (snd a) b :: IO ())
          (zip groupData printstats)

-- | Print all the statistics on a cluster (global) level.
printClusterStats :: Int -> Bool -> Phase -> [Int] -> IO (Bool)
printClusterStats _ True phase stats = do
  let needrebal = sum stats
      printstats = map (printf "%d") $ stats ++ [needrebal]
                 :: [String]
      printkeys = map (printf "%s_%s_%s"
                              (phasePrefix phase)
                              (levelPrefix ClusterLvl))
                      (map fst clusterData) :: [String]
  printKeysHTC (zip printkeys printstats)
  return $ needrebal > 0

printClusterStats verbose False phase stats = do
  let needrebal = sum stats
      printstats = map (printf "%d") stats :: [String]
  unless (verbose == 0) $ do
      printf "\nCluster statistics %s\n" (phaseDescription phase) :: IO ()
      mapM_ (\(a,b) -> printf "    %s: %s\n" (snd a) b :: IO ())
            (zip clusterData (printstats ++ [show (needrebal>0)]))
  return $ needrebal > 0

{- | Check group for N+1 hapiness, conflicts of primaries on nodes and
instances residing on offline nodes.

-}
perGroupChecks :: Int -> Bool -> Phase -> (Gdx, (Node.List, Instance.List))
               -> IO ([Int])
perGroupChecks verbose machineread phase (gidx, (nl, il)) = do
  let offnl = filter Node.offline (Container.elems nl)
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
  printGroupStats verbose machineread phase gidx groupstats score
  return groupstats

-- | Use Hbal's iterateDepth to simulate group rebalance.
simulateRebalance :: Options ->
                     (Gdx, (Node.List, Instance.List)) ->
                     IO ( (Gdx, (Node.List, Instance.List)) )
simulateRebalance opts (gidx, (nl, il)) = do
  let ini_cv = Cluster.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
      min_cv = optMinScore opts


  if (ini_cv < min_cv)
    then return (gidx, (nl, il))
    else do
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

  (ClusterData _ fixed_nl ilf _ _) <- loadExternalData opts
  nlf <- setNodeStatus opts fixed_nl

  let splitinstances = Cluster.findSplitInstances nlf ilf
      splitcluster = Cluster.splitCluster nlf ilf

  groupsstats <- mapM (perGroupChecks verbose machineread Initial) splitcluster
  let clusterstats = map sum (transpose groupsstats) :: [Int]
  needrebalance <- printClusterStats verbose machineread Initial clusterstats

  when nosimulation $ do
    unless (verbose == 0 || machineread) $
      printf "Running in no-simulation mode. Exiting.\n"
    printFinalHTC machineread
    exitWith ExitSuccess

  when (length splitinstances > 0) $ do
    unless (verbose == 0 || machineread) $
       printf "Split instances found, simulation of re-balancing not possible\n"
    exitWith $ ExitFailure 1

  unless needrebalance $ do
    unless (verbose == 0 || machineread) $
      printf "No need to rebalance cluster, no problems found. Exiting.\n"
    printFinalHTC machineread
    exitWith ExitSuccess

  rebalancedcluster <- mapM (simulateRebalance opts) splitcluster
  newgroupstats <- mapM (perGroupChecks verbose machineread Rebalanced)
                     rebalancedcluster
  let newclusterstats = map sum (transpose newgroupstats) :: [Int]
  _ <- printClusterStats verbose machineread Rebalanced newclusterstats

  printFinalHTC machineread

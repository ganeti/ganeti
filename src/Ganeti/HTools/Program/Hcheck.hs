{-| Cluster checker.

-}

{-

Copyright (C) 2012, 2013 Google Inc.
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

module Ganeti.HTools.Program.Hcheck
  ( main
  , options
  , arguments
  ) where

import Control.Monad
import qualified Data.IntMap as IntMap
import Data.List (transpose)
import System.Exit
import Text.Printf (printf)

import Ganeti.HTools.AlgorithmParams (fromCLIOptions)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import qualified Ganeti.HTools.Cluster.Utils as ClusterUtils
import qualified Ganeti.HTools.GlobalN1 as GlobalN1
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

import qualified Ganeti.HTools.Program.Hbal as Hbal

import Ganeti.Common
import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import Ganeti.Utils

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ oDataFile
    , oDiskMoves
    , oDynuFile
    , oIgnoreDyn
    , oEvacMode
    , oExInst
    , oExTags
    , oIAllocSrc
    , oInstMoves
    , luxi
    , oMachineReadable
    , oMaxCpu
    , oMaxSolLength
    , oMinDisk
    , oMinGain
    , oMinGainLim
    , oMinScore
    , oIgnoreSoftErrors
    , oNoSimulation
    , oOfflineNode
    , oQuiet
    , oRapiMaster
    , oSelInst
    , oNoCapacityChecks
    , oVerbose
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Check phase - are we before (initial) or after rebalance.
data Phase = Initial
           | Rebalanced

-- | Level of presented statistics.
data Level = GroupLvl String -- ^ Group level, with name
           | ClusterLvl      -- ^ Cluster level

-- | A type alias for a group index and node\/instance lists.
type GroupInfo = (Gdx, (Node.List, Instance.List))

-- | A type alias for group stats.
type GroupStats = ((Group.Group, Double), [Int])

-- | Prefix for machine readable names.
htcPrefix :: String
htcPrefix = "HCHECK"

-- | Data showed both per group and per cluster.
commonData :: Options -> [(String, String)]
commonData opts =
  [ ("N1_FAIL", "Nodes not N+1 happy")
  , ("CONFLICT_TAGS", "Nodes with conflicting instances")
  , ("OFFLINE_PRI", "Instances having the primary node offline")
  , ("OFFLINE_SEC", "Instances having a secondary node offline")
  ]
  ++ [ ("GN1_FAIL", "Nodes not directly evacuateable")  | optCapacity opts ]

-- | Data showed per group.
groupData :: Options -> [(String, String)]
groupData opts = commonData opts ++ [("SCORE", "Group score")]

-- | Data showed per cluster.
clusterData :: Options -> [(String, String)]
clusterData opts = commonData opts  ++
              [ ("NEED_REBALANCE", "Cluster is not healthy") ]

-- | Phase-specific prefix for machine readable version.
phasePrefix :: Phase -> String
phasePrefix Initial = "INIT"
phasePrefix Rebalanced = "FINAL"

-- | Level-specific prefix for machine readable version.
levelPrefix :: Level -> String
levelPrefix GroupLvl {} = "GROUP"
levelPrefix ClusterLvl  = "CLUSTER"

-- | Machine-readable keys to show depending on given level.
keysData :: Options -> Level -> [String]
keysData opts GroupLvl {} = map fst $ groupData opts
keysData opts ClusterLvl  = map fst $ clusterData opts

-- | Description of phases for human readable version.
phaseDescr :: Phase -> String
phaseDescr Initial = "initially"
phaseDescr Rebalanced = "after rebalancing"

-- | Description to show depending on given level.
descrData :: Options -> Level -> [String]
descrData opts GroupLvl {} = map snd $ groupData opts
descrData opts ClusterLvl  = map snd $ clusterData opts

-- | Human readable prefix for statistics.
phaseLevelDescr :: Phase -> Level -> String
phaseLevelDescr phase (GroupLvl name) =
    printf "Statistics for group %s %s\n" name $ phaseDescr phase
phaseLevelDescr phase ClusterLvl =
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

-- | Print mapping from group idx to group uuid (only in machine
-- readable mode).
printGroupsMappings :: Group.List -> IO ()
printGroupsMappings gl = do
    let extract_vals g = (printf "GROUP_UUID_%d" $ Group.idx g :: String,
                          Group.uuid g)
        printpairs = map extract_vals (Container.elems gl)
    printKeysHTC printpairs

-- | Prepare a single key given a certain level and phase of simulation.
prepareKey :: Level -> Phase -> String -> String
prepareKey level@ClusterLvl phase suffix =
  printf "%s_%s_%s" (phasePrefix phase) (levelPrefix level) suffix
prepareKey level@(GroupLvl idx) phase suffix =
  printf "%s_%s_%s_%s" (phasePrefix phase) (levelPrefix level) idx suffix

-- | Print all the statistics for given level and phase.
printStats :: Options
           -> Bool           -- ^ If the output should be machine readable
           -> Level          -- ^ Level on which we are printing
           -> Phase          -- ^ Current phase of simulation
           -> [String]       -- ^ Values to print
           -> IO ()
printStats opts True level phase values = do
  let keys = map (prepareKey level phase) (keysData opts level)
  printKeysHTC $ zip keys values

printStats opts False level phase values = do
  let prefix = phaseLevelDescr phase level
      descr = descrData opts level
  unless (optVerbose opts < 1) $ do
    putStrLn ""
    putStr prefix
    mapM_ (uncurry (printf "    %s: %s\n")) (zip descr values)

-- | Extract name or idx from group.
extractGroupData :: Bool -> Group.Group -> String
extractGroupData True grp = show $ Group.idx grp
extractGroupData False grp = Group.name grp

-- | Prepare values for group.
prepareGroupValues :: [Int] -> Double -> [String]
prepareGroupValues stats score =
  map show stats ++ [printf "%.8f" score]

-- | Prepare values for cluster.
prepareClusterValues :: Bool -> [Int] -> [Bool] -> [String]
prepareClusterValues machineread stats bstats =
  map show stats ++ map (printBool machineread) bstats

-- | Print all the statistics on a group level.
printGroupStats :: Options -> Bool -> Phase -> GroupStats -> IO ()
printGroupStats opts machineread phase ((grp, score), stats) = do
  let values = prepareGroupValues stats score
      extradata = extractGroupData machineread grp
  printStats opts machineread (GroupLvl extradata) phase values

-- | Print all the statistics on a cluster (global) level.
printClusterStats :: Options -> Bool -> Phase -> [Int] -> Bool -> IO ()
printClusterStats opts machineread phase stats needhbal = do
  let values = prepareClusterValues machineread stats [needhbal]
  printStats opts machineread ClusterLvl phase values

-- | Check if any of cluster metrics is non-zero.
clusterNeedsRebalance :: [Int] -> Bool
clusterNeedsRebalance stats = sum stats > 0

{- | Check group for N+1 hapiness, conflicts of primaries on nodes and
instances residing on offline nodes.

-}
perGroupChecks :: Options -> Group.List -> GroupInfo -> GroupStats
perGroupChecks opts gl (gidx, (nl, il)) =
  let grp = Container.find gidx gl
      offnl = filter Node.offline (Container.elems nl)
      n1violated = length . fst $ Cluster.computeBadItems nl il
      gn1fail = length . filter (not . GlobalN1.canEvacuateNode (nl, il))
                  $ IntMap.elems nl
      conflicttags = length $ filter (>0)
                     (map Node.conflictingPrimaries (Container.elems nl))
      offline_pri = sum . map length $ map Node.pList offnl
      offline_sec = length $ map Node.sList offnl
      score = Metrics.compCV nl
      groupstats = [ n1violated
                   , conflicttags
                   , offline_pri
                   , offline_sec
                   ]
                   ++ [ gn1fail | optCapacity opts ]
  in ((grp, score), groupstats)

-- | Use Hbal's iterateDepth to simulate group rebalance.
executeSimulation :: Options -> Cluster.Table -> Double
                  -> Gdx -> Node.List -> Instance.List
                  -> IO GroupInfo
executeSimulation opts ini_tbl min_cv gidx nl il = do
  let imlen = maximum . map (length . Instance.alias) $ Container.elems il
      nmlen = maximum . map (length . Node.alias) $ Container.elems nl

  (fin_tbl, _) <- Hbal.iterateDepth False (fromCLIOptions opts) ini_tbl
                                    (optMaxLength opts)
                                    nmlen imlen [] min_cv

  let (Cluster.Table fin_nl fin_il _ _) = fin_tbl
  return (gidx, (fin_nl, fin_il))

-- | Simulate group rebalance if group's score is not good
maybeSimulateGroupRebalance :: Options -> GroupInfo -> IO GroupInfo
maybeSimulateGroupRebalance opts (gidx, (nl, il)) = do
  let ini_cv = Metrics.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
      min_cv = optMinScore opts + Metrics.optimalCVScore nl
  if ini_cv < min_cv
    then return (gidx, (nl, il))
    else executeSimulation opts ini_tbl min_cv gidx nl il

-- | Decide whether to simulate rebalance.
maybeSimulateRebalance :: Bool             -- ^ Whether to simulate rebalance
                       -> Options          -- ^ Command line options
                       -> [GroupInfo]      -- ^ Group data
                       -> IO [GroupInfo]
maybeSimulateRebalance True opts cluster =
    mapM (maybeSimulateGroupRebalance opts) cluster
maybeSimulateRebalance False _ cluster = return cluster

-- | Prints the final @OK@ marker in machine readable output.
printFinalHTC :: Bool -> IO ()
printFinalHTC = printFinal htcPrefix

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ exitErr "This program doesn't take any arguments."

  let verbose = optVerbose opts
      machineread = optMachineReadable opts
      nosimulation = optNoSimulation opts

  (ClusterData gl fixed_nl ilf _ _) <- loadExternalData opts
  nlf <- setNodeStatus opts fixed_nl

  let splitcluster = ClusterUtils.splitCluster nlf ilf

  when machineread $ printGroupsMappings gl

  let groupsstats = map (perGroupChecks opts gl) splitcluster
      clusterstats = map sum . transpose . map snd $ groupsstats
      needrebalance = clusterNeedsRebalance clusterstats

  unless (verbose < 1 || machineread) .
    putStrLn $ if nosimulation
                 then "Running in no-simulation mode."
                 else if needrebalance
                        then "Cluster needs rebalancing."
                        else "No need to rebalance cluster, no problems found."

  mapM_ (printGroupStats opts machineread Initial) groupsstats

  printClusterStats opts machineread Initial clusterstats needrebalance

  let exitOK = nosimulation || not needrebalance
      simulate = not nosimulation && needrebalance

  rebalancedcluster <- maybeSimulateRebalance simulate opts splitcluster

  when (simulate || machineread) $ do
    let newgroupstats = map (perGroupChecks opts gl) rebalancedcluster
        newclusterstats = map sum . transpose . map snd $ newgroupstats
        newneedrebalance = clusterNeedsRebalance clusterstats

    mapM_ (printGroupStats opts machineread Rebalanced) newgroupstats

    printClusterStats opts machineread Rebalanced newclusterstats
                           newneedrebalance

  printFinalHTC machineread

  unless exitOK . exitWith $ ExitFailure 1

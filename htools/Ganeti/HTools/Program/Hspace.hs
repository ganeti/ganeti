{-| Cluster space sizing

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Ganeti.HTools.Program.Hspace (main, options) where

import Control.Monad
import Data.Char (toUpper, isAlphaNum, toLower)
import Data.Function (on)
import Data.List
import Data.Maybe (fromMaybe)
import Data.Ord (comparing)
import System.Exit
import System.IO

import Text.Printf (printf, hPrintf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

import Ganeti.HTools.Utils
import Ganeti.HTools.Types
import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Loader

-- | Options list and functions.
options :: [OptType]
options =
  [ oPrintNodes
  , oDataFile
  , oDiskTemplate
  , oNodeSim
  , oRapiMaster
  , oLuxiSocket
  , oVerbose
  , oQuiet
  , oOfflineNode
  , oMachineReadable
  , oMaxCpu
  , oMaxSolLength
  , oMinDisk
  , oStdSpec
  , oTieredSpec
  , oSaveCluster
  , oShowVer
  , oShowHelp
  ]

-- | The allocation phase we're in (initial, after tiered allocs, or
-- after regular allocation).
data Phase = PInitial
           | PFinal
           | PTiered

-- | The kind of instance spec we print.
data SpecType = SpecNormal
              | SpecTiered

-- | What we prefix a spec with.
specPrefix :: SpecType -> String
specPrefix SpecNormal = "SPEC"
specPrefix SpecTiered = "TSPEC_INI"

-- | The description of a spec.
specDescription :: SpecType -> String
specDescription SpecNormal = "Standard (fixed-size)"
specDescription SpecTiered = "Tiered (initial size)"

-- | Efficiency generic function.
effFn :: (Cluster.CStats -> Integer)
      -> (Cluster.CStats -> Double)
      -> Cluster.CStats -> Double
effFn fi ft cs = fromIntegral (fi cs) / ft cs

-- | Memory efficiency.
memEff :: Cluster.CStats -> Double
memEff = effFn Cluster.csImem Cluster.csTmem

-- | Disk efficiency.
dskEff :: Cluster.CStats -> Double
dskEff = effFn Cluster.csIdsk Cluster.csTdsk

-- | Cpu efficiency.
cpuEff :: Cluster.CStats -> Double
cpuEff = effFn Cluster.csIcpu (fromIntegral . Cluster.csVcpu)

-- | Holds data for converting a 'Cluster.CStats' structure into
-- detailed statictics.
statsData :: [(String, Cluster.CStats -> String)]
statsData = [ ("SCORE", printf "%.8f" . Cluster.csScore)
            , ("INST_CNT", printf "%d" . Cluster.csNinst)
            , ("MEM_FREE", printf "%d" . Cluster.csFmem)
            , ("MEM_AVAIL", printf "%d" . Cluster.csAmem)
            , ("MEM_RESVD",
               \cs -> printf "%d" (Cluster.csFmem cs - Cluster.csAmem cs))
            , ("MEM_INST", printf "%d" . Cluster.csImem)
            , ("MEM_OVERHEAD",
               \cs -> printf "%d" (Cluster.csXmem cs + Cluster.csNmem cs))
            , ("MEM_EFF", printf "%.8f" . memEff)
            , ("DSK_FREE", printf "%d" . Cluster.csFdsk)
            , ("DSK_AVAIL", printf "%d". Cluster.csAdsk)
            , ("DSK_RESVD",
               \cs -> printf "%d" (Cluster.csFdsk cs - Cluster.csAdsk cs))
            , ("DSK_INST", printf "%d" . Cluster.csIdsk)
            , ("DSK_EFF", printf "%.8f" . dskEff)
            , ("CPU_INST", printf "%d" . Cluster.csIcpu)
            , ("CPU_EFF", printf "%.8f" . cpuEff)
            , ("MNODE_MEM_AVAIL", printf "%d" . Cluster.csMmem)
            , ("MNODE_DSK_AVAIL", printf "%d" . Cluster.csMdsk)
            ]

-- | List holding 'RSpec' formatting information.
specData :: [(String, RSpec -> String)]
specData = [ ("MEM", printf "%d" . rspecMem)
           , ("DSK", printf "%d" . rspecDsk)
           , ("CPU", printf "%d" . rspecCpu)
           ]

-- | List holding 'Cluster.CStats' formatting information.
clusterData :: [(String, Cluster.CStats -> String)]
clusterData = [ ("MEM", printf "%.0f" . Cluster.csTmem)
              , ("DSK", printf "%.0f" . Cluster.csTdsk)
              , ("CPU", printf "%.0f" . Cluster.csTcpu)
              , ("VCPU", printf "%d" . Cluster.csVcpu)
              ]

-- | Function to print stats for a given phase.
printStats :: Phase -> Cluster.CStats -> [(String, String)]
printStats ph cs =
  map (\(s, fn) -> (printf "%s_%s" kind s, fn cs)) statsData
  where kind = case ph of
                 PInitial -> "INI"
                 PFinal -> "FIN"
                 PTiered -> "TRL"

-- | Print failure reason and scores
printFRScores :: Node.List -> Node.List -> [(FailMode, Int)] -> IO ()
printFRScores ini_nl fin_nl sreason = do
  printf "  - most likely failure reason: %s\n" $ failureReason sreason::IO ()
  printClusterScores ini_nl fin_nl
  printClusterEff (Cluster.totalResources fin_nl)

-- | Print final stats and related metrics.
printResults :: Bool -> Node.List -> Node.List -> Int -> Int
             -> [(FailMode, Int)] -> IO ()
printResults True _ fin_nl num_instances allocs sreason = do
  let fin_stats = Cluster.totalResources fin_nl
      fin_instances = num_instances + allocs

  when (num_instances + allocs /= Cluster.csNinst fin_stats) $
       do
         hPrintf stderr "ERROR: internal inconsistency, allocated (%d)\
                        \ != counted (%d)\n" (num_instances + allocs)
                                 (Cluster.csNinst fin_stats) :: IO ()
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

printResults False ini_nl fin_nl _ allocs sreason = do
  putStrLn "Normal (fixed-size) allocation results:"
  printf "  - %3d instances allocated\n" allocs :: IO ()
  printFRScores ini_nl fin_nl sreason

-- | Prints the final @OK@ marker in machine readable output.
printFinal :: Bool -> IO ()
printFinal True =
  -- this should be the final entry
  printKeys [("OK", "1")]

printFinal False = return ()

-- | Compute the tiered spec counts from a list of allocated
-- instances.
tieredSpecMap :: [Instance.Instance]
              -> [(RSpec, Int)]
tieredSpecMap trl_ixes =
  let fin_trl_ixes = reverse trl_ixes
      ix_byspec = groupBy ((==) `on` Instance.specOf) fin_trl_ixes
      spec_map = map (\ixs -> (Instance.specOf $ head ixs, length ixs))
                 ix_byspec
  in spec_map

-- | Formats a spec map to strings.
formatSpecMap :: [(RSpec, Int)] -> [String]
formatSpecMap =
  map (\(spec, cnt) -> printf "%d,%d,%d=%d" (rspecMem spec)
                       (rspecDsk spec) (rspecCpu spec) cnt)

-- | Formats \"key-metrics\" values.
formatRSpec :: String -> AllocInfo -> [(String, String)]
formatRSpec s r =
  [ ("KM_" ++ s ++ "_CPU", show $ allocInfoVCpus r)
  , ("KM_" ++ s ++ "_NPU", show $ allocInfoNCpus r)
  , ("KM_" ++ s ++ "_MEM", show $ allocInfoMem r)
  , ("KM_" ++ s ++ "_DSK", show $ allocInfoDisk r)
  ]

-- | Shows allocations stats.
printAllocationStats :: Node.List -> Node.List -> IO ()
printAllocationStats ini_nl fin_nl = do
  let ini_stats = Cluster.totalResources ini_nl
      fin_stats = Cluster.totalResources fin_nl
      (rini, ralo, runa) = Cluster.computeAllocationDelta ini_stats fin_stats
  printKeys $ formatRSpec "USED" rini
  printKeys $ formatRSpec "POOL" ralo
  printKeys $ formatRSpec "UNAV" runa

-- | Ensure a value is quoted if needed.
ensureQuoted :: String -> String
ensureQuoted v = if not (all (\c -> isAlphaNum c || c == '.') v)
                 then '\'':v ++ "'"
                 else v

-- | Format a list of key\/values as a shell fragment.
printKeys :: [(String, String)] -> IO ()
printKeys = mapM_ (\(k, v) ->
                   printf "HTS_%s=%s\n" (map toUpper k) (ensureQuoted v))

-- | Converts instance data to a list of strings.
printInstance :: Node.List -> Instance.Instance -> [String]
printInstance nl i = [ Instance.name i
                     , Container.nameOf nl $ Instance.pNode i
                     , let sdx = Instance.sNode i
                       in if sdx == Node.noSecondary then ""
                          else Container.nameOf nl sdx
                     , show (Instance.mem i)
                     , show (Instance.dsk i)
                     , show (Instance.vcpus i)
                     ]

-- | Optionally print the allocation map.
printAllocationMap :: Int -> String
                   -> Node.List -> [Instance.Instance] -> IO ()
printAllocationMap verbose msg nl ixes =
  when (verbose > 1) $ do
    hPutStrLn stderr (msg ++ " map")
    hPutStr stderr . unlines . map ((:) ' ' .  unwords) $
            formatTable (map (printInstance nl) (reverse ixes))
                        -- This is the numberic-or-not field
                        -- specification; the first three fields are
                        -- strings, whereas the rest are numeric
                       [False, False, False, True, True, True]

-- | Formats nicely a list of resources.
formatResources :: a -> [(String, a->String)] -> String
formatResources res =
    intercalate ", " . map (\(a, fn) -> a ++ " " ++ fn res)

-- | Print the cluster resources.
printCluster :: Bool -> Cluster.CStats -> Int -> IO ()
printCluster True ini_stats node_count = do
  printKeys $ map (\(a, fn) -> ("CLUSTER_" ++ a, fn ini_stats)) clusterData
  printKeys [("CLUSTER_NODES", printf "%d" node_count)]
  printKeys $ printStats PInitial ini_stats

printCluster False ini_stats node_count = do
  printf "The cluster has %d nodes and the following resources:\n  %s.\n"
         node_count (formatResources ini_stats clusterData)::IO ()
  printf "There are %s initial instances on the cluster.\n"
             (if inst_count > 0 then show inst_count else "no" )
      where inst_count = Cluster.csNinst ini_stats

-- | Prints the normal instance spec.
printISpec :: Bool -> RSpec -> SpecType -> DiskTemplate -> IO ()
printISpec True ispec spec disk_template = do
  printKeys $ map (\(a, fn) -> (prefix ++ "_" ++ a, fn ispec)) specData
  printKeys [ (prefix ++ "_RQN", printf "%d" req_nodes) ]
  printKeys [ (prefix ++ "_DISK_TEMPLATE",
               diskTemplateToRaw disk_template) ]
      where req_nodes = Instance.requiredNodes disk_template
            prefix = specPrefix spec

printISpec False ispec spec disk_template =
  printf "%s instance spec is:\n  %s, using disk\
         \ template '%s'.\n"
         (specDescription spec)
         (formatResources ispec specData) (diskTemplateToRaw disk_template)

-- | Prints the tiered results.
printTiered :: Bool -> [(RSpec, Int)]
            -> Node.List -> Node.List -> [(FailMode, Int)] -> IO ()
printTiered True spec_map nl trl_nl _ = do
  printKeys $ printStats PTiered (Cluster.totalResources trl_nl)
  printKeys [("TSPEC", unwords (formatSpecMap spec_map))]
  printAllocationStats nl trl_nl

printTiered False spec_map ini_nl fin_nl sreason = do
  _ <- printf "Tiered allocation results:\n"
  if null spec_map
    then putStrLn "  - no instances allocated"
    else mapM_ (\(ispec, cnt) ->
                  printf "  - %3d instances of spec %s\n" cnt
                           (formatResources ispec specData)) spec_map
  printFRScores ini_nl fin_nl sreason

-- | Displays the initial/final cluster scores.
printClusterScores :: Node.List -> Node.List -> IO ()
printClusterScores ini_nl fin_nl = do
  printf "  - initial cluster score: %.8f\n" $ Cluster.compCV ini_nl::IO ()
  printf "  -   final cluster score: %.8f\n" $ Cluster.compCV fin_nl

-- | Displays the cluster efficiency.
printClusterEff :: Cluster.CStats -> IO ()
printClusterEff cs =
  mapM_ (\(s, fn) ->
           printf "  - %s usage efficiency: %5.2f%%\n" s (fn cs * 100))
          [("memory", memEff),
           ("  disk", dskEff),
           ("  vcpu", cpuEff)]

-- | Computes the most likely failure reason.
failureReason :: [(FailMode, Int)] -> String
failureReason = show . fst . head

-- | Sorts the failure reasons.
sortReasons :: [(FailMode, Int)] -> [(FailMode, Int)]
sortReasons = reverse . sortBy (comparing snd)

-- | Aborts the program if we get a bad value.
exitIfBad :: Result a -> IO a
exitIfBad (Bad s) =
  hPrintf stderr "Failure: %s\n" s >> exitWith (ExitFailure 1)
exitIfBad (Ok v) = return v

-- | Runs an allocation algorithm and saves cluster state.
runAllocation :: ClusterData                -- ^ Cluster data
              -> Maybe Cluster.AllocResult  -- ^ Optional stop-allocation
              -> Result Cluster.AllocResult -- ^ Allocation result
              -> RSpec                      -- ^ Requested instance spec
              -> DiskTemplate               -- ^ Requested disk template
              -> SpecType                   -- ^ Allocation type
              -> Options                    -- ^ CLI options
              -> IO (FailStats, Node.List, Int, [(RSpec, Int)])
runAllocation cdata stop_allocation actual_result spec dt mode opts = do
  (reasons, new_nl, new_il, new_ixes, _) <-
      case stop_allocation of
        Just result_noalloc -> return result_noalloc
        Nothing -> exitIfBad actual_result

  let name = head . words . specDescription $ mode
      descr = name ++ " allocation"
      ldescr = "after " ++ map toLower descr

  printISpec (optMachineReadable opts) spec mode dt

  printAllocationMap (optVerbose opts) descr new_nl new_ixes

  maybePrintNodes (optShowNodes opts) descr (Cluster.printNodes new_nl)

  maybeSaveData (optSaveCluster opts) (map toLower name) ldescr
                    (cdata { cdNodes = new_nl, cdInstances = new_il})

  return (sortReasons reasons, new_nl, length new_ixes, tieredSpecMap new_ixes)

-- | Create an instance from a given spec.
instFromSpec :: RSpec -> DiskTemplate -> Instance.Instance
instFromSpec spx disk_template =
  Instance.create "new" (rspecMem spx) (rspecDsk spx)
    (rspecCpu spx) Running [] True (-1) (-1) disk_template

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ do
         hPutStrLn stderr "Error: this program doesn't take any arguments."
         exitWith $ ExitFailure 1

  let verbose = optVerbose opts
      machine_r = optMachineReadable opts

  orig_cdata@(ClusterData gl fixed_nl il _ ipol) <- loadExternalData opts
  nl <- setNodeStatus opts fixed_nl

  cluster_disk_template <-
    case iPolicyDiskTemplates ipol of
      first_templ:_ -> return first_templ
      _ -> do
         _ <- hPutStrLn stderr $ "Error: null list of disk templates\
                               \ received from cluster!"
         exitWith $ ExitFailure 1

  let num_instances = Container.size il
      all_nodes = Container.elems fixed_nl
      cdata = orig_cdata { cdNodes = fixed_nl }
      disk_template = fromMaybe cluster_disk_template (optDiskTemplate opts)
      req_nodes = Instance.requiredNodes disk_template
      csf = commonSuffix fixed_nl il

  when (not (null csf) && verbose > 1) $
       hPrintf stderr "Note: Stripping common suffix of '%s' from names\n" csf

  maybePrintNodes (optShowNodes opts) "Initial cluster" (Cluster.printNodes nl)

  when (verbose > 2) $
         hPrintf stderr "Initial coefficients: overall %.8f, %s\n"
                 (Cluster.compCV nl) (Cluster.printStats nl)

  printCluster machine_r (Cluster.totalResources nl) (length all_nodes)

  let stop_allocation = case Cluster.computeBadItems nl il of
                          ([], _) -> Nothing
                          _ -> Just ([(FailN1, 1)]::FailStats, nl, il, [], [])
      alloclimit = if optMaxLength opts == -1
                   then Nothing
                   else Just (optMaxLength opts)

  allocnodes <- exitIfBad $ Cluster.genAllocNodes gl nl req_nodes True

  -- Run the tiered allocation

  let tspec = fromMaybe (rspecFromISpec (iPolicyMaxSpec ipol))
              (optTieredSpec opts)

  (treason, trl_nl, _, spec_map) <-
    runAllocation cdata stop_allocation
       (Cluster.tieredAlloc nl il alloclimit
        (instFromSpec tspec disk_template) allocnodes [] [])
       tspec disk_template SpecTiered opts

  printTiered machine_r spec_map nl trl_nl treason

  -- Run the standard (avg-mode) allocation

  let ispec = fromMaybe (rspecFromISpec (iPolicyStdSpec ipol))
              (optStdSpec opts)

  (sreason, fin_nl, allocs, _) <-
      runAllocation cdata stop_allocation
            (Cluster.iterateAlloc nl il alloclimit
             (instFromSpec ispec disk_template) allocnodes [] [])
            ispec disk_template SpecNormal opts

  printResults machine_r nl fin_nl num_instances allocs sreason

  -- Print final result

  printFinal machine_r

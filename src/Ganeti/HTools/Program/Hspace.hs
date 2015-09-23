{-| Cluster space sizing

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

module Ganeti.HTools.Program.Hspace
  (main
  , options
  , arguments
  ) where

import Control.Monad
import Data.Char (toUpper, toLower)
import Data.Function (on)
import qualified Data.IntMap as IntMap
import Data.List
import Data.Maybe (fromMaybe)
import Data.Ord (comparing)
import System.IO

import Text.Printf (printf, hPrintf)

import qualified Ganeti.HTools.AlgorithmParams as Alg
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(algCapacityIgnoreGroups))
import Ganeti.HTools.GlobalN1 (redundantGrp)
import Ganeti.HTools.Types
import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Loader
import Ganeti.Utils

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ oPrintNodes
    , oDataFile
    , oDiskTemplate
    , oSpindleUse
    , oNodeSim
    , oRapiMaster
    , luxi
    , oIAllocSrc
    , oVerbose
    , oQuiet
    , oIndependentGroups
    , oAcceptExisting
    , oOfflineNode
    , oNoCapacityChecks
    , oMachineReadable
    , oMaxCpu
    , oMaxSolLength
    , oMinDisk
    , oStdSpec
    , oTieredSpec
    , oSaveCluster
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | The allocation phase we're in (initial, after tiered allocs, or
-- after regular allocation).
data Phase = PInitial
           | PFinal
           | PTiered

-- | The kind of instance spec we print.
data SpecType = SpecNormal
              | SpecTiered

-- | Prefix for machine readable names
htsPrefix :: String
htsPrefix = "HTS"

-- | What we prefix a spec with.
specPrefix :: SpecType -> String
specPrefix SpecNormal = "SPEC"
specPrefix SpecTiered = "TSPEC_INI"

-- | The description of a spec.
specDescription :: SpecType -> String
specDescription SpecNormal = "Standard (fixed-size)"
specDescription SpecTiered = "Tiered (initial size)"

-- | The \"name\" of a 'SpecType'.
specName :: SpecType -> String
specName SpecNormal = "Standard"
specName SpecTiered = "Tiered"

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

-- | Spindles efficiency.
spnEff :: Cluster.CStats -> Double
spnEff = effFn Cluster.csIspn Cluster.csTspn

-- | Holds data for converting a 'Cluster.CStats' structure into
-- detailed statistics.
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
            , ("SPN_FREE", printf "%d" . Cluster.csFspn)
            , ("SPN_INST", printf "%d" . Cluster.csIspn)
            , ("SPN_EFF", printf "%.8f" . spnEff)
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

-- | 'RSpec' formatting information including spindles.
specDataSpn :: [(String, RSpec -> String)]
specDataSpn = specData ++ [("SPN", printf "%d" . rspecSpn)]

-- | List holding 'Cluster.CStats' formatting information.
clusterData :: [(String, Cluster.CStats -> String)]
clusterData = [ ("MEM", printf "%.0f" . Cluster.csTmem)
              , ("DSK", printf "%.0f" . Cluster.csTdsk)
              , ("CPU", printf "%.0f" . Cluster.csTcpu)
              , ("VCPU", printf "%d" . Cluster.csVcpu)
              ]

-- | 'Cluster.CStats' formatting information including spindles
clusterDataSpn :: [(String, Cluster.CStats -> String)]
clusterDataSpn = clusterData ++ [("SPN", printf "%.0f" . Cluster.csTspn)]

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
  printClusterEff (Cluster.totalResources fin_nl) (Node.haveExclStorage fin_nl)

-- | Print final stats and related metrics.
printResults :: Bool -> Node.List -> Node.List -> Int -> Int
             -> [(FailMode, Int)] -> IO ()
printResults True _ fin_nl num_instances allocs sreason = do
  let fin_stats = Cluster.totalResources fin_nl
      fin_instances = num_instances + allocs

  exitWhen (num_instances + allocs /= Cluster.csNinst fin_stats) $
           printf "internal inconsistency, allocated (%d)\
                  \ != counted (%d)\n" (num_instances + allocs)
           (Cluster.csNinst fin_stats)

  main_reason <- exitIfEmpty "Internal error, no failure reasons?!" sreason

  printKeysHTS $ printStats PFinal fin_stats
  printKeysHTS [ ("ALLOC_USAGE", printf "%.8f"
                                   ((fromIntegral num_instances::Double) /
                                   fromIntegral fin_instances))
               , ("ALLOC_INSTANCES", printf "%d" allocs)
               , ("ALLOC_FAIL_REASON", map toUpper . show . fst $ main_reason)
               ]
  printKeysHTS $ map (\(x, y) -> (printf "ALLOC_%s_CNT" (show x),
                                  printf "%d" y)) sreason

printResults False ini_nl fin_nl _ allocs sreason = do
  putStrLn "Normal (fixed-size) allocation results:"
  printf "  - %3d instances allocated\n" allocs :: IO ()
  printFRScores ini_nl fin_nl sreason

-- | Prints the final @OK@ marker in machine readable output.
printFinalHTS :: Bool -> IO ()
printFinalHTS = printFinal htsPrefix

{-# ANN tieredSpecMap "HLint: ignore Use alternative" #-}
-- | Compute the tiered spec counts from a list of allocated
-- instances.
tieredSpecMap :: [Instance.Instance]
              -> [(RSpec, Int)]
tieredSpecMap trl_ixes =
  let fin_trl_ixes = reverse trl_ixes
      ix_byspec = groupBy ((==) `on` Instance.specOf) fin_trl_ixes
      -- head is "safe" here, as groupBy returns list of non-empty lists
      spec_map = map (\ixs -> (Instance.specOf $ head ixs, length ixs))
                 ix_byspec
  in spec_map

-- | Formats a spec map to strings.
formatSpecMap :: [(RSpec, Int)] -> [String]
formatSpecMap =
  map (\(spec, cnt) -> printf "%d,%d,%d,%d=%d" (rspecMem spec)
                       (rspecDsk spec) (rspecCpu spec) (rspecSpn spec) cnt)

-- | Formats \"key-metrics\" values.
formatRSpec :: String -> AllocInfo -> [(String, String)]
formatRSpec s r =
  [ ("KM_" ++ s ++ "_CPU", show $ allocInfoVCpus r)
  , ("KM_" ++ s ++ "_NPU", show $ allocInfoNCpus r)
  , ("KM_" ++ s ++ "_MEM", show $ allocInfoMem r)
  , ("KM_" ++ s ++ "_DSK", show $ allocInfoDisk r)
  , ("KM_" ++ s ++ "_SPN", show $ allocInfoSpn r)
  ]

-- | Shows allocations stats.
printAllocationStats :: Node.List -> Node.List -> IO ()
printAllocationStats ini_nl fin_nl = do
  let ini_stats = Cluster.totalResources ini_nl
      fin_stats = Cluster.totalResources fin_nl
      (rini, ralo, runa) = Cluster.computeAllocationDelta ini_stats fin_stats
  printKeysHTS $ formatRSpec "USED" rini
  printKeysHTS $ formatRSpec "POOL" ralo
  printKeysHTS $ formatRSpec "UNAV" runa

-- | Format a list of key\/values as a shell fragment.
printKeysHTS :: [(String, String)] -> IO ()
printKeysHTS = printKeys htsPrefix

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
                     , if Node.haveExclStorage nl
                       then case Instance.getTotalSpindles i of
                              Nothing -> "?"
                              Just sp -> show sp
                       else ""
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
                       [False, False, False, True, True, True, True]

-- | Formats nicely a list of resources.
formatResources :: a -> [(String, a->String)] -> String
formatResources res =
    intercalate ", " . map (\(a, fn) -> a ++ " " ++ fn res)

-- | Print the cluster resources.
printCluster :: Bool -> Cluster.CStats -> Int -> Bool -> IO ()
printCluster True ini_stats node_count _ = do
  printKeysHTS $ map (\(a, fn) -> ("CLUSTER_" ++ a, fn ini_stats))
    clusterDataSpn
  printKeysHTS [("CLUSTER_NODES", printf "%d" node_count)]
  printKeysHTS $ printStats PInitial ini_stats

printCluster False ini_stats node_count print_spn = do
  let cldata = if print_spn then clusterDataSpn else clusterData
  printf "The cluster has %d nodes and the following resources:\n  %s.\n"
         node_count (formatResources ini_stats cldata)::IO ()
  printf "There are %s initial instances on the cluster.\n"
             (if inst_count > 0 then show inst_count else "no" )
      where inst_count = Cluster.csNinst ini_stats

-- | Prints the normal instance spec.
printISpec :: Bool -> RSpec -> SpecType -> DiskTemplate -> Bool -> IO ()
printISpec True ispec spec disk_template _ = do
  printKeysHTS $ map (\(a, fn) -> (prefix ++ "_" ++ a, fn ispec)) specDataSpn
  printKeysHTS [ (prefix ++ "_RQN", printf "%d" req_nodes) ]
  printKeysHTS [ (prefix ++ "_DISK_TEMPLATE",
                  diskTemplateToRaw disk_template) ]
      where req_nodes = Instance.requiredNodes disk_template
            prefix = specPrefix spec

printISpec False ispec spec disk_template print_spn =
  let spdata = if print_spn then specDataSpn else specData
  in printf "%s instance spec is:\n  %s, using disk\
            \ template '%s'.\n"
            (specDescription spec)
            (formatResources ispec spdata) (diskTemplateToRaw disk_template)

-- | Prints the tiered results.
printTiered :: Bool -> [(RSpec, Int)]
            -> Node.List -> Node.List -> [(FailMode, Int)] -> IO ()
printTiered True spec_map nl trl_nl _ = do
  printKeysHTS $ printStats PTiered (Cluster.totalResources trl_nl)
  printKeysHTS [("TSPEC", unwords (formatSpecMap spec_map))]
  printAllocationStats nl trl_nl

printTiered False spec_map ini_nl fin_nl sreason = do
  _ <- printf "Tiered allocation results:\n"
  let spdata = if Node.haveExclStorage ini_nl then specDataSpn else specData
  if null spec_map
    then putStrLn "  - no instances allocated"
    else mapM_ (\(ispec, cnt) ->
                  printf "  - %3d instances of spec %s\n" cnt
                           (formatResources ispec spdata)) spec_map
  printFRScores ini_nl fin_nl sreason

-- | Displays the initial/final cluster scores.
printClusterScores :: Node.List -> Node.List -> IO ()
printClusterScores ini_nl fin_nl = do
  printf "  - initial cluster score: %.8f\n" $ Metrics.compCV ini_nl::IO ()
  printf "  -   final cluster score: %.8f\n" $ Metrics.compCV fin_nl

-- | Displays the cluster efficiency.
printClusterEff :: Cluster.CStats -> Bool -> IO ()
printClusterEff cs print_spn = do
  let format = [("memory", memEff),
                ("disk", dskEff),
                ("vcpu", cpuEff)] ++
               [("spindles", spnEff) | print_spn]
      len = maximum $ map (length . fst) format
  mapM_ (\(s, fn) ->
          printf "  - %*s usage efficiency: %5.2f%%\n" len s (fn cs * 100))
    format

-- | Computes the most likely failure reason.
failureReason :: [(FailMode, Int)] -> String
failureReason = show . fst . head

-- | Sorts the failure reasons.
sortReasons :: [(FailMode, Int)] -> [(FailMode, Int)]
sortReasons = sortBy (flip $ comparing snd)

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
        Nothing -> exitIfBad "failure during allocation" actual_result

  let name = specName mode
      descr = name ++ " allocation"
      ldescr = "after " ++ map toLower descr
      excstor = Node.haveExclStorage new_nl

  printISpec (optMachineReadable opts) spec mode dt excstor

  printAllocationMap (optVerbose opts) descr new_nl new_ixes

  maybePrintNodes (optShowNodes opts) descr (Cluster.printNodes new_nl)

  maybeSaveData (optSaveCluster opts) (map toLower name) ldescr
                    (cdata { cdNodes = new_nl, cdInstances = new_il})

  return (sortReasons reasons, new_nl, length new_ixes, tieredSpecMap new_ixes)

-- | Create an instance from a given spec.
-- For values not implied by the resorce specification (like distribution of
-- of the disk space to individual disks), sensible defaults are guessed (e.g.,
-- having a single disk).
instFromSpec :: RSpec -> DiskTemplate -> Int -> Instance.Instance
instFromSpec spx dt su =
  Instance.create "new" (rspecMem spx) (rspecDsk spx)
    [Instance.Disk (rspecDsk spx) (Just $ rspecSpn spx)]
    (rspecCpu spx) Running [] True (-1) (-1) dt su [] False

combineTiered :: AlgorithmOptions
              -> Maybe Int
              -> Cluster.AllocNodes
              -> Cluster.AllocResult
              -> Instance.Instance
              -> Result Cluster.AllocResult
combineTiered algOpts limit allocnodes result inst = do
  let (_, nl, il, ixes, cstats) = result
      ixes_cnt = length ixes
      (stop, newlimit) = case limit of
        Nothing -> (False, Nothing)
        Just n -> (n <= ixes_cnt, Just (n - ixes_cnt))
  if stop
    then return result
    else Cluster.tieredAlloc algOpts nl il newlimit inst allocnodes ixes cstats

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  exitUnless (null args) "This program doesn't take any arguments."

  let verbose = optVerbose opts
      machine_r = optMachineReadable opts
      independent_grps = optIndependentGroups opts
      accept_existing = optAcceptExisting opts
      algOpts = Alg.fromCLIOptions opts

  orig_cdata@(ClusterData gl fixed_nl il _ ipol) <- loadExternalData opts
  nl <- setNodeStatus opts fixed_nl

  cluster_disk_template <-
    case iPolicyDiskTemplates ipol of
      first_templ:_ -> return first_templ
      _ -> exitErr "null list of disk templates received from cluster"

  let num_instances = Container.size il
      all_nodes = Container.elems fixed_nl
      cdata = orig_cdata { cdNodes = fixed_nl }
      disk_template = fromMaybe cluster_disk_template (optDiskTemplate opts)
      req_nodes = Instance.requiredNodes disk_template
      csf = commonSuffix fixed_nl il
      su = fromMaybe (iSpecSpindleUse $ iPolicyStdSpec ipol)
                     (optSpindleUse opts)

  when (not (null csf) && verbose > 1) $
       hPrintf stderr "Note: Stripping common suffix of '%s' from names\n" csf

  maybePrintNodes (optShowNodes opts) "Initial cluster" (Cluster.printNodes nl)

  when (verbose > 2) $
         hPrintf stderr "Initial coefficients: overall %.8f\n%s"
                 (Metrics.compCV nl) (Metrics.printStats "  " nl)

  printCluster machine_r (Cluster.totalResources nl) (length all_nodes)
    (Node.haveExclStorage nl)

  let (bad_nodes, _)  = Cluster.computeBadItems nl il
      bad_grp_idxs = filter (not . redundantGrp algOpts nl il)
                       $ Container.keys gl

  when ((verbose > 3) && (not . null $ bad_nodes))
    . hPrintf stderr "Bad nodes: %s\n" . show . map Node.name $ bad_nodes

  when ((verbose > 3) && not (null bad_grp_idxs))
    . hPrintf stderr "Bad groups: %s\n" . show
    $ map (Group.name . flip Container.find gl) bad_grp_idxs

  let markGrpsUnalloc = foldl (flip $ IntMap.adjust Group.setUnallocable)
      gl' = if accept_existing
              then gl
              else markGrpsUnalloc gl $ map Node.group bad_nodes
      (gl'', algOpts') = if independent_grps
                           then ( markGrpsUnalloc gl' bad_grp_idxs
                                , algOpts { algCapacityIgnoreGroups
                                            = bad_grp_idxs }
                                )
                           else (gl', algOpts)
      grps_remaining = any Group.isAllocable $ IntMap.elems gl''
      stop_allocation = case () of
                          _ | accept_existing-> Nothing
                          _ | independent_grps && grps_remaining -> Nothing
                          _ | null bad_nodes -> Nothing
                          _ -> Just ([(FailN1, 1)]::FailStats, nl, il, [], [])
      alloclimit = if optMaxLength opts == -1
                   then Nothing
                   else Just (optMaxLength opts)

  allocnodes <- exitIfBad "failure during allocation" $
                Cluster.genAllocNodes algOpts' gl'' nl req_nodes True

  when (verbose > 3)
    . hPrintf stderr "Allocatable nodes: %s\n" $ show allocnodes

  -- Run the tiered allocation

  let minmaxes = iPolicyMinMaxISpecs ipol
      tspecs = case optTieredSpec opts of
                 Nothing -> map (rspecFromISpec . minMaxISpecsMaxSpec)
                            minmaxes
                 Just t -> [t]
      tinsts = map (\ts -> instFromSpec ts disk_template su) tspecs

  tspec <- case tspecs of
    [] -> exitErr "Empty list of specs received from the cluster"
    t:_ -> return t

  (treason, trl_nl, _, spec_map) <-
    runAllocation cdata stop_allocation
       (foldM (combineTiered algOpts' alloclimit allocnodes)
              ([], nl, il, [], [])
              tinsts
       )
       tspec disk_template SpecTiered opts

  printTiered machine_r spec_map nl trl_nl treason

  -- Run the standard (avg-mode) allocation

  let ispec = fromMaybe (rspecFromISpec (iPolicyStdSpec ipol))
              (optStdSpec opts)

  (sreason, fin_nl, allocs, _) <-
      runAllocation cdata stop_allocation
            (Cluster.iterateAlloc algOpts' nl il alloclimit
             (instFromSpec ispec disk_template su) allocnodes [] [])
            ispec disk_template SpecNormal opts

  printResults machine_r nl fin_nl num_instances allocs sreason

  -- Print final result

  printFinalHTS machine_r

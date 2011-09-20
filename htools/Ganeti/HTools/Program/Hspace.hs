{-| Cluster space sizing

-}

{-

Copyright (C) 2009, 2010, 2011 Google Inc.

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

module Ganeti.HTools.Program.Hspace (main) where

import Control.Monad
import Data.Char (toUpper, isAlphaNum)
import Data.Function (on)
import Data.List
import Data.Maybe (isJust, fromJust)
import Data.Ord (comparing)
import System (exitWith, ExitCode(..))
import System.IO
import qualified System

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
    , oIMem
    , oIDisk
    , oIVcpus
    , oMachineReadable
    , oMaxCpu
    , oMaxSolLength
    , oMinDisk
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
specDescription SpecNormal = "Normal (fixed-size)"
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
  printf "  - most likely failure reason: %s\n" $ failureReason sreason::IO ()
  printClusterScores ini_nl fin_nl
  printClusterEff (Cluster.totalResources fin_nl)

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
formatRSpec :: Double -> String -> RSpec -> [(String, String)]
formatRSpec m_cpu s r =
    [ ("KM_" ++ s ++ "_CPU", show $ rspecCpu r)
    , ("KM_" ++ s ++ "_NPU", show $ fromIntegral (rspecCpu r) / m_cpu)
    , ("KM_" ++ s ++ "_MEM", show $ rspecMem r)
    , ("KM_" ++ s ++ "_DSK", show $ rspecDsk r)
    ]

-- | Shows allocations stats.
printAllocationStats :: Double -> Node.List -> Node.List -> IO ()
printAllocationStats m_cpu ini_nl fin_nl = do
  let ini_stats = Cluster.totalResources ini_nl
      fin_stats = Cluster.totalResources fin_nl
      (rini, ralo, runa) = Cluster.computeAllocationDelta ini_stats fin_stats
  printKeys $ formatRSpec m_cpu  "USED" rini
  printKeys $ formatRSpec m_cpu "POOL"ralo
  printKeys $ formatRSpec m_cpu "UNAV" runa

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
    hPutStrLn stderr msg
    hPutStr stderr . unlines . map ((:) ' ' .  intercalate " ") $
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
               diskTemplateToString disk_template) ]
      where req_nodes = Instance.requiredNodes disk_template
            prefix = specPrefix spec

printISpec False ispec spec disk_template =
  printf "%s instance spec is:\n  %s, using disk\
         \ template '%s'.\n"
         (specDescription spec)
         (formatResources ispec specData) (diskTemplateToString disk_template)

-- | Prints the tiered results.
printTiered :: Bool -> [(RSpec, Int)] -> Double
            -> Node.List -> Node.List -> [(FailMode, Int)] -> IO ()
printTiered True spec_map m_cpu nl trl_nl _ = do
  printKeys $ printStats PTiered (Cluster.totalResources trl_nl)
  printKeys [("TSPEC", intercalate " " (formatSpecMap spec_map))]
  printAllocationStats m_cpu nl trl_nl

printTiered False spec_map _ ini_nl fin_nl sreason = do
  _ <- printf "Tiered allocation results:\n"
  mapM_ (\(ispec, cnt) ->
             printf "  - %3d instances of spec %s\n" cnt
                        (formatResources ispec specData)) spec_map
  printf "  - most likely failure reason: %s\n" $ failureReason sreason::IO ()
  printClusterScores ini_nl fin_nl
  printClusterEff (Cluster.totalResources fin_nl)

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

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, args) <- parseOpts cmd_args "hspace" options

  unless (null args) $ do
         hPutStrLn stderr "Error: this program doesn't take any arguments."
         exitWith $ ExitFailure 1

  let verbose = optVerbose opts
      ispec = optISpec opts
      shownodes = optShowNodes opts
      disk_template = optDiskTemplate opts
      req_nodes = Instance.requiredNodes disk_template
      machine_r = optMachineReadable opts

  (ClusterData gl fixed_nl il ctags) <- loadExternalData opts

  let num_instances = length $ Container.elems il

  let offline_passed = optOffline opts
      all_nodes = Container.elems fixed_nl
      offline_lkp = map (lookupName (map Node.name all_nodes)) offline_passed
      offline_wrong = filter (not . goodLookupResult) offline_lkp
      offline_names = map lrContent offline_lkp
      offline_indices = map Node.idx $
                        filter (\n -> Node.name n `elem` offline_names)
                               all_nodes
      m_cpu = optMcpu opts
      m_dsk = optMdsk opts

  when (not (null offline_wrong)) $ do
         hPrintf stderr "Error: Wrong node name(s) set as offline: %s\n"
                     (commaJoin (map lrContent offline_wrong)) :: IO ()
         exitWith $ ExitFailure 1

  when (req_nodes /= 1 && req_nodes /= 2) $ do
         hPrintf stderr "Error: Invalid required nodes (%d)\n"
                                            req_nodes :: IO ()
         exitWith $ ExitFailure 1

  let nm = Container.map (\n -> if Node.idx n `elem` offline_indices
                                then Node.setOffline n True
                                else n) fixed_nl
      nl = Container.map (flip Node.setMdsk m_dsk . flip Node.setMcpu m_cpu)
           nm
      csf = commonSuffix fixed_nl il

  when (length csf > 0 && verbose > 1) $
       hPrintf stderr "Note: Stripping common suffix of '%s' from names\n" csf

  when (isJust shownodes) $
       do
         hPutStrLn stderr "Initial cluster status:"
         hPutStrLn stderr $ Cluster.printNodes nl (fromJust shownodes)

  let ini_cv = Cluster.compCV nl
      ini_stats = Cluster.totalResources nl

  when (verbose > 2) $
         hPrintf stderr "Initial coefficients: overall %.8f, %s\n"
                 ini_cv (Cluster.printStats nl)

  printCluster machine_r ini_stats (length all_nodes)

  printISpec machine_r ispec SpecNormal disk_template

  let bad_nodes = fst $ Cluster.computeBadItems nl il
      stop_allocation = length bad_nodes > 0
      result_noalloc = ([(FailN1, 1)]::FailStats, nl, il, [], [])

  -- utility functions
  let iofspec spx = Instance.create "new" (rspecMem spx) (rspecDsk spx)
                    (rspecCpu spx) "running" [] True (-1) (-1) disk_template
      exitifbad val = (case val of
                         Bad s -> do
                           hPrintf stderr "Failure: %s\n" s :: IO ()
                           exitWith $ ExitFailure 1
                         Ok x -> return x)


  let reqinst = iofspec ispec
      alloclimit = if optMaxLength opts == -1
                   then Nothing
                   else Just (optMaxLength opts)

  allocnodes <- exitifbad $ Cluster.genAllocNodes gl nl req_nodes True

  -- Run the tiered allocation, if enabled

  (case optTieredSpec opts of
     Nothing -> return ()
     Just tspec -> do
       (treason, trl_nl, trl_il, trl_ixes, _) <-
           if stop_allocation
           then return result_noalloc
           else exitifbad (Cluster.tieredAlloc nl il alloclimit (iofspec tspec)
                                  allocnodes [] [])
       let spec_map' = tieredSpecMap trl_ixes
           treason' = sortReasons treason

       printAllocationMap verbose "Tiered allocation map" trl_nl trl_ixes

       maybePrintNodes shownodes "Tiered allocation"
                           (Cluster.printNodes trl_nl)

       maybeSaveData (optSaveCluster opts) "tiered" "after tiered allocation"
                     (ClusterData gl trl_nl trl_il ctags)

       printISpec machine_r tspec SpecTiered disk_template

       printTiered machine_r spec_map' m_cpu nl trl_nl treason'
       )

  -- Run the standard (avg-mode) allocation

  (ereason, fin_nl, fin_il, ixes, _) <-
      if stop_allocation
      then return result_noalloc
      else exitifbad (Cluster.iterateAlloc nl il alloclimit
                      reqinst allocnodes [] [])

  let allocs = length ixes
      sreason = sortReasons ereason

  printAllocationMap verbose "Standard allocation map" fin_nl ixes

  maybePrintNodes shownodes "Standard allocation" (Cluster.printNodes fin_nl)

  maybeSaveData (optSaveCluster opts) "alloc" "after standard allocation"
       (ClusterData gl fin_nl fin_il ctags)

  printResults machine_r nl fin_nl num_instances allocs sreason

  printFinal machine_r

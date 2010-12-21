{-| Cluster space sizing

-}

{-

Copyright (C) 2009, 2010 Google Inc.

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

module Main (main) where

import Data.Char (toUpper, isAlphaNum)
import Data.List
import Data.Maybe (isJust, fromJust)
import Data.Ord (comparing)
import Monad
import System (exitWith, ExitCode(..))
import System.FilePath
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
import Ganeti.HTools.Text (serializeCluster)
import Ganeti.HTools.Loader (ClusterData(..))

-- | Options list and functions
options :: [OptType]
options =
    [ oPrintNodes
    , oDataFile
    , oNodeSim
    , oRapiMaster
    , oLuxiSocket
    , oVerbose
    , oQuiet
    , oOfflineNode
    , oIMem
    , oIDisk
    , oIVcpus
    , oINodes
    , oMaxCpu
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
            , ("MEM_EFF",
               \cs -> printf "%.8f" (fromIntegral (Cluster.csImem cs) /
                                     Cluster.csTmem cs))
            , ("DSK_FREE", printf "%d" . Cluster.csFdsk)
            , ("DSK_AVAIL", printf "%d". Cluster.csAdsk)
            , ("DSK_RESVD",
               \cs -> printf "%d" (Cluster.csFdsk cs - Cluster.csAdsk cs))
            , ("DSK_INST", printf "%d" . Cluster.csIdsk)
            , ("DSK_EFF",
               \cs -> printf "%.8f" (fromIntegral (Cluster.csIdsk cs) /
                                    Cluster.csTdsk cs))
            , ("CPU_INST", printf "%d" . Cluster.csIcpu)
            , ("CPU_EFF",
               \cs -> printf "%.8f" (fromIntegral (Cluster.csIcpu cs) /
                                     Cluster.csTcpu cs))
            , ("MNODE_MEM_AVAIL", printf "%d" . Cluster.csMmem)
            , ("MNODE_DSK_AVAIL", printf "%d" . Cluster.csMdsk)
            ]

specData :: [(String, RSpec -> String)]
specData = [ ("MEM", printf "%d" . rspecMem)
           , ("DSK", printf "%d" . rspecDsk)
           , ("CPU", printf "%d" . rspecCpu)
           ]

clusterData :: [(String, Cluster.CStats -> String)]
clusterData = [ ("MEM", printf "%.0f" . Cluster.csTmem)
              , ("DSK", printf "%.0f" . Cluster.csTdsk)
              , ("CPU", printf "%.0f" . Cluster.csTcpu)
              , ("VCPU", printf "%d" . Cluster.csVcpu)
              ]

-- | Function to print stats for a given phase
printStats :: Phase -> Cluster.CStats -> [(String, String)]
printStats ph cs =
  map (\(s, fn) -> (printf "%s_%s" kind s, fn cs)) statsData
  where kind = case ph of
                 PInitial -> "INI"
                 PFinal -> "FIN"
                 PTiered -> "TRL"

-- | Print final stats and related metrics
printResults :: Node.List -> Int -> Int -> [(FailMode, Int)] -> IO ()
printResults fin_nl num_instances allocs sreason = do
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
  -- this should be the final entry
  printKeys [("OK", "1")]

formatRSpec :: Double -> String -> RSpec -> [(String, String)]
formatRSpec m_cpu s r =
    [ ("KM_" ++ s ++ "_CPU", show $ rspecCpu r)
    , ("KM_" ++ s ++ "_NPU", show $ fromIntegral (rspecCpu r) / m_cpu)
    , ("KM_" ++ s ++ "_MEM", show $ rspecMem r)
    , ("KM_" ++ s ++ "_DSK", show $ rspecDsk r)
    ]

printAllocationStats :: Double -> Node.List -> Node.List -> IO ()
printAllocationStats m_cpu ini_nl fin_nl = do
  let ini_stats = Cluster.totalResources ini_nl
      fin_stats = Cluster.totalResources fin_nl
      (rini, ralo, runa) = Cluster.computeAllocationDelta ini_stats fin_stats
  printKeys $ formatRSpec m_cpu  "USED" rini
  printKeys $ formatRSpec m_cpu "POOL"ralo
  printKeys $ formatRSpec m_cpu "UNAV" runa

-- | Ensure a value is quoted if needed
ensureQuoted :: String -> String
ensureQuoted v = if not (all (\c -> (isAlphaNum c || c == '.')) v)
                 then '\'':v ++ "'"
                 else v

-- | Format a list of key\/values as a shell fragment
printKeys :: [(String, String)] -> IO ()
printKeys = mapM_ (\(k, v) ->
                   printf "HTS_%s=%s\n" (map toUpper k) (ensureQuoted v))

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

  (ClusterData gl fixed_nl il ctags) <- loadExternalData opts

  printKeys $ map (\(a, fn) -> ("SPEC_" ++ a, fn ispec)) specData
  printKeys [ ("SPEC_RQN", printf "%d" (optINodes opts)) ]

  let num_instances = length $ Container.elems il

  let offline_names = optOffline opts
      all_nodes = Container.elems fixed_nl
      all_names = map Node.name all_nodes
      offline_wrong = filter (`notElem` all_names) offline_names
      offline_indices = map Node.idx $
                        filter (\n ->
                                 Node.name n `elem` offline_names ||
                                 Node.alias n `elem` offline_names)
                               all_nodes
      req_nodes = optINodes opts
      m_cpu = optMcpu opts
      m_dsk = optMdsk opts

  when (length offline_wrong > 0) $ do
         hPrintf stderr "Error: Wrong node name(s) set as offline: %s\n"
                     (commaJoin offline_wrong) :: IO ()
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

  printKeys $ map (\(a, fn) -> ("CLUSTER_" ++ a, fn ini_stats)) clusterData
  printKeys [("CLUSTER_NODES", printf "%d" (length all_nodes))]
  printKeys $ printStats PInitial ini_stats

  let bad_nodes = fst $ Cluster.computeBadItems nl il
      stop_allocation = length bad_nodes > 0
      result_noalloc = ([(FailN1, 1)]::FailStats, nl, il, [])

  -- utility functions
  let iofspec spx = Instance.create "new" (rspecMem spx) (rspecDsk spx)
                    (rspecCpu spx) "running" [] (-1) (-1)
      exitifbad val = (case val of
                         Bad s -> do
                           hPrintf stderr "Failure: %s\n" s :: IO ()
                           exitWith $ ExitFailure 1
                         Ok x -> return x)


  let reqinst = iofspec ispec

  -- Run the tiered allocation, if enabled

  (case optTieredSpec opts of
     Nothing -> return ()
     Just tspec -> do
       (_, trl_nl, trl_il, trl_ixes) <-
           if stop_allocation
           then return result_noalloc
           else exitifbad (Cluster.tieredAlloc nl il (iofspec tspec)
                                  req_nodes [])
       let spec_map' = Cluster.tieredSpecMap trl_ixes

       when (verbose > 1) $ do
         hPutStrLn stderr "Tiered allocation map"
         hPutStr stderr . unlines . map ((:) ' ' .  intercalate " ") $
                 formatTable (map (printInstance trl_nl) (reverse trl_ixes))
                                 [False, False, False, True, True, True]

       when (isJust shownodes) $ do
         hPutStrLn stderr ""
         hPutStrLn stderr "Tiered allocation status:"
         hPutStrLn stderr $ Cluster.printNodes trl_nl (fromJust shownodes)

       when (isJust $ optSaveCluster opts) $
            do
              let out_path = (fromJust $ optSaveCluster opts) <.> "tiered"
                  adata = serializeCluster
                          (ClusterData gl trl_nl trl_il ctags)
              writeFile out_path adata
              hPrintf stderr "The cluster state after tiered allocation\
                             \ has been written to file '%s'\n"
                             out_path
       printKeys $ printStats PTiered (Cluster.totalResources trl_nl)
       printKeys [("TSPEC", intercalate " " spec_map')]
       printAllocationStats m_cpu nl trl_nl)

  -- Run the standard (avg-mode) allocation

  (ereason, fin_nl, fin_il, ixes) <-
      if stop_allocation
      then return result_noalloc
      else exitifbad (Cluster.iterateAlloc nl il reqinst req_nodes [])

  let allocs = length ixes
      fin_ixes = reverse ixes
      sreason = reverse $ sortBy (comparing snd) ereason

  when (verbose > 1) $ do
         hPutStrLn stderr "Instance map"
         hPutStr stderr . unlines . map ((:) ' ' .  intercalate " ") $
                 formatTable (map (printInstance fin_nl) fin_ixes)
                                 [False, False, False, True, True, True]
  when (isJust shownodes) $
       do
         hPutStrLn stderr ""
         hPutStrLn stderr "Final cluster status:"
         hPutStrLn stderr $ Cluster.printNodes fin_nl (fromJust shownodes)

  when (isJust $ optSaveCluster opts) $
       do
         let out_path = (fromJust $ optSaveCluster opts) <.> "alloc"
             adata = serializeCluster (ClusterData gl fin_nl fin_il ctags)
         writeFile out_path adata
         hPrintf stderr "The cluster state after standard allocation\
                        \ has been written to file '%s'\n"
                 out_path

  printResults fin_nl num_instances allocs sreason

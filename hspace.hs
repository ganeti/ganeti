{-| Cluster space sizing

-}

{-

Copyright (C) 2009 Google Inc.

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

import Data.Char (toUpper)
import Data.List
import Data.Function
import Data.Maybe (isJust, fromJust)
import Monad
import System
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

-- | Options list and functions
options :: [OptType]
options =
    [ oPrintNodes
    , oNodeFile
    , oInstFile
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
            , ("DSK_AVAIL", printf "%d ". Cluster.csAdsk)
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
              ]

-- | Recursively place instances on the cluster until we're out of space
iterateDepth :: Node.List
             -> Instance.List
             -> Instance.Instance
             -> Int
             -> [Instance.Instance]
             -> Result (FailStats, Node.List, [Instance.Instance])
iterateDepth nl il newinst nreq ixes =
      let depth = length ixes
          newname = printf "new-%d" depth::String
          newidx = length (Container.elems il) + depth
          newi2 = Instance.setIdx (Instance.setName newinst newname) newidx
      in case Cluster.tryAlloc nl il newi2 nreq of
           Bad s -> Bad s
           Ok (errs, _, sols3) ->
               case sols3 of
                 Nothing -> Ok (Cluster.collapseFailures errs, nl, ixes)
                 Just (_, (xnl, xi, _)) ->
                     iterateDepth xnl il newinst nreq $! (xi:ixes)

tieredAlloc :: Node.List
            -> Instance.List
            -> Instance.Instance
            -> Int
            -> [Instance.Instance]
            -> Result (FailStats, Node.List, [Instance.Instance])
tieredAlloc nl il newinst nreq ixes =
    case iterateDepth nl il newinst nreq ixes of
      Bad s -> Bad s
      Ok (errs, nl', ixes') ->
          case Instance.shrinkByType newinst . fst . last $
               sortBy (compare `on` snd) errs of
            Bad _ -> Ok (errs, nl', ixes')
            Ok newinst' ->
                tieredAlloc nl' il newinst' nreq ixes'


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
                                 (Cluster.csNinst fin_stats)
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

-- | Format a list of key/values as a shell fragment
printKeys :: [(String, String)] -> IO ()
printKeys = mapM_ (\(k, v) -> printf "HTS_%s=%s\n" (map toUpper k) v)

printInstance :: Node.List -> Instance.Instance -> [String]
printInstance nl i = [ Instance.name i
                     , (Container.nameOf nl $ Instance.pNode i)
                     , (let sdx = Instance.sNode i
                        in if sdx == Node.noSecondary then ""
                           else Container.nameOf nl sdx)
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

  (fixed_nl, il, _, csf) <- loadExternalData opts

  printKeys $ map (\(a, fn) -> ("SPEC_" ++ a, fn ispec)) specData
  printKeys [ ("SPEC_RQN", printf "%d" (optINodes opts)) ]

  let num_instances = length $ Container.elems il

  let offline_names = optOffline opts
      all_nodes = Container.elems fixed_nl
      all_names = map Node.name all_nodes
      offline_wrong = filter (flip notElem all_names) offline_names
      offline_indices = map Node.idx $
                        filter (\n -> elem (Node.name n) offline_names)
                               all_nodes
      req_nodes = optINodes opts
      m_cpu = optMcpu opts
      m_dsk = optMdsk opts

  when (length offline_wrong > 0) $ do
         hPrintf stderr "Error: Wrong node name(s) set as offline: %s\n"
                     (commaJoin offline_wrong)
         exitWith $ ExitFailure 1

  when (req_nodes /= 1 && req_nodes /= 2) $ do
         hPrintf stderr "Error: Invalid required nodes (%d)\n" req_nodes
         exitWith $ ExitFailure 1

  let nm = Container.map (\n -> if elem (Node.idx n) offline_indices
                                then Node.setOffline n True
                                else n) fixed_nl
      nl = Container.map (flip Node.setMdsk m_dsk . flip Node.setMcpu m_cpu)
           nm

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
  when (length bad_nodes > 0) $ do
         -- This is failn1 case, so we print the same final stats and
         -- exit early
         printResults nl num_instances 0 [(FailN1, 1)]
         exitWith ExitSuccess

  -- utility functions
  let iofspec spx = Instance.create "new" (rspecMem spx) (rspecDsk spx)
                    (rspecCpu spx) "ADMIN_down" [] (-1) (-1)
      exitifbad val = (case val of
                         Bad s -> do
                           hPrintf stderr "Failure: %s\n" s
                           exitWith $ ExitFailure 1
                         Ok x -> return x)


  let reqinst = iofspec ispec

  -- Run the tiered allocation, if enabled

  (case optTieredSpec opts of
     Nothing -> return ()
     Just tspec -> do
       let tresu = tieredAlloc nl il (iofspec tspec) req_nodes []
       (_, trl_nl, trl_ixes) <- exitifbad tresu
       let fin_trl_ixes = reverse trl_ixes
           ix_byspec = groupBy ((==) `on` Instance.specOf) fin_trl_ixes
           spec_map = map (\ixs -> (Instance.specOf $ head ixs, length ixs))
                      ix_byspec::[(RSpec, Int)]
           spec_map' = map (\(spec, cnt) ->
                                printf "%d,%d,%d=%d" (rspecMem spec)
                                       (rspecDsk spec) (rspecCpu spec) cnt)
                       spec_map::[String]

       when (verbose > 1) $ do
         hPutStrLn stderr "Tiered allocation map"
         hPutStr stderr . unlines . map ((:) ' ' .  intercalate " ") $
                 formatTable (map (printInstance trl_nl) fin_trl_ixes)
                                 [False, False, False, True, True, True]

       when (isJust shownodes) $ do
         hPutStrLn stderr ""
         hPutStrLn stderr "Tiered allocation status:"
         hPutStrLn stderr $ Cluster.printNodes trl_nl (fromJust shownodes)

       printKeys $ printStats PTiered (Cluster.totalResources trl_nl)
       printKeys [("TSPEC", intercalate " " spec_map')])

  -- Run the standard (avg-mode) allocation

  let result = iterateDepth nl il reqinst req_nodes []
  (ereason, fin_nl, ixes) <- exitifbad result

  let allocs = length ixes
      fin_ixes = reverse ixes
      sreason = reverse $ sortBy (compare `on` snd) ereason

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

  printResults fin_nl num_instances allocs sreason

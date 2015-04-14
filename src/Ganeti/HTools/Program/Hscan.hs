{-| Scan clusters via RAPI or LUXI and write state data files.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

module Ganeti.HTools.Program.Hscan
  ( main
  , options
  , arguments
  ) where

import Control.Monad
import Data.Maybe (isJust, fromJust, fromMaybe)
import System.Exit
import System.IO
import System.FilePath
import System.Time

import Text.Printf (printf)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Backend.Rapi as Rapi
import qualified Ganeti.HTools.Backend.Luxi as Luxi
import qualified Ganeti.Path as Path
import Ganeti.HTools.Loader (checkData, mergeData, ClusterData(..))
import Ganeti.HTools.Backend.Text (serializeCluster)

import Ganeti.Common
import Ganeti.HTools.CLI

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ oPrintNodes
    , oOutputDir
    , luxi
    , oVerbose
    , oNoHeaders
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = [ArgCompletion OptComplHost 0 Nothing]

-- | Return a one-line summary of cluster state.
printCluster :: Node.List -> Instance.List
             -> String
printCluster nl il =
  let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
      ccv = Metrics.compCV nl
      nodes = Container.elems nl
      insts = Container.elems il
      t_ram = sum . map Node.tMem $ nodes
      t_dsk = sum . map Node.tDsk $ nodes
      f_ram = sum . map Node.fMem $ nodes
      f_dsk = sum . map Node.fDsk $ nodes
  in printf "%5d %5d %5d %5d %6.0f %6d %6.0f %6d %.8f"
       (length nodes) (length insts)
       (length bad_nodes) (length bad_instances)
       t_ram f_ram (t_dsk / 1024) (f_dsk `div` 1024) ccv

-- | Replace slashes with underscore for saving to filesystem.
fixSlash :: String -> String
fixSlash = map (\x -> if x == '/' then '_' else x)

-- | Generates serialized data from loader input.
processData :: ClockTime -> ClusterData -> Result ClusterData
processData now input_data = do
  cdata@(ClusterData _ nl il _ _) <- mergeData [] [] [] [] now input_data
  let (_, fix_nl) = checkData nl il
  return cdata { cdNodes = fix_nl }

-- | Writes cluster data out.
writeData :: Int
          -> String
          -> Options
          -> Result ClusterData
          -> IO Bool
writeData _ name _ (Bad err) =
  printf "\nError for %s: failed to load data. Details:\n%s\n" name err >>
  return False

writeData nlen name opts (Ok cdata) = do
  now <- getClockTime
  let fixdata = processData now cdata
  case fixdata of
    Bad err -> printf "\nError for %s: failed to process data. Details:\n%s\n"
               name err >> return False
    Ok processed -> writeDataInner nlen name opts cdata processed

-- | Inner function for writing cluster data to disk.
writeDataInner :: Int
               -> String
               -> Options
               -> ClusterData
               -> ClusterData
               -> IO Bool
writeDataInner nlen name opts cdata fixdata = do
  let (ClusterData _ nl il _ _) = fixdata
  printf "%-*s " nlen name :: IO ()
  hFlush stdout
  let shownodes = optShowNodes opts
      odir = optOutPath opts
      oname = odir </> fixSlash name
  putStrLn $ printCluster nl il
  hFlush stdout
  when (isJust shownodes) .
       putStr $ Cluster.printNodes nl (fromJust shownodes)
  writeFile (oname <.> "data") (serializeCluster cdata)
  return True

-- | Main function.
main :: Options -> [String] -> IO ()
main opts clusters = do
  let local = "LOCAL"

  let nlen = if null clusters
             then length local
             else maximum . map length $ clusters

  unless (optNoHeaders opts) $
         printf "%-*s %5s %5s %5s %5s %6s %6s %6s %6s %10s\n" nlen
                "Name" "Nodes" "Inst" "BNode" "BInst" "t_mem" "f_mem"
                "t_disk" "f_disk" "Score"

  when (null clusters) $ do
         def_socket <- Path.defaultQuerySocket
         let lsock = fromMaybe def_socket (optLuxi opts)
         let name = local
         input_data <- Luxi.loadData lsock
         result <- writeData nlen name opts input_data
         unless result . exitWith $ ExitFailure 2

  results <- mapM (\name -> Rapi.loadData name >>= writeData nlen name opts)
             clusters
  unless (and results) $ exitWith (ExitFailure 2)

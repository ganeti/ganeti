{-| IAllocator plugin for Ganeti.

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

module Ganeti.HTools.Program.Hail (main) where

import Control.Monad
import System.IO
import qualified System

import qualified Ganeti.HTools.Cluster as Cluster

import Ganeti.HTools.CLI
import Ganeti.HTools.IAlloc
import Ganeti.HTools.Loader (Request(..), ClusterData(..))
import Ganeti.HTools.ExtLoader (maybeSaveData)

-- | Options list and functions.
options :: [OptType]
options =
    [ oPrintNodes
    , oSaveCluster
    , oDataFile
    , oNodeSim
    , oVerbose
    , oShowVer
    , oShowHelp
    ]

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, args) <- parseOpts cmd_args "hail" options

  let shownodes = optShowNodes opts
      verbose = optVerbose opts
      savecluster = optSaveCluster opts

  request <- readRequest opts args

  let Request rq cdata = request

  when (verbose > 1) $
       hPutStrLn stderr $ "Received request: " ++ show rq

  when (verbose > 2) $
       hPutStrLn stderr $ "Received cluster data: " ++ show cdata

  maybePrintNodes shownodes "Initial cluster"
       (Cluster.printNodes (cdNodes cdata))

  maybeSaveData savecluster "pre-ialloc" "before iallocator run" cdata

  let (maybe_ni, resp) = runIAllocator request
      (fin_nl, fin_il) = maybe (cdNodes cdata, cdInstances cdata) id maybe_ni
  putStrLn resp

  maybePrintNodes shownodes "Final cluster" (Cluster.printNodes fin_nl)

  maybeSaveData savecluster "post-ialloc" "after iallocator run"
       (cdata { cdNodes = fin_nl, cdInstances = fin_il})

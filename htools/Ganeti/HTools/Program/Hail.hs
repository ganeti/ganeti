{-| IAllocator plugin for Ganeti.

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

module Ganeti.HTools.Program.Hail (main, options) where

import Control.Monad
import Data.Maybe (fromMaybe, isJust)
import System.IO
import System.Exit

import qualified Ganeti.HTools.Cluster as Cluster

import Ganeti.HTools.CLI
import Ganeti.HTools.IAlloc
import Ganeti.HTools.Loader (Request(..), ClusterData(..))
import Ganeti.HTools.ExtLoader (maybeSaveData, loadExternalData)

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

wrapReadRequest :: Options -> [String] -> IO Request
wrapReadRequest opts args = do
  when (null args) $ do
    hPutStrLn stderr "Error: this program needs an input file."
    exitWith $ ExitFailure 1

  r1 <- readRequest (head args)
  if isJust (optDataFile opts) ||  (not . null . optNodeSim) opts
    then do
      cdata <- loadExternalData opts
      let Request rqt _ = r1
      return $ Request rqt cdata
    else return r1


-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  let shownodes = optShowNodes opts
      verbose = optVerbose opts
      savecluster = optSaveCluster opts

  request <- wrapReadRequest opts args

  let Request rq cdata = request

  when (verbose > 1) .
       hPutStrLn stderr $ "Received request: " ++ show rq

  when (verbose > 2) .
       hPutStrLn stderr $ "Received cluster data: " ++ show cdata

  maybePrintNodes shownodes "Initial cluster"
       (Cluster.printNodes (cdNodes cdata))

  maybeSaveData savecluster "pre-ialloc" "before iallocator run" cdata

  let (maybe_ni, resp) = runIAllocator request
      (fin_nl, fin_il) = fromMaybe (cdNodes cdata, cdInstances cdata) maybe_ni
  putStrLn resp

  maybePrintNodes shownodes "Final cluster" (Cluster.printNodes fin_nl)

  maybeSaveData savecluster "post-ialloc" "after iallocator run"
       (cdata { cdNodes = fin_nl, cdInstances = fin_il})

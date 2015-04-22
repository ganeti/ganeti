{-| IAllocator plugin for Ganeti.

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

module Ganeti.HTools.Program.Hail
  ( main
  , options
  , arguments
  ) where

import Control.Monad
import Control.Monad.Writer (runWriterT)
import Data.Maybe (fromMaybe, isJust)
import System.IO

import qualified Ganeti.HTools.AlgorithmParams as Alg
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Dedicated as Dedicated

import Ganeti.Common
import Ganeti.HTools.CLI
import Ganeti.HTools.Backend.IAlloc
import qualified Ganeti.HTools.Backend.MonD as MonD
import Ganeti.HTools.Loader (Request(..), ClusterData(..), isAllocationRequest)
import Ganeti.HTools.ExtLoader (maybeSaveData, loadExternalData)
import Ganeti.Utils

-- | Options list and functions.
options :: IO [OptType]
options =
  return
    [ oPrintNodes
    , oSaveCluster
    , oDataFile
    , oNodeSim
    , oVerbose
    , oIgnoreDyn
    , oIgnoreSoftErrors
    , oNoCapacityChecks
    , oRestrictToNodes
    , oMonD
    , oMonDXen
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = [ArgCompletion OptComplFile 1 (Just 1)]

wrapReadRequest :: Options -> [String] -> IO Request
wrapReadRequest opts args = do
  r1 <- case args of
          []    -> exitErr "This program needs an input file."
          _:_:_ -> exitErr "Only one argument is accepted (the input file)"
          x:_   -> readRequest x

  if isJust (optDataFile opts) ||  (not . null . optNodeSim) opts
    then do
      cdata <- loadExternalData opts
      let Request rqt _ = r1
      return $ Request rqt cdata
    else do
      let Request rqt cdata = r1
      (cdata', _) <- runWriterT $ if optMonD opts
                                    then MonD.queryAllMonDDCs cdata opts
                                    else return cdata
      return $ Request rqt cdata'

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

  let dedicatedAlloc = maybe False (Dedicated.isDedicated cdata)
                       $ isAllocationRequest rq

  when (verbose > 1 && dedicatedAlloc) $
      hPutStrLn stderr "Allocation on a dedicated cluster;\
                       \ using lost-allocations metrics."

  maybePrintNodes shownodes "Initial cluster"
       (Cluster.printNodes (cdNodes cdata))

  maybeSaveData savecluster "pre-ialloc" "before iallocator run" cdata

  let runAlloc = if dedicatedAlloc
                   then Dedicated.runDedicatedAllocation
                   else runIAllocator
      (maybe_ni, resp) = runAlloc (Alg.fromCLIOptions opts) request
      (fin_nl, fin_il) = fromMaybe (cdNodes cdata, cdInstances cdata) maybe_ni
  putStrLn resp

  maybePrintNodes shownodes "Final cluster" (Cluster.printNodes fin_nl)

  maybeSaveData savecluster "post-ialloc" "after iallocator run"
       (cdata { cdNodes = fin_nl, cdInstances = fin_il})

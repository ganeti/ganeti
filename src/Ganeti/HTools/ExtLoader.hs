{-| External data loader.

This module holds the external data loading, and thus is the only one
depending (via the specialized Text\/Rapi\/Luxi modules) on the actual
libraries implementing the low-level protocols.

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

module Ganeti.HTools.ExtLoader
  ( loadExternalData
  , commonSuffix
  , maybeSaveData
  ) where

import Control.Monad
import Control.Monad.Writer (runWriterT)
import Control.Exception
import Data.Maybe (isJust, fromJust)
import Data.Monoid (getAll)
import System.FilePath
import System.IO
import System.Time (getClockTime)
import Text.Printf (hPrintf)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.Backend.Luxi as Luxi
import qualified Ganeti.HTools.Backend.Rapi as Rapi
import qualified Ganeti.HTools.Backend.Simu as Simu
import qualified Ganeti.HTools.Backend.Text as Text
import qualified Ganeti.HTools.Backend.IAlloc as IAlloc
import qualified Ganeti.HTools.Backend.MonD as MonD
import Ganeti.HTools.CLI
import Ganeti.HTools.Loader (mergeData, checkData, ClusterData(..)
                            , commonSuffix, clearDynU)
import Ganeti.HTools.Types
import Ganeti.Utils (sepSplit, tryRead, exitIfBad, exitWhen)

-- | Error beautifier.
wrapIO :: IO (Result a) -> IO (Result a)
wrapIO = handle (\e -> return . Bad . show $ (e::IOException))

-- | Parses a user-supplied utilisation string.
parseUtilisation :: String -> Result (String, DynUtil)
parseUtilisation line =
  case sepSplit ' ' line of
    [name, cpu, mem, dsk, net] ->
      do
        rcpu <- tryRead name cpu
        rmem <- tryRead name mem
        rdsk <- tryRead name dsk
        rnet <- tryRead name net
        let du = DynUtil { cpuWeight = rcpu, memWeight = rmem
                         , dskWeight = rdsk, netWeight = rnet }
        return (name, du)
    _ -> Bad $ "Cannot parse line " ++ line

-- | External tool data loader from a variety of sources.
loadExternalData :: Options
                 -> IO ClusterData
loadExternalData opts = do
  let mhost = optMaster opts
      lsock = optLuxi opts
      tfile = optDataFile opts
      simdata = optNodeSim opts
      iallocsrc = optIAllocSrc opts
      setRapi = mhost /= ""
      setLuxi = isJust lsock
      setSim = (not . null) simdata
      setFile = isJust tfile
      setIAllocSrc = isJust iallocsrc
      allSet = filter id [setRapi, setLuxi, setFile]
      exTags = case optExTags opts of
                 Nothing -> []
                 Just etl -> map (++ ":") etl
      selInsts = optSelInst opts
      exInsts = optExInst opts

  exitWhen (length allSet > 1) "Only one of the rapi, luxi, and data\
                               \ files options should be given."

  util_contents <- maybe (return "") readFile (optDynuFile opts)
  util_data <- exitIfBad "can't parse utilisation data" .
               mapM parseUtilisation $ lines util_contents
  input_data <-
    case () of
      _ | setRapi -> wrapIO $ Rapi.loadData mhost
        | setLuxi -> wrapIO . Luxi.loadData $ fromJust lsock
        | setSim -> Simu.loadData simdata
        | setFile -> wrapIO . Text.loadData $ fromJust tfile
        | setIAllocSrc -> wrapIO . IAlloc.loadData $ fromJust iallocsrc
        | otherwise -> return $ Bad "No backend selected! Exiting."
  now <- getClockTime

  let ignoreDynU = optIgnoreDynu opts
      eff_u = if ignoreDynU then [] else util_data
      ldresult = input_data >>= (if ignoreDynU then clearDynU else return)
                            >>= mergeData eff_u exTags selInsts exInsts now
  cdata <- exitIfBad "failed to load data, aborting" ldresult
  (cdata', ok) <- runWriterT $ if optMonD opts
                                 then MonD.queryAllMonDDCs cdata opts
                                 else return cdata
  exitWhen (optMonDExitMissing opts && not (getAll ok))
      "Not all required data available"
  let (fix_msgs, nl) = checkData (cdNodes cdata') (cdInstances cdata')

  unless (optVerbose opts == 0) $ maybeShowWarnings fix_msgs

  return cdata' {cdNodes = nl}

-- | Function to save the cluster data to a file.
maybeSaveData :: Maybe FilePath -- ^ The file prefix to save to
              -> String         -- ^ The suffix (extension) to add
              -> String         -- ^ Informational message
              -> ClusterData    -- ^ The cluster data
              -> IO ()
maybeSaveData Nothing _ _ _ = return ()
maybeSaveData (Just path) ext msg cdata = do
  let adata = Text.serializeCluster cdata
      out_path = path <.> ext
  writeFile out_path adata
  hPrintf stderr "The cluster state %s has been written to file '%s'\n"
          msg out_path

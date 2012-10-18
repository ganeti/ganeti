{-| External data loader.

This module holds the external data loading, and thus is the only one
depending (via the specialized Text\/Rapi\/Luxi modules) on the actual
libraries implementing the low-level protocols.

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

module Ganeti.HTools.ExtLoader
  ( loadExternalData
  , commonSuffix
  , maybeSaveData
  ) where

import Control.Monad
import Control.Exception
import Data.Maybe (isJust, fromJust)
import Prelude hiding (catch)
import System.FilePath
import System.IO
import Text.Printf (hPrintf)

import qualified Ganeti.HTools.Luxi as Luxi
import qualified Ganeti.HTools.Rapi as Rapi
import qualified Ganeti.HTools.Simu as Simu
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.IAlloc as IAlloc
import Ganeti.HTools.Loader (mergeData, checkData, ClusterData(..)
                            , commonSuffix)

import Ganeti.BasicTypes
import Ganeti.HTools.Types
import Ganeti.HTools.CLI
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

  let ldresult = input_data >>= mergeData util_data exTags selInsts exInsts
  cdata <- exitIfBad "failed to load data, aborting" ldresult
  let (fix_msgs, nl) = checkData (cdNodes cdata) (cdInstances cdata)

  unless (optVerbose opts == 0) $ maybeShowWarnings fix_msgs

  return cdata {cdNodes = nl}

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

{-# LANGUAGE CPP #-}

{-| External data loader

This module holds the external data loading, and thus is the only one
depending (via the specialized Text\/Rapi\/Luxi modules) on the actual
libraries implementing the low-level protocols.

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

module Ganeti.HTools.ExtLoader
    ( loadExternalData
    , Loader.commonSuffix
    ) where

import Data.Maybe (isJust, fromJust)
import Monad
import System.IO
import System
import Text.Printf (printf, hPrintf)

import qualified Ganeti.HTools.Luxi as Luxi
#ifndef NO_CURL
import qualified Ganeti.HTools.Rapi as Rapi
#endif
import qualified Ganeti.HTools.Simu as Simu
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group

import Ganeti.HTools.Types
import Ganeti.HTools.CLI
import Ganeti.HTools.Utils (sepSplit, tryRead)

-- | Error beautifier
wrapIO :: IO (Result a) -> IO (Result a)
wrapIO = flip catch (return . Bad . show)

parseUtilisation :: String -> Result (String, DynUtil)
parseUtilisation line =
    let columns = sepSplit ' ' line
    in case columns of
         [name, cpu, mem, dsk, net] -> do
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
                 -> IO (Group.List, Node.List, Instance.List, [String])
loadExternalData opts = do
  let mhost = optMaster opts
      lsock = optLuxi opts
      tfile = optDataFile opts
      simdata = optNodeSim opts
      setRapi = mhost /= ""
      setLuxi = isJust lsock
      setSim = (not . null) simdata
      setFile = isJust tfile
      allSet = filter id [setRapi, setLuxi, setFile]
      exTags = case optExTags opts of
                 Nothing -> []
                 Just etl -> map (++ ":") etl
      exInsts = optExInst opts

  when (length allSet > 1) $
       do
         hPutStrLn stderr ("Error: Only one of the rapi, luxi, and data" ++
                           " files options should be given.")
         exitWith $ ExitFailure 1

  util_contents <- (case optDynuFile opts of
                      Just path -> readFile path
                      Nothing -> return "")
  let util_data = mapM parseUtilisation $ lines util_contents
  util_data' <- (case util_data of
                   Ok x -> return x
                   Bad y -> do
                     hPutStrLn stderr ("Error: can't parse utilisation" ++
                                       " data: " ++ show y)
                     exitWith $ ExitFailure 1)
  input_data <-
      case () of
        _ | setRapi ->
#ifdef NO_CURL
              return $ Bad "RAPI/curl backend disabled at compile time"
#else
              wrapIO $ Rapi.loadData mhost
#endif
          | setLuxi -> wrapIO $ Luxi.loadData $ fromJust lsock
          | setSim -> Simu.loadData simdata
          | setFile -> wrapIO $ Text.loadData $ fromJust tfile
          | otherwise -> return $ Bad "No backend selected! Exiting."

  let ldresult = input_data >>= Loader.mergeData util_data' exTags exInsts
  (gl, loaded_nl, il, tags) <-
      (case ldresult of
         Ok x -> return x
         Bad s -> do
           hPrintf stderr "Error: failed to load data. Details:\n%s\n" s
               :: IO ()
           exitWith $ ExitFailure 1
      )
  let (fix_msgs, fixed_nl) = Loader.checkData loaded_nl il

  unless (null fix_msgs || optVerbose opts == 0) $ do
         hPutStrLn stderr "Warning: cluster has inconsistent data:"
         hPutStrLn stderr . unlines . map (printf "  - %s") $ fix_msgs

  return (gl, fixed_nl, il, tags)

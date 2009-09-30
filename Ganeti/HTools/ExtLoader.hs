{-# LANGUAGE CPP #-}

{-| External data loader

This module holds the external data loading, and thus is the only one
depending (via the specialized Text\/Rapi\/Luxi modules) on the actual
libraries implementing the low-level protocols.

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

module Ganeti.HTools.ExtLoader
    ( loadExternalData
    ) where

import Data.Maybe (isJust, fromJust)
import Monad
import System.Posix.Env
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

import Ganeti.HTools.Types
import Ganeti.HTools.CLI

-- | Parse the environment and return the node\/instance names.
--
-- This also hardcodes here the default node\/instance file names.
parseEnv :: () -> IO (String, String)
parseEnv () = do
  a <- getEnvDefault "HTOOLS_NODES" "nodes"
  b <- getEnvDefault "HTOOLS_INSTANCES" "instances"
  return (a, b)

-- | Error beautifier
wrapIO :: IO (Result a) -> IO (Result a)
wrapIO = flip catch (return . Bad . show)

-- | External tool data loader from a variety of sources.
loadExternalData :: Options
                 -> IO (Node.List, Instance.List, String)
loadExternalData opts = do
  (env_node, env_inst) <- parseEnv ()
  let nodef = if optNodeSet opts then optNodeFile opts
              else env_node
      instf = if optInstSet opts then optInstFile opts
              else env_inst
      mhost = optMaster opts
      lsock = optLuxi opts
      simdata = optNodeSim opts
      setRapi = mhost /= ""
      setLuxi = isJust lsock
      setSim = isJust simdata
      setFiles = optNodeSet opts || optInstSet opts
      allSet = filter id [setRapi, setLuxi, setFiles]
  when (length allSet > 1) $
       do
         hPutStrLn stderr ("Error: Only one of the rapi, luxi, and data" ++
                           " files options should be given.")
         exitWith $ ExitFailure 1

  input_data <-
      case () of
        _ | setRapi ->
#ifdef NO_CURL
              return $ Bad "RAPI/curl backend disabled at compile time"
#else
              wrapIO $ Rapi.loadData mhost
#endif
          | setLuxi -> wrapIO $ Luxi.loadData $ fromJust lsock
          | setSim -> Simu.loadData $ fromJust simdata
          | otherwise -> wrapIO $ Text.loadData nodef instf

  let ldresult = input_data >>= Loader.mergeData
  (loaded_nl, il, csf) <-
      (case ldresult of
         Ok x -> return x
         Bad s -> do
           hPrintf stderr "Error: failed to load data. Details:\n%s\n" s
           exitWith $ ExitFailure 1
      )
  let (fix_msgs, fixed_nl) = Loader.checkData loaded_nl il

  unless (null fix_msgs || optVerbose opts == 0) $ do
         hPutStrLn stderr "Warning: cluster has inconsistent data:"
         hPutStrLn stderr . unlines . map (printf "  - %s") $ fix_msgs

  return (fixed_nl, il, csf)

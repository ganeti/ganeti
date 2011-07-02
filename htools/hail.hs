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

module Main (main) where

import Control.Monad
import Data.List
import Data.Maybe (isJust, fromJust)
import System.IO
import qualified System

import qualified Ganeti.HTools.Cluster as Cluster

import Ganeti.HTools.CLI
import Ganeti.HTools.IAlloc
import Ganeti.HTools.Types
import Ganeti.HTools.Loader (Request(..), ClusterData(..))

-- | Options list and functions
options :: [OptType]
options =
    [ oPrintNodes
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

  request <- readRequest opts args

  let Request rq cdata = request

  when (verbose > 1) $
       hPutStrLn stderr $ "Received request: " ++ show rq

  when (verbose > 2) $
       hPutStrLn stderr $ "Received cluster data: " ++ show cdata

  when (isJust shownodes) $ do
         hPutStrLn stderr "Initial cluster status:"
         hPutStrLn stderr $ Cluster.printNodes (cdNodes cdata)
                       (fromJust shownodes)

  let sols = processRequest request >>= processResults rq
  let (ok, info, rn) =
          case sols of
            Ok as -> (True, "Request successful: " ++
                            intercalate ", " (Cluster.asLog as),
                      Cluster.asSolutions as)
            Bad s -> (False, "Request failed: " ++ s, [])
      resp = formatResponse ok info rq rn
  putStrLn resp

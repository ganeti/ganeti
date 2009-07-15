{-| Solver for N+1 cluster errors

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

import Data.List
import Data.Function
import Monad
import System
import System.IO
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node

import Ganeti.HTools.CLI
import Ganeti.HTools.IAlloc
import Ganeti.HTools.Types
import Ganeti.HTools.Loader (RqType(..), Request(..))

-- | Options list and functions
options :: [OptType]
options = [oShowVer, oShowHelp]

processResults :: (Monad m) => Cluster.AllocSolution -> m (String, [Node.Node])
processResults (fstats, succ, sols) =
    case sols of
      Nothing -> fail "No valid allocation solutions"
      Just (best, (_, _, w)) ->
          let tfails = length fstats
              info = printf "successes %d, failures %d,\
                            \ best score: %.8f for node(s) %s"
                            succ tfails
                            best (intercalate "/" . map Node.name $ w)::String
          in return (info, w)

-- | Process a request and return new node lists
processRequest :: Request
               -> Result Cluster.AllocSolution
processRequest request =
  let Request rqtype nl il _ = request
  in case rqtype of
       Allocate xi reqn -> Cluster.tryAlloc nl il xi reqn
       Relocate idx reqn exnodes -> Cluster.tryReloc nl il idx reqn exnodes

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (_, args) <- parseOpts cmd_args "hail" options

  when (null args) $ do
         hPutStrLn stderr "Error: this program needs an input file."
         exitWith $ ExitFailure 1

  let input_file = head args
  input_data <- readFile input_file

  request <- case (parseData input_data) of
               Bad err -> do
                 hPutStrLn stderr $ "Error: " ++ err
                 exitWith $ ExitFailure 1
               Ok rq -> return rq

  let Request _ _ _ csf = request
      sols = processRequest request >>= processResults
  let (ok, info, rn) =
          case sols of
            Ok (info, sn) -> (True, "Request successful: " ++ info,
                                  map ((++ csf) . Node.name) sn)
            Bad s -> (False, "Request failed: " ++ s, [])
      resp = formatResponse ok info rn
  putStrLn resp

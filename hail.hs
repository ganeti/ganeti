{-| Solver for N+1 cluster errors

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

module Main (main) where

import Data.List
import Data.Maybe (isJust, fromJust)
import Monad
import System (exitWith, ExitCode(..))
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
options = [oPrintNodes, oShowVer, oShowHelp]

processResults :: (Monad m) =>
                  RqType -> Cluster.AllocSolution
               -> m (String, Cluster.AllocSolution)
processResults _ (Cluster.AllocSolution { Cluster.asSolutions = [] }) =
  fail "No valid allocation solutions"
processResults (Evacuate _) as =
    let fstats = Cluster.asFailures as
        successes = Cluster.asAllocs as
        (_, _, _, best) = head (Cluster.asSolutions as)
        tfails = length fstats
        info = printf "for last allocation, successes %d, failures %d,\
                      \ best score: %.8f" successes tfails best::String
    in return (info, as)

processResults _ as =
    case Cluster.asSolutions as of
      (_, _, w, best):[] ->
          let tfails = length (Cluster.asFailures as)
              info = printf "successes %d, failures %d,\
                            \ best score: %.8f for node(s) %s"
                            (Cluster.asAllocs as) tfails
                            best (intercalate "/" . map Node.name $ w)::String
          in return (info, as)
      _ -> fail "Internal error: multiple allocation solutions"

-- | Process a request and return new node lists
processRequest :: Request
               -> Result Cluster.AllocSolution
processRequest request =
  let Request rqtype nl il _ = request
  in case rqtype of
       Allocate xi reqn -> Cluster.tryAlloc nl il xi reqn
       Relocate idx reqn exnodes -> Cluster.tryReloc nl il idx reqn exnodes
       Evacuate exnodes -> Cluster.tryEvac nl il exnodes

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, args) <- parseOpts cmd_args "hail" options

  when (null args) $ do
         hPutStrLn stderr "Error: this program needs an input file."
         exitWith $ ExitFailure 1

  let input_file = head args
      shownodes = optShowNodes opts
  input_data <- readFile input_file

  request <- case (parseData input_data) of
               Bad err -> do
                 hPutStrLn stderr $ "Error: " ++ err
                 exitWith $ ExitFailure 1
               Ok rq -> return rq

  let Request rq nl _ _ = request

  when (isJust shownodes) $ do
         hPutStrLn stderr "Initial cluster status:"
         hPutStrLn stderr $ Cluster.printNodes nl (fromJust shownodes)

  let sols = processRequest request >>= processResults rq
  let (ok, info, rn) =
          case sols of
            Ok (ginfo, as) -> (True, "Request successful: " ++ ginfo,
                               Cluster.asSolutions as)
            Bad s -> (False, "Request failed: " ++ s, [])
      resp = formatResponse ok info rq rn
  putStrLn resp

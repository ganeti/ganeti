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
import Data.Maybe (isJust, fromJust)
import Monad
import System
import System.IO
import System.Console.GetOpt
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.CLI as CLI
import Ganeti.HTools.IAlloc
import Ganeti.HTools.Types
import Ganeti.HTools.Loader (RqType(..), Request(..))
import Ganeti.HTools.Utils

-- | Command line options structure.
data Options = Options
    { optShowVer   :: Bool           -- ^ Just show the program version
    , optShowHelp  :: Bool           -- ^ Just show the help
    } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowVer   = False
 , optShowHelp  = False
 }

instance CLI.CLIOptions Options where
    showVersion = optShowVer
    showHelp    = optShowHelp

-- | Options list and functions
options :: [OptDescr (Options -> Options)]
options =
    [ Option ['V']     ["version"]
      (NoArg (\ opts -> opts { optShowVer = True}))
      "show the version of the program"
    , Option ['h']     ["help"]
      (NoArg (\ opts -> opts { optShowHelp = True}))
      "show help"
    ]


filterFails :: (Monad m) => [(Maybe Node.List, Instance.Instance, [Node.Node])]
            -> m [(Node.List, [Node.Node])]
filterFails sols =
    if null sols then fail "No nodes onto which to allocate at all"
    else let sols' = filter (isJust . fst3) sols
         in if null sols' then
                fail "No valid allocation solutions"
            else
                return $ map (\(x, _, y) -> (fromJust x, y)) sols'

processResults :: (Monad m) => [(Node.List, [Node.Node])]
               -> m (String, [Node.Node])
processResults sols =
    let sols' = map (\(nl', ns) -> (Cluster.compCV  nl', ns)) sols
        sols'' = sortBy (compare `on` fst) sols'
        (best, w) = head sols''
        (worst, l) = last sols''
        info = (printf "Valid results: %d, best score: %.8f for node(s) %s, \
                       \worst score: %.8f for node(s) %s" (length sols'')
                       best (intercalate "/" . map Node.name $ w)
                       worst (intercalate "/" . map Node.name $ l))::String
    in return (info, w)

-- | Process a request and return new node lists
processRequest ::
                  Request
               -> Result [(Maybe Node.List, Instance.Instance, [Node.Node])]
processRequest request =
  let Request rqtype nl il _ = request
  in case rqtype of
       Allocate xi reqn -> Cluster.tryAlloc nl il xi reqn
       Relocate idx reqn exnodes -> Cluster.tryReloc nl il idx reqn exnodes

-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (_, args) <- CLI.parseOpts cmd_args "hail" options defaultOptions

  when (null args) $ do
         hPutStrLn stderr "Error: this program needs an input file."
         exitWith $ ExitFailure 1

  let input_file = head args
  input_data <- readFile input_file

  request <- case (parseData input_data) of
               Bad err -> do
                 putStrLn $ "Error: " ++ err
                 exitWith $ ExitFailure 1
               Ok rq -> return rq

  let Request _ _ _ csf = request
      sols = processRequest request >>= filterFails >>= processResults
  let (ok, info, rn) = case sols of
               Ok (info, sn) -> (True, "Request successful: " ++ info,
                                     map ((++ csf) . Node.name) sn)
               Bad s -> (False, "Request failed: " ++ s, [])
      resp = formatResponse ok info rn
  putStrLn resp

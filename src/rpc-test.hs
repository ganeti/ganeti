{-| RPC test program.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

import System.Environment

import Ganeti.Errors
import Ganeti.Config
import Ganeti.Objects
import qualified Ganeti.Path as P
import Ganeti.Rpc
import Ganeti.Utils

-- | Show usage info and exit.
usage :: IO ()
usage = do
  prog <- getProgName
  exitErr $ "Usage: " ++ prog ++ " delay node..."

main :: IO ()
main = do
  args <- getArgs
  (delay, nodes) <- case args of
                      [] -> usage >> return ("", []) -- workaround types...
                      _:[] -> usage >> return ("", [])
                      x:xs -> return (x, xs)
  cfg_file <- P.clusterConfFile
  cfg <- loadConfig  cfg_file>>= exitIfBad "Can't load configuration"
  let call = RpcCallTestDelay (read delay)
  nodes' <- exitIfBad "Can't find node" . errToResult $
            mapM (getNode cfg) nodes
  results <- executeRpcCall nodes' call
  putStr $ printTable "" ["Node", "Result"]
           (map (\(n, r) -> [nodeName n, either explainRpcError show r])
                results)
           [False, False]

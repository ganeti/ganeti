{-# LANGUAGE BangPatterns #-}

{-| RPC test program.

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.

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

import Control.Concurrent
import Control.Monad
import System.Console.GetOpt
import System.Environment
import System.IO
import Text.JSON (decode)
import Text.Printf

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.Config
import Ganeti.Errors
import Ganeti.JSON
import Ganeti.Objects
import qualified Ganeti.Path as P
import Ganeti.Rpc
import Ganeti.Utils


-- | Command line options structure.
data Options = Options
  { optRpc      :: String   -- ^ RPC to execute
  , optDataFile :: FilePath -- ^ Path to the RPC serialised form
  , optVerbose  :: Bool     -- ^ Verbosity level
  , optStats    :: Bool     -- ^ Whether to show timing stats
  , optCount    :: Int      -- ^ Count of (multi) RPCs to do
  , optBatch    :: Int      -- ^ How many (multi) RPCs to run in parallel
  , optShowHelp :: Bool     -- ^ Just show the help
  , optShowComp :: Bool     -- ^ Just show the completion info
  , optShowVer  :: Bool     -- ^ Just show the program version
  } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions = Options
  { optRpc      = "version"
  , optDataFile = "rpc.json"
  , optVerbose  = False
  , optStats    = False
  , optCount    = 1
  , optBatch    = 1
  , optShowHelp = False
  , optShowComp = False
  , optShowVer  = False
  }

instance StandardOptions Options where
  helpRequested = optShowHelp
  verRequested  = optShowVer
  compRequested = optShowComp
  requestHelp o = o { optShowHelp = True }
  requestVer  o = o { optShowVer  = True }
  requestComp o = o { optShowComp = True }

-- | The rpcs we support. Sadly this duplicates the RPC list.
data KnownRpc = KRInstanceInfo      RpcCallInstanceInfo
              | KRAllInstancesInfo  RpcCallAllInstancesInfo
              | KRInstanceList      RpcCallInstanceList
              | KRNodeInfo          RpcCallNodeInfo
              | KRVersion           RpcCallVersion
              | KRStorageList       RpcCallStorageList
              | KRTestDelay         RpcCallTestDelay
              | KRExportList        RpcCallExportList
                deriving (Show)

-- | The command line options.
options :: [GenericOptType Options]
options =
  [ (Option "r" ["rpc"]
     (ReqArg (\ r o -> Ok o { optRpc = r }) "RPC")
     "the rpc to use [version]",
     OptComplChoices [])
  , (Option "f" ["data-file"]
     (ReqArg (\ f o -> Ok o { optDataFile = f }) "FILE")
     "the rpc serialised form [\"rpc.json\"]",
     OptComplFile)
  , (Option "v" ["verbose"]
     (NoArg (\ opts -> Ok opts { optVerbose = True}))
     "show more information when executing RPCs",
     OptComplNone)
  , (Option "t" ["stats"]
     (NoArg (\ opts -> Ok opts { optStats = True}))
     "show timing information summary",
     OptComplNone)
  , (Option "c" ["count"]
     (reqWithConversion (tryRead "reading count")
      (\count opts -> Ok opts { optCount = count }) "NUMBER")
     "Count of (multi) RPCs to execute [1]",
     OptComplInteger)
  , (Option "b" ["batch"]
     (reqWithConversion (tryRead "reading batch size")
      (\batch opts -> Ok opts { optBatch = batch }) "NUMBER")
     "Parallelisation factor for RPCs [1]",
     OptComplInteger)
  , oShowHelp
  , oShowComp
  , oShowVer
  ]

-- | Arguments we expect
arguments :: [ArgCompletion]
arguments = [ArgCompletion OptComplOneNode 1 Nothing]

-- | Log a message.
logMsg :: MVar () -> String -> IO ()
logMsg outmvar text =
  withMVar outmvar $ \_ -> do
    let p = if null text || last text /= '\n'
              then putStrLn
              else putStr
    p text
    hFlush stdout

-- | Parses a RPC.
parseRpc :: String -> String -> Result KnownRpc
parseRpc "instance_info"      f =
  fromJResult "parsing rpc" (decode f) >>= Ok . KRInstanceInfo
parseRpc "all_instances_info" f =
  fromJResult "parsing rpc" (decode f) >>= Ok . KRAllInstancesInfo
parseRpc "instance_list"      f =
  fromJResult "parsing rpc" (decode f) >>= Ok . KRInstanceList
parseRpc "node_info"          f =
  fromJResult "parsing rpc" (decode f) >>= Ok . KRNodeInfo
parseRpc "version"            f =
  fromJResult "parsing rpc" (decode f) >>= Ok . KRVersion
parseRpc "storage_list"       f =
  fromJResult "parsing rpc" (decode f) >>= Ok . KRStorageList
parseRpc "test_delay"         f =
  fromJResult "parsing rpc" (decode f) >>= Ok . KRTestDelay
parseRpc "export_list"        f =
  fromJResult "parsing rpc" (decode f) >>= Ok . KRExportList
parseRpc s _                  = Bad $ "Unknown rpc '" ++ s ++ "'"

-- | Executes a RPC. These duplicate definitions are needed due to the
-- polymorphism of 'executeRpcCall', and the binding of the result
-- based on the input rpc call.
execRpc :: [Node] -> KnownRpc -> IO [[String]]
execRpc n (KRInstanceInfo      v) = formatRpcRes `fmap` executeRpcCall n v
execRpc n (KRAllInstancesInfo  v) = formatRpcRes `fmap` executeRpcCall n v
execRpc n (KRInstanceList      v) = formatRpcRes `fmap` executeRpcCall n v
execRpc n (KRNodeInfo          v) = formatRpcRes `fmap` executeRpcCall n v
execRpc n (KRVersion           v) = formatRpcRes `fmap` executeRpcCall n v
execRpc n (KRStorageList       v) = formatRpcRes `fmap` executeRpcCall n v
execRpc n (KRTestDelay         v) = formatRpcRes `fmap` executeRpcCall n v
execRpc n (KRExportList        v) = formatRpcRes `fmap` executeRpcCall n v

-- | Helper to format the RPC result such that it can be printed by
-- 'printTable'.
formatRpcRes :: (Show b) => [(Node, ERpcError b)] -> [[String]]
formatRpcRes = map (\(n, r) -> [nodeName n, either explainRpcError show r])

-- | Main function.
main :: IO ()
main = do
  cmd_args <- getArgs
  (opts, args) <-
    parseOpts defaultOptions cmd_args "rpc-test" options arguments
  rpc <- parseRpc (optRpc opts) `liftM` readFile (optDataFile opts) >>=
         exitIfBad "parsing RPC"
  cfg_file <- P.clusterConfFile
  cfg <- loadConfig  cfg_file>>= exitIfBad "Can't load configuration"
  nodes <- exitIfBad "Can't find node" . errToResult $
            mapM (getNode cfg) args
  token <- newEmptyMVar -- semaphore for batch calls
  outmvar <- newMVar () -- token for stdout non-interleaving
  let logger = if optVerbose opts
                 then logMsg outmvar
                 else const $ return ()
  let batch = [1..optBatch opts]
      count = optCount opts
      rpcs = count * length nodes
  logger $ printf "Will execute %s multi-ops and %s RPCs"
           (show count) (show rpcs)
  tstart <- getCurrentTimeUSec
  _ <- forkIO $ mapM_ (\_ -> putMVar token ()) batch
  mapM_ (\idx -> do
           let str_idx = show idx
           logger $ "Acquiring token for run " ++ str_idx
           _ <- takeMVar token
           forkIO $ do
             start <- getCurrentTimeUSec
             logger $ "Start run " ++ str_idx
             !results <- execRpc nodes rpc
             stop <- getCurrentTimeUSec
             let delta = (fromIntegral (stop - start)::Double) / 1000
             putMVar token ()
             let stats = if optVerbose opts
                           then printf "Done run %d in %7.3fmsec\n" idx delta
                           else ""
                 table = printTable "" ["Node", "Result"]
                           results [False, False]
             logMsg outmvar $ stats ++ table
        ) [1..count]
  mapM_ (\_ -> takeMVar token) batch
  _ <- takeMVar outmvar
  when (optStats opts) $ do
    tstop <- getCurrentTimeUSec
    let delta = (fromIntegral (tstop - tstart) / 1000000)::Double
    printf "Total runtime:     %9.3fs\n" delta :: IO ()
    printf "Total mult-ops:    %9d\n" count :: IO ()
    printf "Total single RPCs: %9d\n" rpcs  :: IO ()
    printf "Multi-ops/sec:     %9.3f\n" (fromIntegral count / delta) :: IO ()
    printf "RPCs/sec:          %9.3f\n" (fromIntegral rpcs / delta) :: IO ()

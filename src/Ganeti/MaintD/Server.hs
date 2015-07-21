{-# LANGUAGE OverloadedStrings #-}

{-| Implementation of the Ganeti maintenenace server.

-}

{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.MaintD.Server
  ( options
  , main
  , checkMain
  , prepMain
  ) where

import Control.Applicative ((<|>))
import Control.Concurrent (forkIO)
import Control.Exception.Lifted (bracket)
import Control.Monad (forever, void, unless, when, liftM)
import Control.Monad.IO.Class (liftIO)
import Data.IORef (IORef, newIORef, readIORef)
import qualified Data.Set as Set
import Snap.Core (Snap, method, Method(GET), ifTop, dir, route)
import Snap.Http.Server (httpServe)
import Snap.Http.Server.Config (Config)
import System.IO.Error (tryIOError)
import System.Time (getClockTime)
import qualified Text.JSON as J

import Ganeti.BasicTypes ( GenericResult(..), ResultT, runResultT, mkResultT
                         , withErrorT, isBad)
import qualified Ganeti.Constants as C
import Ganeti.Daemon ( OptType, CheckFn, PrepFn, MainFn, oDebug
                     , oNoVoting, oYesDoIt, oPort, oBindAddress, oNoDaemonize)
import Ganeti.Daemon.Utils (handleMasterVerificationOptions)
import qualified Ganeti.HTools.Backend.Luxi as Luxi
import qualified Ganeti.HTools.Container as Container
import Ganeti.HTools.Loader (ClusterData(..), mergeData, checkData)
import Ganeti.Jobs (waitForJobs)
import Ganeti.Logging.Lifted
import qualified Ganeti.Luxi as L
import Ganeti.MaintD.Autorepairs (harepTasks)
import Ganeti.MaintD.MemoryState
import qualified Ganeti.Path as Path
import Ganeti.Runtime (GanetiDaemon(GanetiMaintd))
import Ganeti.Types (JobId(..))
import Ganeti.Utils (threadDelaySeconds)
import Ganeti.Utils.Http (httpConfFromOpts, plainJSON, error404)
import Ganeti.WConfd.Client (runNewWConfdClient, maintenanceRoundDelay)

-- | Options list and functions.
options :: [OptType]
options =
  [ oNoDaemonize
  , oDebug
  , oPort C.defaultMaintdPort
  , oBindAddress
  , oNoVoting
  , oYesDoIt
  ]

-- | Type alias for checkMain results.
type CheckResult = ()

-- | Type alias for prepMain results
type PrepResult = Config Snap ()

-- | Load cluster data
--
-- At the moment, only the static data is fetched via luxi;
-- once we support load-based balancing in maintd as well,
-- we also need to query the MonDs for the load data.
loadClusterData :: ResultT String IO ClusterData
loadClusterData = do
  now <- liftIO getClockTime
  socket <- liftIO Path.defaultQuerySocket
  either_inp <-  liftIO . tryIOError $ Luxi.loadData socket
  input_data <- mkResultT $ case either_inp of
                  Left e -> do
                    let msg = show e
                    logNotice $ "Couldn't read data from luxid: " ++ msg
                    return $ Bad msg
                  Right r -> return r
  cdata <- mkResultT . return $ mergeData [] [] [] [] now input_data
  let (msgs, nl) = checkData (cdNodes cdata) (cdInstances cdata)
  unless (null msgs) . logDebug $ "Cluster data inconsistencies: " ++ show msgs
  return $ cdata { cdNodes = nl }

-- | Perform one round of maintenance
maintenance :: IORef MemoryState -> ResultT String IO ()
maintenance memstate = do
  delay <- withErrorT show $ runNewWConfdClient maintenanceRoundDelay
  liftIO $ threadDelaySeconds delay
  oldjobs <- getJobs memstate
  logDebug $ "Jobs submitted in the last round: "
             ++ show (map fromJobId oldjobs)
  luxiSocket <- liftIO Path.defaultQuerySocket
  bracket (mkResultT . liftM (either (Bad . show) Ok)
            . tryIOError $ L.getLuxiClient luxiSocket)
          (liftIO . L.closeClient)
          $ void . mkResultT . waitForJobs oldjobs
  unless (null oldjobs)
    . liftIO $ clearJobs memstate
  logDebug "New round of maintenance started"
  cData <- loadClusterData
  let il = cdInstances cData
      nl = cdNodes cData
      nidxs = Set.fromList $ Container.keys nl
  (nidxs', jobs) <- harepTasks (nl, il) nidxs
  unless (null oldjobs)
   . liftIO $ appendJobs memstate jobs
  logDebug $ "Unaffected nodes " ++ show (Set.toList nidxs')
             ++ ", jobs submitted " ++ show (map fromJobId jobs)

-- | Expose a part of the memory state
exposeState :: J.JSON a => (MemoryState -> a) -> IORef MemoryState -> Snap ()
exposeState selector ref = do
  state <- liftIO $ readIORef ref
  plainJSON $ selector state

-- | The information to serve via HTTP
httpInterface :: IORef MemoryState -> Snap ()
httpInterface memstate =
  ifTop (method GET $ plainJSON [1 :: Int])
  <|> dir "1" (ifTop (plainJSON J.JSNull)
               <|> route [ ("jobs", exposeState msJobs memstate)
                         ])
  <|> error404

-- | Check function for luxid.
checkMain :: CheckFn CheckResult
checkMain = handleMasterVerificationOptions

-- | Prepare function for luxid.
prepMain :: PrepFn CheckResult PrepResult
prepMain opts _ = httpConfFromOpts GanetiMaintd opts

-- | Main function.
main :: MainFn CheckResult PrepResult
main _ _ httpConf = do
  memstate <- newIORef emptyMemoryState
  void . forkIO . forever $ do
    res <- runResultT $ maintenance memstate
    (if isBad res then logInfo else logDebug)
       $ "Maintenance round result is " ++ show res
    when (isBad res) $ do
      logDebug "Backing off after a round with internal errors"
      threadDelaySeconds C.maintdDefaultRoundDelay
  httpServe httpConf $ httpInterface memstate

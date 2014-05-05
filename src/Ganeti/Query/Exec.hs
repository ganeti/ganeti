{-| Executing jobs as processes

The protocol works as follows (MP = master process, FP = forked process):

* MP sets its own livelock as the livelock of the job to be executed.

* FP creates its own lock file and sends its name to the MP.

* MP updates the lock file name in the job file and confirms the FP it can
  start.

* FP calls 'executeFile' and replaces the process with a Python process

* FP sends an empty message to the MP to signal it's ready to receive
  the necessary information.

* MP sends the FP its job ID.

* FP sends an empty message to the MP again.

* MP sends the FP its live lock file name (since it was known only to the
  Haskell process, but not the Python process).

* Both MP and FP close the communication channel.

 -}

{-

Copyright (C) 2014 Google Inc.

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

module Ganeti.Query.Exec
  ( isForkSupported
  , forkJobProcess
  ) where

import Control.Concurrent
import Control.Exception.Lifted (onException)
import Control.Monad
import Control.Monad.Error
import Control.Monad.Trans.Maybe ()
import Data.Functor
import qualified Data.Map as M
import Data.Maybe (listToMaybe, mapMaybe)
import System.Directory (getDirectoryContents)
import System.Environment
import System.IO.Error (tryIOError)
import System.Posix.Process
import System.Posix.IO
import System.Posix.Signals (sigTERM, signalProcess)
import System.Posix.Types (Fd, ProcessID)
import System.Time
import Text.Printf

import qualified AutoConf as AC
import Ganeti.BasicTypes
import Ganeti.Logging
import qualified Ganeti.Path as P
import Ganeti.Types
import Ganeti.UDSServer
import Ganeti.Utils
import Ganeti.Utils.MonadPlus

isForkSupported :: IO Bool
isForkSupported = return $ not rtsSupportsBoundThreads

connectConfig :: ConnectConfig
connectConfig = ConnectConfig { recvTmo    = 30
                              , sendTmo    = 30
                              }

-- Returns the list of all open file descriptors of the current process.
listOpenFds :: (Error e) => ResultT e IO [Fd]
listOpenFds = liftM filterReadable
                $ liftIO (getDirectoryContents "/proc/self/fd") `orElse`
                  liftIO (getDirectoryContents "/dev/fd") `orElse`
                  ([] <$ logInfo "Listing open file descriptors isn't\
                                 \ supported by the system,\
                                 \ not cleaning them up!")
                  -- FIXME: If we can't get the list of file descriptors,
                  -- try to determine the maximum value and just return
                  -- the full range.
                  -- See http://stackoverflow.com/a/918469/1333025
  where
    filterReadable :: (Read a) => [String] -> [a]
    filterReadable = mapMaybe (fmap fst . listToMaybe . reads)

-- Code that is executed in a @fork@-ed process and that the replaces iteself
-- with the actual job process
runJobProcess :: JobId -> Client -> IO ()
runJobProcess jid s = withErrorLogAt CRITICAL (show jid) $
  do
    logInfo $ "Forking a new process for job " ++ show (fromJobId jid)

    -- Create a livelock file for the job
    (TOD ts _) <- getClockTime
    lockfile <- P.livelockFile $ printf "job_%06d_%d" (fromJobId jid) ts

    -- Lock the livelock file
    logDebug $ "Locking livelock file " ++ show lockfile
    fd <- lockFile lockfile >>= annotateResult "Can't lock the livelock file"
    logDebug "Sending the lockfile name to the master process"
    sendMsg s lockfile

    logDebug "Waiting for the master process to confirm the lock"
    _ <- recvMsg s

    -- close the client
    logDebug "Closing the client"
    (clFdR, clFdW) <- clientToFd s
    -- .. and use its file descriptors as stdin/out for the job process;
    -- this way the job process can communicate with the master process
    -- using stdin/out.
    logDebug "Reconnecting the file descriptors to stdin/out"
    _ <- dupTo clFdR stdInput
    _ <- dupTo clFdW stdOutput
    logDebug "Closing the old file descriptors"
    closeFd clFdR
    closeFd clFdW

    fds <- (filter (> 2) . filter (/= fd)) <$> toErrorBase listOpenFds
    logDebug $ "Closing every superfluous file descriptor: " ++ show fds
    mapM_ (tryIOError . closeFd) fds

    -- the master process will send the job id and the livelock file name
    -- using the same protocol to the job process
    -- we pass the job id as the first argument to the process;
    -- while the process never uses it, it's very convenient when listing
    -- job processes
    use_debug <- isDebugMode
    env <- (M.insert "GNT_DEBUG" (if use_debug then "1" else "0")
            . M.insert "PYTHONPATH" AC.versionedsharedir
            . M.fromList)
           `liftM` getEnvironment
    execPy <- P.jqueueExecutorPy
    logDebug $ "Executing " ++ AC.pythonPath ++ " " ++ execPy
               ++ " with PYTHONPATH=" ++ AC.versionedsharedir
    () <- executeFile AC.pythonPath True [execPy, show (fromJobId jid)]
                      (Just $ M.toList env)

    failError $ "Failed to execute " ++ AC.pythonPath ++ " " ++ execPy


-- | Forks a child POSIX process, creating a bi-directional communication
-- channel between the master and the child processes.
-- Supplies the child action with its part of the pipe and returns
-- the master part of the pipe as its result.
forkWithPipe :: ConnectConfig -> (Client -> IO ()) -> IO (ProcessID, Client)
forkWithPipe conf childAction = do
  (master, child) <- pipeClient conf
  pid <- forkProcess (closeClient master >> childAction child)
  closeClient child
  return (pid, master)

-- | Forks the job process and starts processing of the given job.
-- Returns the livelock of the job and its process ID.
forkJobProcess :: (Error e, Show e)
               => JobId -- ^ a job to process
               -> FilePath  -- ^ the daemons own livelock file
               -> (FilePath -> ResultT e IO ())
                  -- ^ a callback function to update the livelock file
                  -- and process id in the job file
               -> ResultT e IO (FilePath, ProcessID)
forkJobProcess jid luxiLivelock update = do
  logDebug $ "Setting the lockfile temporarily to " ++ luxiLivelock
  update luxiLivelock

  -- Due to some bug in GHC forking process, we want to retry,
  -- if the forked process fails to start to communicate.
  -- If it fails later on, the failure is handled by 'ResultT'
  -- and no retry is performed.
  resultOpt <- retryMaybeN 3 $ \_ -> do
    (pid, master) <- liftIO $ forkWithPipe connectConfig (runJobProcess jid)

    let onError = do
          logDebug "Closing the pipe to the client"
          withErrorLogAt WARNING "Closing the communication pipe failed"
              (liftIO (closeClient master)) `mplus` return ()
          logDebug $ "Getting the status of job process "
                     ++ show (fromJobId jid)
          status <- liftIO $ getProcessStatus False True pid
          case status of
            Just s -> logDebug $ "Child process (job " ++ show (fromJobId jid)
                                  ++ ") status: " ++ show s
            Nothing -> do
                      logDebug $ "Child process (job " ++ show (fromJobId jid)
                                  ++ ") running, killing by SIGTERM"
                      liftIO $ signalProcess sigTERM pid

    flip onException onError $ do
      let recv = liftIO $ recvMsg master
          send = liftIO . sendMsg master
      logDebug "Getting the lockfile of the client"
      -- If we fail to receive a message from the client, fail the MaybeT
      -- computation here using `mzero` to retry.
      lockfile <- recv `orElse` mzero

      logDebug $ "Setting the lockfile to the final " ++ lockfile
      lift $ update lockfile
      logDebug "Confirming the client it can start"
      send ""

      -- from now on, we communicate with the job's Python process

      logDebug "Waiting for the job to ask for the job id"
      _ <- recv
      logDebug "Writing job id to the client"
      send . show $ fromJobId jid

      logDebug "Waiting for the job to ask for the lock file name"
      _ <- recv
      logDebug "Writing the lock file name to the client"
      send lockfile

      return (lockfile, pid)

  maybe (failError "The client process timed out repeatedly") return resultOpt

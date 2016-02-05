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

{-# LANGUAGE FlexibleContexts #-}

module Ganeti.Query.Exec
  ( isForkSupported
  , forkJobProcess
  , forkPostHooksProcess
  ) where

import Prelude ()
import Ganeti.Prelude

import Control.Concurrent (rtsSupportsBoundThreads)
import Control.Concurrent.Lifted (threadDelay)
import Control.Exception (finally)
import Control.Monad
import Control.Monad.Error.Class (MonadError(..))
import qualified Data.Map as M
import Data.Maybe (listToMaybe, mapMaybe)
import System.Directory (getDirectoryContents)
import System.Environment
import System.IO.Error (tryIOError, annotateIOError, modifyIOError)
import System.Posix.Process
import System.Posix.IO
import System.Posix.Signals (sigABRT, sigKILL, sigTERM, signalProcess)
import System.Posix.Types (Fd, ProcessID)
import System.Time
import Text.JSON
import Text.Printf

import qualified AutoConf as AC
import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.JQueue.Objects
import Ganeti.JSON (MaybeForJSON(..))
import Ganeti.Logging
import Ganeti.Logging.WriterLog
import Ganeti.OpCodes
import qualified Ganeti.Path as P
import Ganeti.Types
import Ganeti.UDSServer
import Ganeti.Utils
import Ganeti.Utils.Monad
import Ganeti.Utils.Random (delayRandom)

isForkSupported :: IO Bool
isForkSupported = return $ not rtsSupportsBoundThreads

connectConfig :: ConnectConfig
connectConfig = ConnectConfig { recvTmo    = 30
                              , sendTmo    = 30
                              }

-- Returns the list of all open file descriptors of the current process.
listOpenFds :: (FromString e) => ResultT e IO [Fd]
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

-- | Catches a potential `IOError` and sets its description via
-- `annotateIOError`. This makes exceptions more informative when they
-- are thrown from an unnamed `Handle`.
rethrowAnnotateIOError :: String -> IO a -> IO a
rethrowAnnotateIOError desc =
  modifyIOError (\e -> annotateIOError e desc Nothing Nothing)


-- | Code that is executed in a @fork@-ed process. Performs communication with
-- the parent process by calling commFn and then runs pyExecIO python
-- executable.
runProcess :: JobId -- ^ a job to process
           -> Client -- ^ UDS transport
           -> IO FilePath -- ^ path to the python executable
           -> ((String -> IO ()) -> JobId -> Client -> IO Fd)
              -- ^ pre-execution function communicating with the parent. The
              -- function returns the file descriptor which should
              -- remain open
           -> IO ()
runProcess jid s pyExecIO commFn = withErrorLogAt CRITICAL (show jid) $
  do
    -- Close the standard error to prevent anything being written there
    -- (for example by exceptions when closing unneeded FDs).
    closeFd stdError

    -- Currently, we discard any logging messages to prevent problems
    -- with GHC's fork implementation, and they're kept
    -- in the code just to document what is happening.
    -- Later we might direct them to an appropriate file.
    let logLater _ = return ()

    logLater $ "Forking a new process for job " ++ show (fromJobId jid)
    preserve_fd <- commFn logLater jid s
    -- close the client
    logLater "Closing the client"
    (clFdR, clFdW) <- clientToFd s
    -- .. and use its file descriptors as stdin/out for the job process;
    -- this way the job process can communicate with the master process
    -- using stdin/out.
    logLater "Reconnecting the file descriptors to stdin/out"
    _ <- dupTo clFdR stdInput
    _ <- dupTo clFdW stdOutput
    logLater "Closing the old file descriptors"
    closeFd clFdR
    closeFd clFdW

    fds <- (filter (> 2) . filter (/= preserve_fd)) <$> toErrorBase listOpenFds
    logLater $ "Closing every superfluous file descriptor: " ++ show fds
    mapM_ (tryIOError . closeFd) fds

    -- The master process will send the job id and the livelock file name
    -- using the same protocol. We pass the job id as the first argument
    -- to the process. While the process never uses it, it's very convenient
    -- when listing job processes.
    use_debug <- isDebugMode
    env <- (M.insert "GNT_DEBUG" (if use_debug then "1" else "0")
            . M.insert "PYTHONPATH" AC.versionedsharedir
            . M.fromList)
           `liftM` getEnvironment
    execPy <- pyExecIO
    logLater $ "Executing " ++ AC.pythonPath ++ " " ++ execPy
               ++ " with PYTHONPATH=" ++ AC.versionedsharedir
    () <- executeFile AC.pythonPath True [execPy, show (fromJobId jid)]
                      (Just $ M.toList env)

    failError $ "Failed to execute " ++ AC.pythonPath ++ " " ++ execPy

filterSecretParameters :: [QueuedOpCode] -> [MaybeForJSON (JSObject
                                                           (Private JSValue))]
filterSecretParameters =
   map (MaybeForJSON . fmap revealValInJSObject
        . getSecretParams) . mapMaybe (transformOpCode . qoInput)
  where
    transformOpCode :: InputOpCode -> Maybe OpCode
    transformOpCode inputCode =
      case inputCode of
        ValidOpCode moc -> Just (metaOpCode moc)
        _ -> Nothing
    getSecretParams :: OpCode -> Maybe (JSObject (Secret JSValue))
    getSecretParams opcode =
      case opcode of
        (OpInstanceCreate {opOsparamsSecret = x}) -> x
        (OpInstanceReinstall {opOsparamsSecret = x}) -> x
        (OpTestOsParams {opOsparamsSecret = x}) -> x
        _ -> Nothing

-- | Forks a child POSIX process, creating a bi-directional communication
-- channel between the master and the child processes.
-- Supplies the child action with its part of the pipe and returns
-- the master part of the pipe as its result.
forkWithPipe :: ConnectConfig -> (Client -> IO ()) -> IO (ProcessID, Client)
forkWithPipe conf childAction = do
  (master, child) <- pipeClient conf
  pid <- finally
           (forkProcess (closeClient master >> childAction child))
           $ closeClient child
  return (pid, master)

-- | Kill the process with the id provided.
killProcessOnError :: (FromString e, Show e)
                   => ProcessID -- ^ job process pid
                   -> Client -- ^ UDS client connected to the master node
                   -> (String -> ResultT e (WriterLogT IO) ())
                      -- ^ log function
                   -> ResultT e (WriterLogT IO) ()
killProcessOnError pid master logFn = do
  logFn "Closing the pipe to the client"
  withErrorLogAt WARNING "Closing the communication pipe failed"
                 (liftIO (closeClient master)) `orElse` return ()
  killIfAlive [sigTERM, sigABRT, sigKILL]
  where killIfAlive [] = return ()
        killIfAlive (sig : sigs) = do
          logFn "Getting the status of the process"
          status <- tryError . liftIO $ getProcessStatus False True pid
          case status of
            Left e -> logFn $ "Job process already gone: " ++ show e
            Right (Just s) -> logFn $ "Child process status: " ++ show s
            Right Nothing -> do
              logFn $ "Child process running, killing by " ++ show sig
              liftIO $ signalProcess sig pid
              unless (null sigs) $ do
                threadDelay 100000 -- wait for 0.1s and check again
                killIfAlive sigs

-- | Data type used only to define the return type of forkProcessCatchErrors.
data ForkProcessRet = ForkJob (FilePath, ProcessID) |
                      ForkPostHooks ProcessID

-- | Forks current process and runs runFn in the child and commFn in the
-- parent. Due to a bug in GHC forking process, we want to retry if the forked
-- process fails to start. If it fails later on, the failure is handled by
-- 'ResultT' and no retry is performed.
forkProcessCatchErrors :: (Show e, FromString e)
                       => (Client -> IO ())
                       -> (ProcessID -> String -> ResultT e (WriterLogT IO) ())
                       -> (ProcessID -> Client
                           -> ResultT e (WriterLogT IO) ForkProcessRet)
                       -> ResultT e IO ForkProcessRet
forkProcessCatchErrors runFn logFn commFn = do
  -- Due to a bug in GHC forking process, we want to retry
  -- if the forked process fails to start.
  -- If it fails later on, the failure is handled by 'ResultT'
  -- and no retry is performed.
  let execWriterLogInside = ResultT . execWriterLogT . runResultT
  retryErrorN C.luxidRetryForkCount
               $ \tryNo -> execWriterLogInside $ do
    let maxWaitUS = 2^(tryNo - 1) * C.luxidRetryForkStepUS
    when (tryNo >= 2) . liftIO $ delayRandom (0, maxWaitUS)

    (pid, master) <- liftIO $ forkWithPipe connectConfig runFn

    logFn pid "Forked a new process"
    flip catchError (\e -> killProcessOnError pid master (logFn pid)
                           >> throwError e) $ commFn pid master

-- | Forks the job process and starts processing of the given job.
-- Returns the livelock of the job and its process ID.
forkJobProcess :: (FromString e, Show e)
               => QueuedJob -- ^ a job to process
               -> FilePath  -- ^ the daemons own livelock file
               -> (FilePath -> ResultT e IO ())
                  -- ^ a callback function to update the livelock file
                  -- and process id in the job file
               -> ResultT e IO (FilePath, ProcessID)
forkJobProcess job luxiLivelock update = do

  logDebug $ "Setting the lockfile temporarily to " ++ luxiLivelock
             ++ " for job " ++ jidStr
  update luxiLivelock

  ForkJob ret <- forkProcessCatchErrors (childMain . qjId $ job) logDebugJob
                                        parentMain
  return ret
  where
    -- Retrieve secret parameters if present
    secretParams = encodeStrict . filterSecretParameters . qjOps $ job
    jidStr = show . fromJobId . qjId $ job
    jobLogPrefix pid = "[start:job-" ++ jidStr ++ ",pid=" ++ show pid ++ "] "
    logDebugJob pid = logDebug . (jobLogPrefix pid ++)

    -- | Code performing communication with the child process. First, receive
    -- the livelock, then send necessary parameters to the python child.
    parentMain pid master = do
      let annotatedIO msg k = do
            logDebugJob pid msg
            liftIO $ rethrowAnnotateIOError (jobLogPrefix pid ++ msg) k
      let recv msg = annotatedIO msg (recvMsg master)
          send msg x = annotatedIO msg (sendMsg master x)

      lockfile <- recv "Getting the lockfile of the client"

      logDebugJob pid ("Setting the lockfile to the final " ++ lockfile)
      toErrorBase $ update lockfile
      send "Confirming the client it can start" ""

      -- from now on, we communicate with the job's Python process

      _ <- recv "Waiting for the job to ask for the job id"
      send "Writing job id to the client" jidStr
      _ <- recv "Waiting for the job to ask for the lock file name"
      send "Writing the lock file name to the client" lockfile
      _ <- recv "Waiting for the job to ask for secret parameters"
      send "Writing secret parameters to the client" secretParams
      liftIO $ closeClient master
      return $ ForkJob (lockfile, pid)

    -- | Code performing communication with the parent process. During
    -- communication the livelock is created, locked and sent back
    -- to the parent.
    childMain jid s = runProcess jid s P.jqueueExecutorPy commFn
      where
        commFn logFn jid' s' = do
          -- Create a livelock file for the job
          (TOD ts _) <- getClockTime
          lockfile <- P.livelockFile $ printf "job_%06d_%d" (fromJobId jid') ts
          -- Lock the livelock file
          _ <- logFn $ "Locking livelock file " ++ show lockfile
          fd <- lockFile lockfile >>= annotateResult "Can't lock the livelock"
          _ <- logFn "Sending the lockfile name to the master process"
          sendMsg s' lockfile
          _ <- logFn "Waiting for the master process to confirm the lock"
          _ <- recvMsg s'
          return fd

-- | Forks the process and starts the processing of post hooks for the opcode
-- whose execution was unfinished due to job process disappearing.
forkPostHooksProcess :: (FromString e, Show e)
                     => JobId
                     -> ResultT e IO ProcessID
forkPostHooksProcess jid = do
  ForkPostHooks ret <- forkProcessCatchErrors (childMain jid) logDebugJob
                                              parentMain
  return ret
  where
    jidStr = show $ fromJobId jid
    jobLogPrefix pid = "[start:post_hooks:job-" ++ jidStr ++ ",pid="
                       ++ show pid ++ "] "
    logDebugJob pid = logDebug . (jobLogPrefix pid ++)

    -- | Code performing communication with the child process. First, receive
    -- livelock, then send necessary parameters to the python child.
    parentMain pid master = do
      let annotatedIO msg k = do
            logDebugJob pid msg
            liftIO $ rethrowAnnotateIOError (jobLogPrefix pid ++ msg) k
      let recv msg = annotatedIO msg (recvMsg master)
          send msg x = annotatedIO msg (sendMsg master x)
      -- We communicate with the Python process
      _ <- recv "Waiting for the post hooks executor to ask for the job id"
      send "Writing job id to the client" jidStr

      liftIO $ closeClient master
      return $ ForkPostHooks pid

    -- | Code performing communication with the parent process. Python part
    -- will only read job file so, we don't need livelock here.
    childMain jid' s = runProcess jid' s P.postHooksExecutorPy commFn
      where commFn _ _ _ = return (0 :: Fd)

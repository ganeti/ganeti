{-| Implementation of the generic daemon functionality.

-}

{-

Copyright (C) 2011, 2012 Google Inc.
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

module Ganeti.Daemon
  ( DaemonOptions(..)
  , OptType
  , CheckFn
  , PrepFn
  , MainFn
  , defaultOptions
  , oShowHelp
  , oShowVer
  , oNoDaemonize
  , oNoUserChecks
  , oDebug
  , oPort
  , oBindAddress
  , oSyslogUsage
  , oForceNode
  , oNoVoting
  , oYesDoIt
  , parseArgs
  , parseAddress
  , cleanupSocket
  , describeError
  , genericMain
  , getFQDN
  ) where

import Control.Concurrent
import Control.Exception
import Control.Monad
import Data.Maybe (fromMaybe, listToMaybe)
import Text.Printf
import Data.Word
import GHC.IO.Handle (hDuplicateTo)
import Network.BSD (getHostName)
import qualified Network.Socket as Socket
import System.Console.GetOpt
import System.Directory
import System.Exit
import System.Environment
import System.IO
import System.IO.Error (isDoesNotExistError, modifyIOError, annotateIOError)
import System.Posix.Directory
import System.Posix.Files
import System.Posix.IO
import System.Posix.Process
import System.Posix.Types
import System.Posix.Signals

import Ganeti.Common as Common
import Ganeti.Logging
import Ganeti.Runtime
import Ganeti.BasicTypes
import Ganeti.Utils
import qualified Ganeti.Constants as C
import qualified Ganeti.Ssconf as Ssconf

-- * Constants

-- | \/dev\/null path.
devNull :: FilePath
devNull = "/dev/null"

-- | Error message prefix, used in two separate paths (when forking
-- and when not).
daemonStartupErr :: String -> String
daemonStartupErr = ("Error when starting the daemon process: " ++)

-- * Data types

-- | Command line options structure.
data DaemonOptions = DaemonOptions
  { optShowHelp     :: Bool           -- ^ Just show the help
  , optShowVer      :: Bool           -- ^ Just show the program version
  , optShowComp     :: Bool           -- ^ Just show the completion info
  , optDaemonize    :: Bool           -- ^ Whether to daemonize or not
  , optPort         :: Maybe Word16   -- ^ Override for the network port
  , optDebug        :: Bool           -- ^ Enable debug messages
  , optNoUserChecks :: Bool           -- ^ Ignore user checks
  , optBindAddress  :: Maybe String   -- ^ Override for the bind address
  , optSyslogUsage  :: Maybe SyslogUsage -- ^ Override for Syslog usage
  , optForceNode    :: Bool           -- ^ Ignore node checks
  , optNoVoting     :: Bool           -- ^ skip voting for master
  , optYesDoIt      :: Bool           -- ^ force dangerous options
  }

-- | Default values for the command line options.
defaultOptions :: DaemonOptions
defaultOptions  = DaemonOptions
  { optShowHelp     = False
  , optShowVer      = False
  , optShowComp     = False
  , optDaemonize    = True
  , optPort         = Nothing
  , optDebug        = False
  , optNoUserChecks = False
  , optBindAddress  = Nothing
  , optSyslogUsage  = Nothing
  , optForceNode    = False
  , optNoVoting     = False
  , optYesDoIt      = False
  }

instance StandardOptions DaemonOptions where
  helpRequested = optShowHelp
  verRequested  = optShowVer
  compRequested = optShowComp
  requestHelp o = o { optShowHelp = True }
  requestVer  o = o { optShowVer  = True }
  requestComp o = o { optShowComp = True }

-- | Abrreviation for the option type.
type OptType = GenericOptType DaemonOptions

-- | Check function type.
type CheckFn a = DaemonOptions -> IO (Either ExitCode a)

-- | Prepare function type.
type PrepFn a b = DaemonOptions -> a -> IO b

-- | Main execution function type.
type MainFn a b = DaemonOptions -> a -> b -> IO ()

-- * Command line options

oNoDaemonize :: OptType
oNoDaemonize =
  (Option "f" ["foreground"]
   (NoArg (\ opts -> Ok opts { optDaemonize = False }))
   "Don't detach from the current terminal",
   OptComplNone)

oDebug :: OptType
oDebug =
  (Option "d" ["debug"]
   (NoArg (\ opts -> Ok opts { optDebug = True }))
   "Enable debug messages",
   OptComplNone)

oNoUserChecks :: OptType
oNoUserChecks =
  (Option "" ["no-user-checks"]
   (NoArg (\ opts -> Ok opts { optNoUserChecks = True }))
   "Ignore user checks",
   OptComplNone)

oPort :: Int -> OptType
oPort def =
  (Option "p" ["port"]
   (reqWithConversion (tryRead "reading port")
    (\port opts -> Ok opts { optPort = Just port }) "PORT")
   ("Network port (default: " ++ show def ++ ")"),
   OptComplInteger)

oBindAddress :: OptType
oBindAddress =
  (Option "b" ["bind"]
   (ReqArg (\addr opts -> Ok opts { optBindAddress = Just addr })
    "ADDR")
   "Bind address (default depends on cluster configuration)",
   OptComplInetAddr)

oSyslogUsage :: OptType
oSyslogUsage =
  (Option "" ["syslog"]
   (reqWithConversion syslogUsageFromRaw
    (\su opts -> Ok opts { optSyslogUsage = Just su })
    "SYSLOG")
   ("Enable logging to syslog (except debug \
    \messages); one of 'no', 'yes' or 'only' [" ++ C.syslogUsage ++
    "]"),
   OptComplChoices ["yes", "no", "only"])

oForceNode :: OptType
oForceNode =
  (Option "" ["force-node"]
   (NoArg (\ opts -> Ok opts { optForceNode = True }))
   "Force the daemon to run on a different node than the master",
   OptComplNone)

oNoVoting :: OptType
oNoVoting =
  (Option "" ["no-voting"]
   (NoArg (\ opts -> Ok opts { optNoVoting = True }))
   "Skip node agreement check (dangerous)",
   OptComplNone)

oYesDoIt :: OptType
oYesDoIt =
  (Option "" ["yes-do-it"]
   (NoArg (\ opts -> Ok opts { optYesDoIt = True }))
   "Force a dangerous operation",
   OptComplNone)

-- | Generic options.
genericOpts :: [OptType]
genericOpts = [ oShowHelp
              , oShowVer
              , oShowComp
              ]

-- | Annotates and transforms IOErrors into a Result type. This can be
-- used in the error handler argument to 'catch', for example.
ioErrorToResult :: String -> IOError -> IO (Result a)
ioErrorToResult description exc =
  return . Bad $ description ++ ": " ++ show exc

-- | Small wrapper over getArgs and 'parseOpts'.
parseArgs :: String -> [OptType] -> IO (DaemonOptions, [String])
parseArgs cmd options = do
  cmd_args <- getArgs
  parseOpts defaultOptions cmd_args cmd (options ++ genericOpts) []

-- * Daemon-related functions

-- | PID file mode.
pidFileMode :: FileMode
pidFileMode = unionFileModes ownerReadMode ownerWriteMode

-- | PID file open flags.
pidFileFlags :: OpenFileFlags
pidFileFlags = defaultFileFlags { noctty = True, trunc = False }

-- | Writes a PID file and locks it.
writePidFile :: FilePath -> IO Fd
writePidFile path = do
  fd <- openFd path ReadWrite (Just pidFileMode) pidFileFlags
  setLock fd (WriteLock, AbsoluteSeek, 0, 0)
  my_pid <- getProcessID
  _ <- fdWrite fd (show my_pid ++ "\n")
  return fd

-- | Helper function to ensure a socket doesn't exist. Should only be
-- called once we have locked the pid file successfully.
cleanupSocket :: FilePath -> IO ()
cleanupSocket socketPath =
  catchJust (guard . isDoesNotExistError) (removeLink socketPath)
            (const $ return ())

-- | Sets up a daemon's environment.
setupDaemonEnv :: FilePath -> FileMode -> IO ()
setupDaemonEnv cwd umask = do
  changeWorkingDirectory cwd
  _ <- setFileCreationMask umask
  _ <- createSession
  return ()

-- | Cleanup function, performing all the operations that need to be done prior
-- to shutting down a daemon.
finalCleanup :: FilePath -> IO ()
finalCleanup = removeFile

-- | Signal handler for the termination signal.
handleSigTerm :: ThreadId -> IO ()
handleSigTerm mainTID =
  -- Throw termination exception to the main thread, so that the daemon is
  -- actually stopped in the proper way, executing all the functions waiting on
  -- "finally" statement.
  Control.Exception.throwTo mainTID ExitSuccess

-- | Signal handler for reopening log files.
handleSigHup :: FilePath -> IO ()
handleSigHup path = do
  setupDaemonFDs (Just path)
  logInfo "Reopening log files after receiving SIGHUP"

-- | Sets up a daemon's standard file descriptors.
setupDaemonFDs :: Maybe FilePath -> IO ()
setupDaemonFDs logfile = do
  null_in_handle <- openFile devNull ReadMode
  null_out_handle <- openFile (fromMaybe devNull logfile) AppendMode
  hDuplicateTo null_in_handle stdin
  hDuplicateTo null_out_handle stdout
  hDuplicateTo null_out_handle stderr
  hClose null_in_handle
  hClose null_out_handle

-- | Computes the default bind address for a given family.
defaultBindAddr :: Int                  -- ^ The port we want
                -> Socket.Family        -- ^ The cluster IP family
                -> Result (Socket.Family, Socket.SockAddr)
defaultBindAddr port Socket.AF_INET =
  Ok (Socket.AF_INET,
      Socket.SockAddrInet (fromIntegral port) Socket.iNADDR_ANY)
defaultBindAddr port Socket.AF_INET6 =
  Ok (Socket.AF_INET6,
      Socket.SockAddrInet6 (fromIntegral port) 0 Socket.iN6ADDR_ANY 0)
defaultBindAddr _ fam = Bad $ "Unsupported address family: " ++ show fam

-- | Based on the options, compute the socket address to use for the
-- daemon.
parseAddress :: DaemonOptions      -- ^ Command line options
             -> Int                -- ^ Default port for this daemon
             -> IO (Result (Socket.Family, Socket.SockAddr))
parseAddress opts defport = do
  let port = maybe defport fromIntegral $ optPort opts
  def_family <- Ssconf.getPrimaryIPFamily Nothing
  case optBindAddress opts of
    Nothing -> return (def_family >>= defaultBindAddr port)
    Just saddr -> Control.Exception.catch
                    (resolveAddr port saddr)
                    (ioErrorToResult $ "Invalid address " ++ saddr)

-- | Environment variable to override the assumed host name of the
-- current node.
vClusterHostNameEnvVar :: String
vClusterHostNameEnvVar = "GANETI_HOSTNAME"

-- | Get the real full qualified host name.
getFQDN' :: IO String
getFQDN' = do
  hostname <- getHostName
  addrInfos <- Socket.getAddrInfo Nothing (Just hostname) Nothing
  let address = listToMaybe addrInfos >>= (Just . Socket.addrAddress)
  case address of
    Just a -> do
      fqdn <- liftM fst $ Socket.getNameInfo [] True False a
      return (fromMaybe hostname fqdn)
    Nothing -> return hostname

-- | Return the full qualified host name, honoring the vcluster setup.
getFQDN :: IO String
getFQDN = do
  let ioErrorToNothing :: IOError -> IO (Maybe String)
      ioErrorToNothing _ = return Nothing
  vcluster_node <- Control.Exception.catch
                     (liftM Just (getEnv vClusterHostNameEnvVar))
                     ioErrorToNothing
  case vcluster_node of
    Just node_name -> return node_name
    Nothing -> getFQDN'

-- | Returns if the current node is the master node.
isMaster :: IO Bool
isMaster = do
  curNode <- getFQDN
  masterNode <- Ssconf.getMasterNode Nothing
  case masterNode of
    Ok n -> return (curNode == n)
    Bad _ -> return False

-- | Ensures that the daemon runs on the right node (and exits
-- gracefully if it doesnt)
ensureNode :: GanetiDaemon -> DaemonOptions -> IO ()
ensureNode daemon opts = do
  is_master <- isMaster
  when (daemonOnlyOnMaster daemon
        && not is_master
        && not (optForceNode opts)) $ do
    putStrLn "Not master, exiting."
    exitWith (ExitFailure C.exitNotmaster)

-- | Run an I\/O action that might throw an I\/O error, under a
-- handler that will simply annotate and re-throw the exception.
describeError :: String -> Maybe Handle -> Maybe FilePath -> IO a -> IO a
describeError descr hndl fpath =
  modifyIOError (\e -> annotateIOError e descr hndl fpath)

-- | Run an I\/O action as a daemon.
--
-- WARNING: this only works in single-threaded mode (either using the
-- single-threaded runtime, or using the multi-threaded one but with
-- only one OS thread, i.e. -N1).
daemonize :: FilePath -> (Maybe Fd -> IO ()) -> IO ()
daemonize logfile action = do
  (rpipe, wpipe) <- createPipe
  -- first fork
  _ <- forkProcess $ do
    -- in the child
    closeFd rpipe
    let wpipe' = Just wpipe
    setupDaemonEnv "/" (unionFileModes groupModes otherModes)
    setupDaemonFDs (Just logfile) `Control.Exception.catch`
      handlePrepErr False wpipe'
    -- second fork, launches the actual child code; standard
    -- double-fork technique
    _ <- forkProcess (action wpipe')
    exitImmediately ExitSuccess
  closeFd wpipe
  hndl <- fdToHandle rpipe
  errors <- hGetContents hndl
  ecode <- if null errors
             then return ExitSuccess
             else do
               hPutStrLn stderr $ daemonStartupErr errors
               return $ ExitFailure C.exitFailure
  exitImmediately ecode

-- | Generic daemon startup.
genericMain :: GanetiDaemon -- ^ The daemon we're running
            -> [OptType]    -- ^ The available options
            -> CheckFn a    -- ^ Check function
            -> PrepFn  a b  -- ^ Prepare function
            -> MainFn  a b  -- ^ Execution function
            -> IO ()
genericMain daemon options check_fn prep_fn exec_fn = do
  let progname = daemonName daemon

  (opts, args) <- parseArgs progname options

  -- Modify handleClient in Ganeti.UDSServer to remove this logging from luxid.
  when (optDebug opts && daemon == GanetiLuxid) .
    hPutStrLn stderr $
      printf C.debugModeConfidentialityWarning (daemonName daemon)

  ensureNode daemon opts

  exitUnless (null args) "This program doesn't take any arguments"

  unless (optNoUserChecks opts) $ do
    runtimeEnts <- runResultT getEnts
    ents <- exitIfBad "Can't find required user/groups" runtimeEnts
    verifyDaemonUser daemon ents

  syslog <- case optSyslogUsage opts of
              Nothing -> exitIfBad "Invalid cluster syslog setting" $
                         syslogUsageFromRaw C.syslogUsage
              Just v -> return v

  log_file <- daemonLogFile daemon
  -- run the check function and optionally exit if it returns an exit code
  check_result <- check_fn opts
  check_result' <- case check_result of
                     Left code -> exitWith code
                     Right v -> return v

  let processFn = if optDaemonize opts
                    then daemonize log_file
                    else \action -> action Nothing
  _ <- installHandler lostConnection (Catch (handleSigHup log_file)) Nothing
  processFn $ innerMain daemon opts syslog check_result' prep_fn exec_fn

-- | Full prepare function.
--
-- This is executed after daemonization, and sets up both the log
-- files (a generic functionality) and the custom prepare function of
-- the daemon.
fullPrep :: GanetiDaemon  -- ^ The daemon we're running
         -> DaemonOptions -- ^ The options structure, filled from the cmdline
         -> SyslogUsage   -- ^ Syslog mode
         -> a             -- ^ Check results
         -> PrepFn a b    -- ^ Prepare function
         -> IO (FilePath, b)
fullPrep daemon opts syslog check_result prep_fn = do
  logfile <- if optDaemonize opts
               then return Nothing
               else liftM Just $ daemonLogFile daemon
  pidfile <- daemonPidFile daemon
  let dname = daemonName daemon
  setupLogging logfile dname (optDebug opts) True False syslog
  _ <- describeError "writing PID file; already locked?"
         Nothing (Just pidfile) $ writePidFile pidfile
  logNotice $ dname ++ " daemon startup"
  prep_res <- prep_fn opts check_result
  tid <- myThreadId
  _ <- installHandler sigTERM (Catch $ handleSigTerm tid) Nothing
  return (pidfile, prep_res)

-- | Inner daemon function.
--
-- This is executed after daemonization.
innerMain :: GanetiDaemon  -- ^ The daemon we're running
          -> DaemonOptions -- ^ The options structure, filled from the cmdline
          -> SyslogUsage   -- ^ Syslog mode
          -> a             -- ^ Check results
          -> PrepFn a b    -- ^ Prepare function
          -> MainFn a b    -- ^ Execution function
          -> Maybe Fd      -- ^ Error reporting function
          -> IO ()
innerMain daemon opts syslog check_result prep_fn exec_fn fd = do
  (pidFile, prep_result) <- fullPrep daemon opts syslog check_result prep_fn
                 `Control.Exception.catch` handlePrepErr True fd
  -- no error reported, we should now close the fd
  maybeCloseFd fd
  finally (exec_fn opts check_result prep_result) (finalCleanup pidFile)

-- | Daemon prepare error handling function.
handlePrepErr :: Bool -> Maybe Fd -> IOError -> IO a
handlePrepErr logging_setup fd err = do
  let msg = show err
  case fd of
    -- explicitly writing to the fd directly, since when forking it's
    -- better (safer) than trying to convert this into a full handle
    Just fd' -> fdWrite fd' msg >> return ()
    Nothing  -> hPutStrLn stderr (daemonStartupErr msg)
  when logging_setup $ logError msg
  exitWith $ ExitFailure 1

-- | Close a file descriptor.
maybeCloseFd :: Maybe Fd -> IO ()
maybeCloseFd Nothing   = return ()
maybeCloseFd (Just fd) = closeFd fd

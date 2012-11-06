{-| Implementation of the generic daemon functionality.

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
  , parseArgs
  , parseAddress
  , cleanupSocket
  , writePidFile
  , genericMain
  ) where

import Control.Exception
import Control.Monad
import Data.Maybe (fromMaybe)
import Data.Word
import GHC.IO.Handle (hDuplicateTo)
import qualified Network.Socket as Socket
import System.Console.GetOpt
import System.Exit
import System.Environment
import System.IO
import System.IO.Error (isDoesNotExistError)
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
   (NoArg (\ opts -> Ok opts { optDaemonize = False}))
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

-- | Writes a PID file and locks it.
_writePidFile :: FilePath -> IO Fd
_writePidFile path = do
  fd <- createFile path pidFileMode
  setLock fd (WriteLock, AbsoluteSeek, 0, 0)
  my_pid <- getProcessID
  _ <- fdWrite fd (show my_pid ++ "\n")
  return fd

-- | Helper to format an IOError.
formatIOError :: String -> IOError -> String
formatIOError msg err = msg ++ ": " ++  show err

-- | Wrapper over '_writePidFile' that transforms IO exceptions into a
-- 'Bad' value.
writePidFile :: FilePath -> IO (Result Fd)
writePidFile path =
  Control.Exception.catch
    (fmap Ok $ _writePidFile path)
    (return . Bad . formatIOError "Failure during writing of the pid file")

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

-- | Default hints for the resolver
resolveAddrHints :: Maybe Socket.AddrInfo
resolveAddrHints =
  Just Socket.defaultHints { Socket.addrFlags = [Socket.AI_NUMERICHOST,
                                                 Socket.AI_NUMERICSERV] }

-- | Resolves a numeric address.
resolveAddr :: Int -> String -> IO (Result (Socket.Family, Socket.SockAddr))
resolveAddr port str = do
  resolved <- Socket.getAddrInfo resolveAddrHints (Just str) (Just (show port))
  return $ case resolved of
             [] -> Bad "Invalid results from lookup?"
             best:_ -> Ok (Socket.addrFamily best, Socket.addrAddress best)

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

-- | Run an I/O action as a daemon.
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
    setupDaemonEnv "/" (unionFileModes groupModes otherModes)
    setupDaemonFDs $ Just logfile
    _ <- installHandler lostConnection (Catch (handleSigHup logfile)) Nothing
    -- second fork, launches the actual child code; standard
    -- double-fork technique
    _ <- forkProcess (action (Just wpipe))
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

  exitUnless (null args) "This program doesn't take any arguments"

  unless (optNoUserChecks opts) $ do
    runtimeEnts <- getEnts
    ents <- exitIfBad "Can't find required user/groups" runtimeEnts
    verifyDaemonUser daemon ents

  syslog <- case optSyslogUsage opts of
              Nothing -> exitIfBad "Invalid cluster syslog setting" $
                         syslogUsageFromRaw C.syslogUsage
              Just v -> return v

  -- run the check function and optionally exit if it returns an exit code
  check_result <- check_fn opts
  check_result' <- case check_result of
                     Left code -> exitWith code
                     Right v -> return v

  let processFn = if optDaemonize opts
                    then daemonize (daemonLogFile daemon)
                    else \action -> action Nothing
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
         -> IO b
fullPrep daemon opts syslog check_result prep_fn = do
  let logfile = if optDaemonize opts
                  then Nothing
                  else Just $ daemonLogFile daemon
  setupLogging logfile (daemonName daemon) (optDebug opts) True False syslog
  pid_fd <- writePidFile (daemonPidFile daemon)
  _ <- exitIfBad "Cannot write PID file; already locked? Error" pid_fd
  logNotice "starting"
  prep_fn opts check_result

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
  prep_result <- fullPrep daemon opts syslog check_result prep_fn
                 `Control.Exception.catch` handlePrepErr fd
  -- no error reported, we should now close the fd
  maybeCloseFd fd
  exec_fn opts check_result prep_result

-- | Daemon prepare error handling function.
handlePrepErr :: Maybe Fd -> IOError -> IO a
handlePrepErr fd err = do
  let msg = show err
  case fd of
    -- explicitly writing to the fd directly, since when forking it's
    -- better (safer) than trying to convert this into a full handle
    Just fd' -> fdWrite fd' msg >> return ()
    Nothing  -> hPutStrLn stderr (daemonStartupErr msg)
  exitWith $ ExitFailure 1

-- | Close a file descriptor.
maybeCloseFd :: Maybe Fd -> IO ()
maybeCloseFd Nothing   = return ()
maybeCloseFd (Just fd) = closeFd fd

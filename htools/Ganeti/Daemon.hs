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
import Prelude hiding (catch)
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
import Ganeti.HTools.Utils
import qualified Ganeti.Constants as C
import qualified Ganeti.Ssconf as Ssconf

-- * Constants

-- | \/dev\/null path.
devNull :: FilePath
devNull = "/dev/null"

-- * Data types

-- | Command line options structure.
data DaemonOptions = DaemonOptions
  { optShowHelp     :: Bool           -- ^ Just show the help
  , optShowVer      :: Bool           -- ^ Just show the program version
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
  requestHelp o = o { optShowHelp = True }
  requestVer  o = o { optShowVer  = True }

-- | Abrreviation for the option type.
type OptType = GenericOptType DaemonOptions

-- * Command line options

oNoDaemonize :: OptType
oNoDaemonize = Option "f" ["foreground"]
               (NoArg (\ opts -> Ok opts { optDaemonize = False}))
               "Don't detach from the current terminal"

oDebug :: OptType
oDebug = Option "d" ["debug"]
         (NoArg (\ opts -> Ok opts { optDebug = True }))
         "Enable debug messages"

oNoUserChecks :: OptType
oNoUserChecks = Option "" ["no-user-checks"]
         (NoArg (\ opts -> Ok opts { optNoUserChecks = True }))
         "Ignore user checks"

oPort :: Int -> OptType
oPort def = Option "p" ["port"]
            (reqWithConversion (tryRead "reading port")
             (\port opts -> Ok opts { optPort = Just port }) "PORT")
            ("Network port (default: " ++ show def ++ ")")

oBindAddress :: OptType
oBindAddress = Option "b" ["bind"]
               (ReqArg (\addr opts -> Ok opts { optBindAddress = Just addr })
                "ADDR")
               "Bind address (default depends on cluster configuration)"

oSyslogUsage :: OptType
oSyslogUsage = Option "" ["syslog"]
               (reqWithConversion syslogUsageFromRaw
                (\su opts -> Ok opts { optSyslogUsage = Just su })
                "SYSLOG")
               ("Enable logging to syslog (except debug \
                \messages); one of 'no', 'yes' or 'only' [" ++ C.syslogUsage ++
                "]")

-- | Small wrapper over getArgs and 'parseOpts'.
parseArgs :: String -> [OptType] -> IO (DaemonOptions, [String])
parseArgs cmd options = do
  cmd_args <- getArgs
  parseOpts defaultOptions cmd_args cmd options

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
  catch (fmap Ok $ _writePidFile path)
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
    Just saddr -> catch (resolveAddr port saddr)
                  (annotateIOError $ "Invalid address " ++ saddr)

-- | Run an I/O action as a daemon.
--
-- WARNING: this only works in single-threaded mode (either using the
-- single-threaded runtime, or using the multi-threaded one but with
-- only one OS thread, i.e. -N1).
--
-- FIXME: this doesn't support error reporting and the prepfn
-- functionality.
daemonize :: FilePath -> IO () -> IO ()
daemonize logfile action = do
  -- first fork
  _ <- forkProcess $ do
    -- in the child
    setupDaemonEnv "/" (unionFileModes groupModes otherModes)
    setupDaemonFDs $ Just logfile
    _ <- installHandler lostConnection (Catch (handleSigHup logfile)) Nothing
    _ <- forkProcess action
    exitImmediately ExitSuccess
  exitImmediately ExitSuccess

-- | Generic daemon startup.
genericMain :: GanetiDaemon -> [OptType] -> (DaemonOptions -> IO ()) -> IO ()
genericMain daemon options main = do
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
  let processFn = if optDaemonize opts
                    then daemonize (daemonLogFile daemon)
                    else id
  processFn $ innerMain daemon opts syslog (main opts)

-- | Inner daemon function.
--
-- This is executed after daemonization.
innerMain :: GanetiDaemon -> DaemonOptions -> SyslogUsage -> IO () -> IO ()
innerMain daemon opts syslog main = do
  let logfile = if optDaemonize opts
                  then Nothing
                  else Just $ daemonLogFile daemon
  setupLogging logfile (daemonName daemon) (optDebug opts) True False syslog
  pid_fd <- writePidFile (daemonPidFile daemon)
  _ <- exitIfBad "Cannot write PID file; already locked? Error" pid_fd
  logNotice "starting"
  main

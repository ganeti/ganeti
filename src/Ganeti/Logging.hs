{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti logging functionality.

This currently lacks the following (FIXME):

- log file reopening

Note that this requires the hslogger library version 1.1 and above.

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

module Ganeti.Logging
  ( setupLogging
  , MonadLog(..)
  , Priority(..)
  , logDebug
  , logInfo
  , logNotice
  , logWarning
  , logError
  , logCritical
  , logAlert
  , logEmergency
  , SyslogUsage(..)
  , syslogUsageToRaw
  , syslogUsageFromRaw
  , withErrorLogAt
  , isDebugMode
  ) where

import Control.Applicative ((<$>))
import Control.Monad
import Control.Monad.Error (Error(..), MonadError(..), catchError)
import Control.Monad.Reader
import System.Log.Logger
import System.Log.Handler.Simple
import System.Log.Handler.Syslog
import System.Log.Handler (setFormatter, LogHandler)
import System.Log.Formatter
import System.IO

import Ganeti.BasicTypes (ResultT(..))
import Ganeti.THH
import qualified Ganeti.ConstantUtils as ConstantUtils

-- | Syslog usage type.
$(declareLADT ''String "SyslogUsage"
  [ ("SyslogNo",   "no")
  , ("SyslogYes",  "yes")
  , ("SyslogOnly", "only")
  ])

-- | Builds the log formatter.
logFormatter :: String  -- ^ Program
             -> Bool    -- ^ Multithreaded
             -> Bool    -- ^ Syslog
             -> LogFormatter a
logFormatter prog mt syslog =
  let parts = [ if syslog
                  then "[$pid]:"
                  else "$time: " ++ prog ++ " pid=$pid"
              , if mt then if syslog then " ($tid)" else "/$tid"
                  else ""
              , " $prio $msg"
              ]
  in tfLogFormatter "%F %X,%q %Z" $ concat parts

-- | Helper to open and set the formatter on a log if enabled by a
-- given condition, otherwise returning an empty list.
openFormattedHandler :: (LogHandler a) => Bool
                     -> LogFormatter a -> IO a -> IO [a]
openFormattedHandler False _ _ = return []
openFormattedHandler True fmt opener = do
  handler <- opener
  return [setFormatter handler fmt]

-- | Sets up the logging configuration.
setupLogging :: Maybe String    -- ^ Log file
             -> String    -- ^ Program name
             -> Bool      -- ^ Debug level
             -> Bool      -- ^ Log to stderr
             -> Bool      -- ^ Log to console
             -> SyslogUsage -- ^ Syslog usage
             -> IO ()
setupLogging logf program debug stderr_logging console syslog = do
  let level = if debug then DEBUG else INFO
      destf = if console then Just ConstantUtils.devConsole else logf
      fmt = logFormatter program False False
      file_logging = syslog /= SyslogOnly

  updateGlobalLogger rootLoggerName (setLevel level)

  stderr_handlers <- openFormattedHandler stderr_logging fmt $
                     streamHandler stderr level

  file_handlers <- case destf of
                     Nothing -> return []
                     Just path -> openFormattedHandler file_logging fmt $
                                  fileHandler path level

  let handlers = file_handlers ++ stderr_handlers
  updateGlobalLogger rootLoggerName $ setHandlers handlers
  -- syslog handler is special (another type, still instance of the
  -- typeclass, and has a built-in formatter), so we can't pass it in
  -- the above list
  when (syslog /= SyslogNo) $ do
    syslog_handler <- openlog program [PID] DAEMON INFO
    updateGlobalLogger rootLoggerName $ addHandler syslog_handler

-- * Logging function aliases

-- | A monad that allows logging.
class Monad m => MonadLog m where
  -- | Log at a given level.
  logAt :: Priority -> String -> m ()

instance MonadLog IO where
  logAt = logM rootLoggerName

instance (MonadLog m) => MonadLog (ReaderT r m) where
  logAt p = lift . logAt p

instance (MonadLog m, Error e) => MonadLog (ResultT e m) where
  logAt p = lift . logAt p

-- | Log at debug level.
logDebug :: (MonadLog m) => String -> m ()
logDebug = logAt DEBUG

-- | Log at info level.
logInfo :: (MonadLog m) => String -> m ()
logInfo = logAt INFO

-- | Log at notice level.
logNotice :: (MonadLog m) => String -> m ()
logNotice = logAt NOTICE

-- | Log at warning level.
logWarning :: (MonadLog m) => String -> m ()
logWarning = logAt WARNING

-- | Log at error level.
logError :: (MonadLog m) => String -> m ()
logError = logAt ERROR

-- | Log at critical level.
logCritical :: (MonadLog m) => String -> m ()
logCritical = logAt CRITICAL

-- | Log at alert level.
logAlert :: (MonadLog m) => String -> m ()
logAlert = logAt ALERT

-- | Log at emergency level.
logEmergency :: (MonadLog m) => String -> m ()
logEmergency = logAt EMERGENCY

-- | Check if the logging is at DEBUG level.
-- DEBUG logging is unacceptable for production.
isDebugMode :: IO Bool
isDebugMode = (Just DEBUG ==) . getLevel <$> getRootLogger

-- * Logging in an error monad with rethrowing errors

-- | If an error occurs within a given computation, it annotated
-- with a given message and logged and the error is re-thrown.
withErrorLogAt :: (MonadLog m, MonadError e m, Show e)
               => Priority -> String -> m a -> m a
withErrorLogAt prio msg = flip catchError $ \e -> do
  logAt prio (msg ++ ": " ++ show e)
  throwError e

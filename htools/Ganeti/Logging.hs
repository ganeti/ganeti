{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti logging functionality.

This currently lacks the following (FIXME):

- log file reopening

Note that this requires the hslogger library version 1.1 and above.

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

module Ganeti.Logging
  ( setupLogging
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
  ) where

import Control.Monad (when)
import System.Log.Logger
import System.Log.Handler.Simple
import System.Log.Handler.Syslog
import System.Log.Handler (setFormatter, LogHandler)
import System.Log.Formatter
import System.IO

import Ganeti.THH
import qualified Ganeti.Constants as C

-- | Syslog usage type.
$(declareSADT "SyslogUsage"
  [ ("SyslogNo",   'C.syslogNo)
  , ("SyslogYes",  'C.syslogYes)
  , ("SyslogOnly", 'C.syslogOnly)
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
  in simpleLogFormatter $ concat parts

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
      destf = if console then Just C.devConsole else logf
      fmt = logFormatter program False False
      file_logging = syslog /= SyslogOnly

  updateGlobalLogger rootLoggerName (setLevel level)

  stderr_handlers <- openFormattedHandler stderr_logging fmt $
                     streamHandler stderr level

  file_handlers <- case destf of
                     Nothing -> return []
                     Just path -> openFormattedHandler file_logging fmt $
                                  fileHandler path level

  let handlers = concat [file_handlers, stderr_handlers]
  updateGlobalLogger rootLoggerName $ setHandlers handlers
  -- syslog handler is special (another type, still instance of the
  -- typeclass, and has a built-in formatter), so we can't pass it in
  -- the above list
  when (syslog /= SyslogNo) $ do
    syslog_handler <- openlog program [PID] DAEMON INFO
    updateGlobalLogger rootLoggerName $ addHandler syslog_handler

-- * Logging function aliases

-- | Log at debug level.
logDebug :: String -> IO ()
logDebug = debugM rootLoggerName

-- | Log at info level.
logInfo :: String -> IO ()
logInfo = infoM rootLoggerName

-- | Log at notice level.
logNotice :: String -> IO ()
logNotice = noticeM rootLoggerName

-- | Log at warning level.
logWarning :: String -> IO ()
logWarning = warningM rootLoggerName

-- | Log at error level.
logError :: String -> IO ()
logError = errorM rootLoggerName

-- | Log at critical level.
logCritical :: String -> IO ()
logCritical = criticalM rootLoggerName

-- | Log at alert level.
logAlert :: String -> IO ()
logAlert = alertM rootLoggerName

-- | Log at emergency level.
logEmergency :: String -> IO ()
logEmergency = emergencyM rootLoggerName

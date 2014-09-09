{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti logging functionality.

This currently lacks the following (FIXME):

- log file reopening

Note that this requires the hslogger library version 1.1 and above.

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.
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

{-# LANGUAGE OverloadedStrings #-}

{-| Utils for HTTP servers

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.Utils.Http
  ( httpConfFromOpts
  , error404
  , plainJSON
  ) where

import Control.Monad (liftM)
import Data.ByteString.Char8 (pack)
import Data.Map ((!))
import Data.Maybe (fromMaybe)
import Network.BSD (getServicePortNumber)
import qualified Network.Socket as Socket
import Snap.Core (Snap, writeBS, modifyResponse, setResponseStatus)
import Snap.Http.Server.Config ( Config, ConfigLog(ConfigFileLog), emptyConfig
                               , setAccessLog, setErrorLog, setCompression
                               , setVerbose, setPort, setBind )
import qualified Text.JSON as J

import Ganeti.BasicTypes (GenericResult(..))
import qualified Ganeti.Constants as C
import Ganeti.Daemon (DaemonOptions(..))
import Ganeti.Runtime ( GanetiDaemon, daemonName
                      , daemonsExtraLogFile, ExtraLogReason(..))
import qualified Ganeti.Ssconf as Ssconf
import Ganeti.Utils (withDefaultOnIOError)

-- * Configuration handling

-- | The default configuration for the HTTP server.
defaultHttpConf :: FilePath -> FilePath -> Config Snap ()
defaultHttpConf accessLog errorLog =
  setAccessLog (ConfigFileLog accessLog) .
  setCompression False .
  setErrorLog (ConfigFileLog errorLog) $
  setVerbose False
  emptyConfig

-- | Get the HTTP Configuration from the daemon options.
httpConfFromOpts :: GanetiDaemon -> DaemonOptions -> IO (Config Snap ())
httpConfFromOpts daemon opts = do
  accessLog <- daemonsExtraLogFile daemon AccessLog
  errorLog <- daemonsExtraLogFile daemon ErrorLog
  let name = daemonName daemon
      standardPort = snd $ C.daemonsPorts ! name
  defaultPort <- withDefaultOnIOError standardPort
                 . liftM fromIntegral
                 $ getServicePortNumber name
  defaultFamily <- Ssconf.getPrimaryIPFamily Nothing
  let defaultBind = if defaultFamily == Ok Socket.AF_INET6 then "::" else "*"
  return .
    setPort (maybe defaultPort fromIntegral (optPort opts)) .
    setBind (pack . fromMaybe defaultBind $ optBindAddress opts)
    $ defaultHttpConf accessLog errorLog


-- * Standard answers

-- | Resource not found error
error404 :: Snap ()
error404 = do
  modifyResponse $ setResponseStatus 404 "Not found"
  writeBS "Resource not found"

-- | Return the JSON encoding of an object
plainJSON :: J.JSON a => a -> Snap ()
plainJSON = writeBS . pack . J.encode

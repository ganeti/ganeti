{-# LANGUAGE TupleSections #-}
{-| Configuration server for the metadata daemon.

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
module Ganeti.Metad.ConfigServer where

import Control.Concurrent (forkIO)
import Control.Concurrent.MVar (MVar)
import Control.Exception (finally)
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Path as Path
import Ganeti.Daemon (DaemonOptions, cleanupSocket, describeError)
import qualified Ganeti.JSON as J
import qualified Ganeti.Logging as Logging
import Ganeti.Runtime (GanetiDaemon(..))
import Ganeti.UDSServer (Client, ConnectConfig(..), Server, ServerConfig(..))
import qualified Ganeti.UDSServer as UDSServer

import Ganeti.Metad.ConfigCore
import Ganeti.Metad.Types (InstanceParams)

-- | Reads messages from clients and update the configuration
-- according to these messages.
acceptConfig :: MetadHandle -> Client -> IO ()
acceptConfig config client = do
  result <- runResultT $ do
    msg <- liftIO $ UDSServer.recvMsg client
    Logging.logDebug $ "Received: " ++ msg
    instData <- toErrorStr . J.fromJResultE "Parsing instance data" . J.decode
                $ msg
    runMetadMonad (updateConfig instData) config
  annotateResult "Updating Metad instance configuration" $ withError show result

-- | Loop that accepts clients and dispatches them to an isolated
-- thread that will handle the client's requests.
acceptClients :: MetadHandle -> Server -> IO ()
acceptClients config server =
  do client <- UDSServer.acceptClient server
     _ <- forkIO $ acceptConfig config client
     acceptClients config server

start :: DaemonOptions -> MVar InstanceParams -> IO ()
start _ config = do
     socket_path <- Path.defaultMetadSocket
     cleanupSocket socket_path
     server <- describeError "binding to the socket" Nothing (Just socket_path)
               $ UDSServer.connectServer metadConfig True socket_path
     finally
       (acceptClients (MetadHandle config) server)
       (UDSServer.closeServer server)
  where
    metadConfig = ServerConfig GanetiMetad $ ConnectConfig 60 60

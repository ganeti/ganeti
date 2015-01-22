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

import Control.Concurrent
import Control.Exception (try, finally)
import Control.Monad (unless)
import Text.JSON
import System.IO.Error (isEOFError)

import Ganeti.Path as Path
import Ganeti.Daemon (DaemonOptions)
import qualified Ganeti.Logging as Logging
import Ganeti.Runtime (GanetiDaemon(..))
import Ganeti.UDSServer (Client, ConnectConfig(..), Server, ServerConfig(..))
import qualified Ganeti.UDSServer as UDSServer

import Ganeti.Metad.Config as Config
import Ganeti.Metad.Types (InstanceParams)

-- | Update the configuration with the received instance parameters.
updateConfig :: MVar InstanceParams -> String -> IO ()
updateConfig config str =
  case decode str of
    Error err ->
      Logging.logDebug $ show err
    Ok x ->
      case Config.getInstanceParams x of
        Error err ->
          Logging.logError $ "Could not get instance parameters: " ++ err
        Ok (name, instanceParams) -> do
          cfg <- takeMVar config
          let cfg' = mergeConfig cfg instanceParams
          putMVar config cfg'
          Logging.logInfo $
            "Updated instance " ++ show name ++ " configuration"
          Logging.logDebug $ "Instance configuration: " ++ show cfg'

-- | Reads messages from clients and update the configuration
-- according to these messages.
acceptConfig :: MVar InstanceParams -> Client -> IO ()
acceptConfig config client =
  do res <- try $ UDSServer.recvMsg client
     case res of
       Left err -> do
         unless (isEOFError err) .
           Logging.logDebug $ show err
         return ()
       Right str -> do
         Logging.logDebug $ "Received: " ++ str
         updateConfig config str

-- | Loop that accepts clients and dispatches them to an isolated
-- thread that will handle the client's requests.
acceptClients :: MVar InstanceParams -> Server -> IO ()
acceptClients config server =
  do client <- UDSServer.acceptClient server
     _ <- forkIO $ acceptConfig config client
     acceptClients config server

start :: DaemonOptions -> MVar InstanceParams -> IO ()
start _ config = do
     socket_path <- Path.defaultMetadSocket
     server <- UDSServer.connectServer metadConfig True socket_path
     finally
       (acceptClients config server)
       (UDSServer.closeServer server)
  where
    metadConfig = ServerConfig GanetiMetad $ ConnectConfig 60 60

{-# LANGUAGE TupleSections, TemplateHaskell #-}
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

import Control.Exception (finally)
import Control.Monad (forever)

import Ganeti.Path as Path
import Ganeti.Daemon (DaemonOptions, cleanupSocket, describeError)
import Ganeti.Runtime (GanetiDaemon(..), GanetiGroup(..), MiscGroup(..))
import Ganeti.THH.RPC
import Ganeti.UDSServer (ConnectConfig(..), ServerConfig(..))
import qualified Ganeti.UDSServer as UDSServer
import Ganeti.Utils (FilePermissions(..))

import Ganeti.Metad.ConfigCore

-- * The handler that converts RPCs to calls to the above functions

handler :: RpcServer MetadMonadInt
handler = $( mkRpcM exportedFunctions )

-- * The main server code

start :: DaemonOptions -> MetadHandle -> IO ()
start _ config = do
     socket_path <- Path.defaultMetadSocket
     cleanupSocket socket_path
     server <- describeError "binding to the socket" Nothing (Just socket_path)
               $ UDSServer.connectServer metadConfig True socket_path
     finally
       (forever $ runMetadMonadInt (UDSServer.listener handler server) config)
       (UDSServer.closeServer server)
  where
    metadConfig =
      ServerConfig
        -- The permission 0600 is completely acceptable because only the node
        -- daemon talks to the metadata daemon, and the node daemon runs as
        -- root.
        FilePermissions { fpOwner = Just GanetiMetad
                        , fpGroup = Just $ ExtraGroup DaemonsGroup
                        , fpPermissions = 0o0600
                        }
        ConnectConfig { recvTmo = 60
                      , sendTmo = 60
                      }

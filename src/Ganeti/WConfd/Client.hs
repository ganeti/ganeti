{-# LANGUAGE TemplateHaskell #-}

{-| The Ganeti WConfd client functions.

The client functions are automatically generated from Ganeti.WConfd.Core

-}

{-

Copyright (C) 2014 Google Inc.

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

module Ganeti.WConfd.Client where

import Ganeti.THH.HsRPC
import Ganeti.Constants
import Ganeti.Runtime (GanetiDaemon(..))
import Ganeti.UDSServer (ConnectConfig(..), Client, connectClient)
import Ganeti.WConfd.Core (exportedFunctions)

-- * Generated client functions

$(mkRpcCalls exportedFunctions)

-- * Helper functions for creating the client

-- | The default WConfd client configuration
wconfdConnectConfig :: ConnectConfig
wconfdConnectConfig = ConnectConfig { connDaemon = GanetiWConfd
                                    , recvTmo    = wconfdDefRwto
                                    , sendTmo    = wconfdDefRwto
                                    }

-- | Given a socket path, creates a WConfd client with the default
-- configuration and timeout.
getWConfdClient :: FilePath -> IO Client
getWConfdClient = connectClient wconfdConnectConfig wconfdDefCtmo

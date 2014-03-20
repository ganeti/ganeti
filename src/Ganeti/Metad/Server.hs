{-| Metadata daemon server, which controls the configuration and web servers.

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
module Ganeti.Metad.Server (start) where

import Control.Concurrent
import qualified Data.Map (empty)

import Ganeti.Daemon (DaemonOptions)
import qualified Ganeti.Metad.ConfigServer as ConfigServer
import qualified Ganeti.Metad.WebServer as WebServer

start :: DaemonOptions -> IO ()
start opts =
  do config <- newMVar Data.Map.empty
     _ <- forkIO $ WebServer.start opts config
     ConfigServer.start opts config

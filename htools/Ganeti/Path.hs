{-| Path-related helper functions.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.Path
  ( defaultLuxiSocket
  , defaultQuerySocket
  , dataDir
  , logDir
  , runDir
  , confdHmacKey
  , clusterConfFile
  , nodedCertFile
  ) where

import qualified Ganeti.Constants as C
import System.FilePath


-- | Directory for data
dataDir :: FilePath
dataDir = C.autoconfLocalstatedir </> "lib" </> "ganeti"

-- | Directory for runtime files
runDir :: FilePath
runDir = C.autoconfLocalstatedir </> "run" </> "ganeti"

-- | Directory for log files
logDir :: FilePath
logDir = C.autoconfLocalstatedir </> "log" </> "ganeti"

-- | Directory for Unix sockets
socketDir :: FilePath
socketDir = runDir </> "socket"

-- | The default LUXI socket path.
defaultLuxiSocket :: FilePath
defaultLuxiSocket = socketDir </> "ganeti-master"

-- | The default LUXI socket for queries.
defaultQuerySocket :: FilePath
defaultQuerySocket = socketDir </> "ganeti-query"

-- | Path to file containing confd's HMAC key
confdHmacKey :: FilePath
confdHmacKey = dataDir </> "hmac.key"

-- | Path to cluster configuration file
clusterConfFile :: FilePath
clusterConfFile  = dataDir </> "config.data"

-- | Path
nodedCertFile  :: FilePath
nodedCertFile = dataDir </> "server.pem"

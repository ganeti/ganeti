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
  ( dataDir
  , runDir
  , logDir
  , socketDir
  , defaultLuxiSocket
  , defaultQuerySocket
  , confdHmacKey
  , clusterConfFile
  , nodedCertFile
  , queueDir
  , jobQueueSerialFile
  , jobQueueArchiveSubDir
  , instanceReasonDir
  , getInstReasonFilename
  ) where

import System.FilePath
import System.Posix.Env (getEnvDefault)

import AutoConf

-- | Simple helper to concat two paths.
pjoin :: IO String -> String -> IO String
pjoin a b = do
  a' <- a
  return $ a' </> b

-- | Returns the root directory, which can be either the real root or
-- the virtual root.
getRootDir :: IO FilePath
getRootDir = getEnvDefault "GANETI_ROOTDIR" ""

-- | Prefixes a path with the current root directory.
addNodePrefix :: FilePath -> IO FilePath
addNodePrefix path = do
  root <- getRootDir
  return $ root ++ path

-- | Directory for data.
dataDir :: IO FilePath
dataDir = addNodePrefix $ AutoConf.localstatedir </> "lib" </> "ganeti"

-- | Helper for building on top of dataDir (internal).
dataDirP :: FilePath -> IO FilePath
dataDirP = (dataDir `pjoin`)

-- | Directory for runtime files.
runDir :: IO FilePath
runDir = addNodePrefix $ AutoConf.localstatedir </> "run" </> "ganeti"

-- | Directory for log files.
logDir :: IO FilePath
logDir = addNodePrefix $ AutoConf.localstatedir </> "log" </> "ganeti"

-- | Directory for Unix sockets.
socketDir :: IO FilePath
socketDir = runDir `pjoin` "socket"

-- | The default LUXI socket path.
defaultLuxiSocket :: IO FilePath
defaultLuxiSocket = socketDir `pjoin` "ganeti-master"

-- | The default LUXI socket for queries.
defaultQuerySocket :: IO FilePath
defaultQuerySocket = socketDir `pjoin` "ganeti-query"

-- | Path to file containing confd's HMAC key.
confdHmacKey :: IO FilePath
confdHmacKey = dataDirP "hmac.key"

-- | Path to cluster configuration file.
clusterConfFile :: IO FilePath
clusterConfFile  = dataDirP "config.data"

-- | Path to the noded certificate.
nodedCertFile :: IO FilePath
nodedCertFile = dataDirP "server.pem"

-- | Job queue directory.
queueDir :: IO FilePath
queueDir = dataDirP "queue"

-- | Job queue serial file.
jobQueueSerialFile :: IO FilePath
jobQueueSerialFile = queueDir `pjoin` "serial"

-- | Job queue archive directory.
jobQueueArchiveSubDir :: FilePath
jobQueueArchiveSubDir = "archive"

-- | Directory containing the reason trails for the last change of status of
-- instances.
instanceReasonDir :: IO FilePath
instanceReasonDir = runDir `pjoin` "instance-reason"

-- | The path of the file containing the reason trail for an instance, given the
-- instance name.
getInstReasonFilename :: String -> IO FilePath
getInstReasonFilename instName = instanceReasonDir `pjoin` instName

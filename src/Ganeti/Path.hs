{-| Path-related helper functions.

-}

{-

Copyright (C) 2012 Google Inc.
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

module Ganeti.Path
  ( dataDir
  , runDir
  , logDir
  , socketDir
  , defaultMasterSocket
  , defaultQuerySocket
  , confdHmacKey
  , clusterConfFile
  , watcherPauseFile
  , nodedCertFile
  , nodedClientCertFile
  , queueDir
  , jobQueueSerialFile
  , jobQueueLockFile 
  , jobQueueDrainFile  
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

-- | The default path for the master-daemon LUXI socket.
defaultMasterSocket :: IO FilePath
defaultMasterSocket = socketDir `pjoin` "ganeti-master"

-- | The default LUXI socket for queries.
defaultQuerySocket :: IO FilePath
defaultQuerySocket = socketDir `pjoin` "ganeti-query"

-- | Path to file containing confd's HMAC key.
confdHmacKey :: IO FilePath
confdHmacKey = dataDirP "hmac.key"

-- | Path to cluster configuration file.
clusterConfFile :: IO FilePath
clusterConfFile  = dataDirP "config.data"

-- | Path to the watcher pause file.
watcherPauseFile :: IO FilePath
watcherPauseFile = dataDirP "watcher.pause"

-- | Path to the noded certificate.
nodedCertFile :: IO FilePath
nodedCertFile = dataDirP "server.pem"

-- | Path to the noded client certificate.
nodedClientCertFile :: IO FilePath
nodedClientCertFile = dataDirP "client.pem"

-- | Job queue directory.
queueDir :: IO FilePath
queueDir = dataDirP "queue"

-- | Job queue serial file.
jobQueueSerialFile :: IO FilePath
jobQueueSerialFile = queueDir `pjoin` "serial"

-- | Job queue lock file
jobQueueLockFile :: IO FilePath
jobQueueLockFile = queueDir `pjoin` "lock"

-- | Job queue drain file
jobQueueDrainFile :: IO FilePath
jobQueueDrainFile = queueDir `pjoin` "drain"

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

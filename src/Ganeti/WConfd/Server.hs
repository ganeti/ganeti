{-# LANGUAGE TemplateHaskell #-}

{-| The implementation of Ganeti WConfd daemon server.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

-}

{-

Copyright (C) 2013, 2014 Google Inc.
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

module Ganeti.WConfd.Server where

import Control.Concurrent (forkIO)
import Control.Exception
import Control.Monad
import Control.Monad.Error

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.Daemon
import Ganeti.Daemon.Utils (handleMasterVerificationOptions)
import Ganeti.Logging (logDebug)
import qualified Ganeti.Path as Path
import Ganeti.THH.RPC
import Ganeti.UDSServer
import Ganeti.Errors (formatError)
import Ganeti.Runtime
import Ganeti.Utils
import Ganeti.Utils.Livelock (mkLivelockFile)
import Ganeti.WConfd.ConfigState
import Ganeti.WConfd.ConfigVerify
import Ganeti.WConfd.ConfigWriter
import Ganeti.WConfd.Core
import Ganeti.WConfd.DeathDetection (cleanupLocksTask)
import Ganeti.WConfd.Monad
import Ganeti.WConfd.Persistent

handler :: DaemonHandle -> RpcServer WConfdMonadInt
handler _ = $( mkRpcM exportedFunctions )


-- | Type alias for prepMain results
type PrepResult = (Server, DaemonHandle)

-- | Check function for luxid.
checkMain :: CheckFn ()
checkMain = handleMasterVerificationOptions

-- | Prepare function for luxid.
prepMain :: PrepFn () PrepResult
prepMain _ _ = do
  socket_path <- Path.defaultWConfdSocket
  cleanupSocket socket_path
  s <- describeError "binding to the socket" Nothing (Just socket_path)
         $ connectServer serverConfig True socket_path

  -- TODO: Lock the configuration file so that running the daemon twice fails?
  conf_file <- Path.clusterConfFile

  dh <- toErrorBase
        . withErrorT (strMsg . ("Initialization of the daemon failed" ++)
                             . formatError) $ do
    ents <- getEnts
    (cdata, cstat) <- loadConfigFromFile conf_file
    verifyConfigErr cdata
    lock <- readPersistent persistentLocks
    tempres <- readPersistent persistentTempRes
    (_, livelock) <- mkLivelockFile C.wconfLivelockPrefix
    mkDaemonHandle conf_file
                   (mkConfigState cdata)
                   lock
                   tempres
                   (saveConfigAsyncTask conf_file cstat)
                   (distMCsAsyncTask ents conf_file)
                   distSSConfAsyncTask
                   (writePersistentAsyncTask persistentLocks)
                   (writePersistentAsyncTask persistentTempRes)
                   livelock

  return (s, dh)

serverConfig :: ServerConfig
serverConfig = ServerConfig
                 -- All the daemons that need to talk to WConfd should be
                 -- running as the same user - the former master daemon user.
                 FilePermissions { fpOwner = Just GanetiWConfd
                                 , fpGroup = Just $ ExtraGroup DaemonsGroup
                                 , fpPermissions = 0o0600
                                 }
                 ConnectConfig { recvTmo = 60
                               , sendTmo = 60
                               }


-- | Main function.
main :: MainFn () PrepResult
main _ _ (server, dh) = do
  logDebug "Starting the cleanup task"
  _ <- forkIO $ runWConfdMonadInt cleanupLocksTask dh
  finally
    (forever $ runWConfdMonadInt (listener (handler dh) server) dh)
    (liftIO $ closeServer server)


-- | Options list and functions.
options :: [OptType]
options =
  [ oNoDaemonize
  , oNoUserChecks
  , oDebug
  , oSyslogUsage
  , oForceNode
  , oNoVoting
  , oYesDoIt
  ]

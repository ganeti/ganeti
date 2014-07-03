{-# LANGUAGE TemplateHaskell #-}

{-| The implementation of Ganeti WConfd daemon server.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

-}

{-

Copyright (C) 2013, 2014 Google Inc.

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

module Ganeti.WConfd.Server where

import Control.Concurrent (forkIO)
import Control.Exception
import Control.Monad
import Control.Monad.Error

import Ganeti.BasicTypes
import Ganeti.Daemon
import Ganeti.Daemon.Utils (handleMasterVerificationOptions)
import Ganeti.Logging (logDebug)
import qualified Ganeti.Path as Path
import Ganeti.THH.RPC
import Ganeti.UDSServer

import Ganeti.Errors (formatError)
import Ganeti.Runtime
import Ganeti.WConfd.ConfigState
import Ganeti.WConfd.ConfigVerify
import Ganeti.WConfd.ConfigWriter
import Ganeti.WConfd.Core
import Ganeti.WConfd.DeathDetection (cleanupLocksTask)
import Ganeti.WConfd.Monad
import Ganeti.WConfd.Persistent

handler :: DaemonHandle -> RpcServer WConfdMonadInt
handler ch = $( mkRpcM exportedFunctions )


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
    mkDaemonHandle conf_file
                   (mkConfigState cdata)
                   lock
                   tempres
                   (saveConfigAsyncTask conf_file cstat)
                   (distMCsAsyncTask ents conf_file)
                   distSSConfAsyncTask
                   (writePersistentAsyncTask persistentLocks)
                   (writePersistentAsyncTask persistentTempRes)

  return (s, dh)

serverConfig :: ServerConfig
serverConfig = ServerConfig GanetiLuxid $ ConnectConfig 60 60

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

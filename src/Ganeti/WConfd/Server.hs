{-# LANGUAGE TemplateHaskell #-}

{-| The implementation of Ganeti WConfd daemon server.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

-}

{-

Copyright (C) 2013 Google Inc.

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

import Control.Exception
import Control.Monad
import Control.Monad.Error
import System.Directory (doesFileExist)

import Ganeti.BasicTypes
import Ganeti.Daemon
import Ganeti.Logging (logInfo)
import Ganeti.Locking.Allocation
import Ganeti.Locking.Locks
import qualified Ganeti.Path as Path
import Ganeti.THH.RPC
import Ganeti.UDSServer

import Ganeti.Runtime
import Ganeti.WConfd.ConfigState
import Ganeti.WConfd.ConfigWriter
import Ganeti.WConfd.Core
import Ganeti.WConfd.Monad

handler :: DaemonHandle -> RpcServer WConfdMonadInt
handler ch = $( mkRpcM exportedFunctions )


-- | Type alias for prepMain results
type PrepResult = (Server, DaemonHandle)

-- | Check function for luxid.
checkMain :: CheckFn ()
checkMain _ = return $ Right ()

-- | Prepare function for luxid.
prepMain :: PrepFn () PrepResult
prepMain _ _ = do
  socket_path <- Path.defaultWConfdSocket
  cleanupSocket socket_path
  s <- describeError "binding to the socket" Nothing (Just socket_path)
         $ connectServer connectConfig True socket_path
  -- TODO: Lock the configuration file so that running the daemon twice fails?
  conf_file <- Path.clusterConfFile

  lock_file <- Path.lockStatusFile
  lock_file_present <- doesFileExist lock_file
  unless lock_file_present
    $ logInfo "No saved lock status; assuming all locks free"
  dhOpt <- runResultT $ do
    (cdata, cstat) <- loadConfigFromFile conf_file
    lock <- if lock_file_present
              then loadLockAllocation lock_file
              else return emptyAllocation
    mkDaemonHandle conf_file
                   (mkConfigState cdata)
                   lock
                   (saveConfigAsyncTask conf_file cstat)
                   (writeLocksAsyncTask lock_file)
  dh <- withError (strMsg . ("Initialization of the daemon failed" ++) . show)
                  dhOpt

  return (s, dh)

connectConfig :: ConnectConfig
connectConfig = ConnectConfig GanetiLuxid 60 60

-- | Main function.
main :: MainFn () PrepResult
main _ _ (server, dh) =
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
  ]

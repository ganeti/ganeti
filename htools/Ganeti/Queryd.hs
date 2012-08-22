{-# LANGUAGE BangPatterns #-}

{-| Implementation of the Ganeti confd types.

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

module Ganeti.Queryd

where

import Control.Applicative
import Control.Concurrent
import Control.Exception
import Data.Bits (bitSize)
import Data.Maybe
import qualified Network.Socket as S
import qualified Text.JSON as J
import Text.JSON (showJSON, JSValue(..))
import Text.JSON.Pretty (pp_value)
import System.Info (arch)

import qualified Ganeti.Constants as C
import Ganeti.Objects
import qualified Ganeti.Config as Config
import Ganeti.BasicTypes
import Ganeti.Logging
import Ganeti.Luxi


-- | A type for functions that can return the configuration when
-- executed.
type ConfigReader = IO (Result ConfigData)

-- | Minimal wrapper to handle the missing config case.
handleCallWrapper :: Result ConfigData -> LuxiOp -> IO (Result JSValue)
handleCallWrapper (Bad msg) _ =
  return . Bad $ "I do not have access to a valid configuration, cannot\
                 \ process queries: " ++ msg
handleCallWrapper (Ok config) op = handleCall config op

-- | Actual luxi operation handler.
handleCall :: ConfigData -> LuxiOp -> IO (Result JSValue)
handleCall cdata QueryClusterInfo =
  let cluster = configCluster cdata
      hypervisors = clusterEnabledHypervisors cluster
      bits = show (bitSize (0::Int)) ++ "bits"
      arch_tuple = [bits, arch]
      obj = [ ("software_version", showJSON $ C.releaseVersion)
            , ("protocol_version", showJSON $ C.protocolVersion)
            , ("config_version", showJSON $ C.configVersion)
            , ("os_api_version", showJSON $ maximum C.osApiVersions)
            , ("export_version", showJSON $ C.exportVersion)
            , ("architecture", showJSON $ arch_tuple)
            , ("name", showJSON $ clusterClusterName cluster)
            , ("master", showJSON $ clusterMasterNode cluster)
            , ("default_hypervisor", showJSON $ head hypervisors)
            , ("enabled_hypervisors", showJSON $ hypervisors)
            , ("hvparams", showJSON $ clusterHvparams cluster)
            , ("os_hvp", showJSON $ clusterOsHvp cluster)
            , ("beparams", showJSON $ clusterBeparams cluster)
            , ("osparams", showJSON $ clusterOsparams cluster)
            , ("ipolicy", showJSON $ clusterIpolicy cluster)
            , ("nicparams", showJSON $ clusterNicparams cluster)
            , ("ndparams", showJSON $ clusterNdparams cluster)
            , ("diskparams", showJSON $ clusterDiskparams cluster)
            , ("candidate_pool_size",
               showJSON $ clusterCandidatePoolSize cluster)
            , ("master_netdev",  showJSON $ clusterMasterNetdev cluster)
            , ("master_netmask", showJSON $ clusterMasterNetmask cluster)
            , ("use_external_mip_script",
               showJSON $ clusterUseExternalMipScript cluster)
            , ("volume_group_name", showJSON $clusterVolumeGroupName cluster)
            , ("drbd_usermode_helper",
               maybe JSNull showJSON (clusterDrbdUsermodeHelper cluster))
            , ("file_storage_dir", showJSON $ clusterFileStorageDir cluster)
            , ("shared_file_storage_dir",
               showJSON $ clusterSharedFileStorageDir cluster)
            , ("maintain_node_health",
               showJSON $ clusterMaintainNodeHealth cluster)
            , ("ctime", showJSON $ clusterCtime cluster)
            , ("mtime", showJSON $ clusterMtime cluster)
            , ("uuid", showJSON $ clusterUuid cluster)
            , ("tags", showJSON $ clusterTags cluster)
            , ("uid_pool", showJSON $ clusterUidPool cluster)
            , ("default_iallocator",
               showJSON $ clusterDefaultIallocator cluster)
            , ("reserved_lvs", showJSON $ clusterReservedLvs cluster)
            , ("primary_ip_version",
               showJSON . ipFamilyToVersion $ clusterPrimaryIpFamily cluster)
             , ("prealloc_wipe_disks",
                showJSON $ clusterPreallocWipeDisks cluster)
             , ("hidden_os", showJSON $ clusterHiddenOs cluster)
             , ("blacklisted_os", showJSON $ clusterBlacklistedOs cluster)
            ]

  in return . Ok . J.makeObj $ obj

handleCall cfg (QueryTags kind name) =
  let tags = case kind of
               TagCluster -> Ok . clusterTags $ configCluster cfg
               TagGroup -> groupTags <$> Config.getGroup cfg name
               TagNode -> nodeTags <$> Config.getNode cfg name
               TagInstance -> instTags <$> Config.getInstance cfg name
  in return (J.showJSON <$> tags)

handleCall _ op =
  return . Bad $ "Luxi call '" ++ strOfOp op ++ "' not implemented"


-- | Given a decoded luxi request, executes it and sends the luxi
-- response back to the client.
handleClientMsg :: Client -> ConfigReader -> LuxiOp -> IO Bool
handleClientMsg client creader args = do
  cfg <- creader
  logDebug $ "Request: " ++ show args
  call_result <- handleCallWrapper cfg args
  (!status, !rval) <-
    case call_result of
      Bad x -> do
        logWarning $ "Failed to execute request: " ++ x
        return (False, JSString $ J.toJSString x)
      Ok result -> do
        logDebug $ "Result " ++ show (pp_value result)
        return (True, result)
  sendMsg client $ buildResponse status rval
  return True

-- | Handles one iteration of the client protocol: receives message,
-- checks for validity and decods, returns response.
handleClient :: Client -> ConfigReader -> IO Bool
handleClient client creader = do
  !msg <- recvMsgExt client
  case msg of
    RecvConnClosed -> logDebug "Connection closed" >> return False
    RecvError err -> logWarning ("Error during message receiving: " ++ err) >>
                     return False
    RecvOk payload ->
      case validateCall payload >>= decodeCall of
        Bad err -> logWarning ("Failed to parse request: " ++ err) >>
                   return False
        Ok args -> handleClientMsg client creader args

-- | Main client loop: runs one loop of 'handleClient', and if that
-- doesn't repot a finished (closed) connection, restarts itself.
clientLoop :: Client -> ConfigReader -> IO ()
clientLoop client creader = do
  result <- handleClient client creader
  if result
    then clientLoop client creader
    else closeClient client

-- | Main loop: accepts clients, forks an I/O thread to handle that
-- client, and then restarts.
mainLoop :: ConfigReader -> S.Socket -> IO ()
mainLoop creader socket = do
  client <- acceptClient socket
  _ <- forkIO $ clientLoop client creader
  mainLoop creader socket

-- | Main function that runs the query endpoint. This should be the
-- only one exposed from this module.
runQueryD :: Maybe FilePath -> ConfigReader -> IO ()
runQueryD fpath creader = do
  let socket_path = fromMaybe C.querySocket fpath
  bracket
    (getServer socket_path)
    (closeServer socket_path)
    (mainLoop creader)

{-# LANGUAGE BangPatterns #-}

{-| Implementation of the Ganeti Query2 server.

-}

{-

Copyright (C) 2012, 2013 Google Inc.

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

module Ganeti.Query.Server
  ( main
  , checkMain
  , prepMain
  ) where

import Control.Applicative
import Control.Concurrent
import Control.Exception
import Control.Monad (forever, when, zipWithM)
import Data.Bits (bitSize)
import qualified Data.Set as Set (toList)
import Data.IORef
import qualified Network.Socket as S
import qualified Text.JSON as J
import Text.JSON (showJSON, JSValue(..))
import System.Info (arch)

import qualified Ganeti.Constants as C
import qualified Ganeti.ConstantUtils as ConstantUtils (unFrozenSet)
import Ganeti.Errors
import qualified Ganeti.Path as Path
import Ganeti.Daemon
import Ganeti.Objects
import qualified Ganeti.Config as Config
import Ganeti.ConfigReader
import Ganeti.BasicTypes
import Ganeti.JQueue
import Ganeti.Logging
import Ganeti.Luxi
import qualified Ganeti.Query.Language as Qlang
import qualified Ganeti.Query.Cluster as QCluster
import Ganeti.Path (queueDir, jobQueueLockFile, defaultLuxiSocket)
import Ganeti.Query.Query
import Ganeti.Query.Filter (makeSimpleFilter)
import Ganeti.Types
import Ganeti.Utils (lockFile, exitIfBad)

-- | Helper for classic queries.
handleClassicQuery :: ConfigData      -- ^ Cluster config
                   -> Qlang.ItemType  -- ^ Query type
                   -> [Either String Integer] -- ^ Requested names
                                              -- (empty means all)
                   -> [String]        -- ^ Requested fields
                   -> Bool            -- ^ Whether to do sync queries or not
                   -> IO (GenericResult GanetiException JSValue)
handleClassicQuery _ _ _ _ True =
  return . Bad $ OpPrereqError "Sync queries are not allowed" ECodeInval
handleClassicQuery cfg qkind names fields _ = do
  let flt = makeSimpleFilter (nameField qkind) names
  qr <- query cfg True (Qlang.Query qkind fields flt)
  return $ showJSON <$> (qr >>= queryCompat)

-- | Minimal wrapper to handle the missing config case.
handleCallWrapper :: MVar () -> Result ConfigData 
                     -> LuxiOp -> IO (ErrorResult JSValue)
handleCallWrapper _ (Bad msg) _ =
  return . Bad . ConfigurationError $
           "I do not have access to a valid configuration, cannot\
           \ process queries: " ++ msg
handleCallWrapper qlock (Ok config) op = handleCall qlock config op

-- | Actual luxi operation handler.
handleCall :: MVar () -> ConfigData -> LuxiOp -> IO (ErrorResult JSValue)
handleCall _ cdata QueryClusterInfo =
  let cluster = configCluster cdata
      master = QCluster.clusterMasterNodeName cdata
      hypervisors = clusterEnabledHypervisors cluster
      diskTemplates = clusterEnabledDiskTemplates cluster
      def_hv = case hypervisors of
                 x:_ -> showJSON x
                 [] -> JSNull
      bits = show (bitSize (0::Int)) ++ "bits"
      arch_tuple = [bits, arch]
      obj = [ ("software_version", showJSON C.releaseVersion)
            , ("protocol_version", showJSON C.protocolVersion)
            , ("config_version", showJSON C.configVersion)
            , ("os_api_version", showJSON . maximum .
                                 Set.toList . ConstantUtils.unFrozenSet $
                                 C.osApiVersions)
            , ("export_version", showJSON C.exportVersion)
            , ("vcs_version", showJSON C.vcsVersion)
            , ("architecture", showJSON arch_tuple)
            , ("name", showJSON $ clusterClusterName cluster)
            , ("master", showJSON (case master of
                                     Ok name -> name
                                     _ -> undefined))
            , ("default_hypervisor", def_hv)
            , ("enabled_hypervisors", showJSON hypervisors)
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
            , ("volume_group_name",
               maybe JSNull showJSON (clusterVolumeGroupName cluster))
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
            , ("enabled_disk_templates", showJSON diskTemplates)
            ]

  in case master of
    Ok _ -> return . Ok . J.makeObj $ obj
    Bad ex -> return $ Bad ex

handleCall _ cfg (QueryTags kind name) = do
  let tags = case kind of
               TagKindCluster  -> Ok . clusterTags $ configCluster cfg
               TagKindGroup    -> groupTags <$> Config.getGroup    cfg name
               TagKindNode     -> nodeTags  <$> Config.getNode     cfg name
               TagKindInstance -> instTags  <$> Config.getInstance cfg name
               TagKindNetwork  -> Bad $ OpPrereqError
                                        "Network tag is not allowed"
                                        ECodeInval
  return (J.showJSON <$> tags)

handleCall _ cfg (Query qkind qfields qfilter) = do
  result <- query cfg True (Qlang.Query qkind qfields qfilter)
  return $ J.showJSON <$> result

handleCall _ _ (QueryFields qkind qfields) = do
  let result = queryFields (Qlang.QueryFields qkind qfields)
  return $ J.showJSON <$> result

handleCall _ cfg (QueryNodes names fields lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRNode)
    (map Left names) fields lock

handleCall _ cfg (QueryGroups names fields lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRGroup)
    (map Left names) fields lock

handleCall _ cfg (QueryJobs names fields) =
  handleClassicQuery cfg (Qlang.ItemTypeLuxi Qlang.QRJob)
    (map (Right . fromIntegral . fromJobId) names)  fields False

handleCall _ cfg (QueryNetworks names fields lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRNetwork)
    (map Left names) fields lock

handleCall qlock cfg (SubmitJobToDrainedQueue ops) =
  do
    jobid <- allocateJobId (Config.getMasterCandidates cfg) qlock
    case jobid of
      Bad s -> return . Bad . GenericError $ s
      Ok jid -> do
        qDir <- queueDir
        job <- queuedJobFromOpCodes jid ops
        write_result <- writeJobToDisk qDir job
        case write_result of
          Bad s -> return . Bad . GenericError $ s
          Ok () -> do
            socketpath <- defaultLuxiSocket
            client <- getClient socketpath
            pickupResult <- callMethod (PickupJob jid) client
            closeClient client
            case pickupResult of
              Ok _ -> return ()
              Bad e -> logWarning $ "Failded to notify masterd: " ++ show e
            return . Ok . showJSON . fromJobId $ jid

handleCall qlock cfg (SubmitJob ops) =
  do
    open <- isQueueOpen
    if not open
       then return . Bad . GenericError $ "Queue drained"
       else handleCall qlock cfg (SubmitJobToDrainedQueue ops)

handleCall qlock cfg (SubmitManyJobs lops) =
  do
    open <- isQueueOpen
    if not open
      then return . Bad . GenericError $ "Queue drained"
      else do
        result_jobids <- allocateJobIds (Config.getMasterCandidates cfg)
                           qlock (length lops)
        case result_jobids of
          Bad s -> return . Bad . GenericError $ s
          Ok jids -> do
            jobs <- zipWithM queuedJobFromOpCodes jids lops
            qDir <- queueDir
            write_results <- mapM (writeJobToDisk qDir) jobs
            let annotated_results = zip write_results jids
                succeeded = map snd $ filter (isOk . fst) annotated_results
            when (any isBad write_results) . logWarning
              $ "Writing some jobs failed " ++ show annotated_results
            socketpath <- defaultLuxiSocket
            client <- getClient socketpath
            pickupResults <- mapM (flip callMethod client . PickupJob)
                               succeeded
            closeClient client
            when (any isBad pickupResults)
              . logWarning . (++)  "Failed to notify maserd: " . show
              $ zip succeeded pickupResults
            return . Ok . JSArray
              . map (\(res, jid) ->
                      if isOk res
                        then showJSON (True, fromJobId jid)
                        else showJSON (False, genericResult id (const "") res))
              $ annotated_results
    
handleCall _ _ op =
  return . Bad $
    GenericError ("Luxi call '" ++ strOfOp op ++ "' not implemented")

-- | Given a decoded luxi request, executes it and sends the luxi
-- response back to the client.
handleClientMsg :: MVar () -> Client -> ConfigReader -> LuxiOp -> IO Bool
handleClientMsg qlock client creader args = do
  cfg <- creader
  logDebug $ "Request: " ++ show args
  call_result <- handleCallWrapper qlock cfg args
  (!status, !rval) <-
    case call_result of
      Bad err -> do
        logWarning $ "Failed to execute request " ++ show args ++ ": "
                     ++ show err
        return (False, showJSON err)
      Ok result -> do
        -- only log the first 2,000 chars of the result
        logDebug $ "Result (truncated): " ++ take 2000 (J.encode result)
        logInfo $ "Successfully handled " ++ strOfOp args
        return (True, result)
  sendMsg client $ buildResponse status rval
  return True

-- | Handles one iteration of the client protocol: receives message,
-- checks it for validity and decodes it, returns response.
handleClient :: MVar () -> Client -> ConfigReader -> IO Bool
handleClient qlock client creader = do
  !msg <- recvMsgExt client
  logDebug $ "Received message: " ++ show msg
  case msg of
    RecvConnClosed -> logDebug "Connection closed" >> return False
    RecvError err -> logWarning ("Error during message receiving: " ++ err) >>
                     return False
    RecvOk payload ->
      case validateCall payload >>= decodeCall of
        Bad err -> do
             let errmsg = "Failed to parse request: " ++ err
             logWarning errmsg
             sendMsg client $ buildResponse False (showJSON errmsg)
             return False
        Ok args -> handleClientMsg qlock client creader args

-- | Main client loop: runs one loop of 'handleClient', and if that
-- doesn't report a finished (closed) connection, restarts itself.
clientLoop :: MVar () -> Client -> ConfigReader -> IO ()
clientLoop qlock client creader = do
  result <- handleClient qlock client creader
  if result
    then clientLoop qlock client creader
    else closeClient client

-- | Main listener loop: accepts clients, forks an I/O thread to handle
-- that client.
listener :: MVar () -> ConfigReader -> S.Socket -> IO ()
listener qlock creader socket = do
  client <- acceptClient socket
  _ <- forkIO $ clientLoop qlock client creader
  return ()

-- | Type alias for prepMain results
type PrepResult = (FilePath, S.Socket, IORef (Result ConfigData))

-- | Check function for luxid.
checkMain :: CheckFn ()
checkMain _ = return $ Right ()

-- | Prepare function for luxid.
prepMain :: PrepFn () PrepResult
prepMain _ _ = do
  socket_path <- Path.defaultQuerySocket
  cleanupSocket socket_path
  s <- describeError "binding to the Luxi socket"
         Nothing (Just socket_path) $ getServer True socket_path
  cref <- newIORef (Bad "Configuration not yet loaded")
  return (socket_path, s, cref)

-- | Main function.
main :: MainFn () PrepResult
main _ _ (socket_path, server, cref) = do
  initConfigReader id cref
  let creader = readIORef cref
  
  qlockFile <- jobQueueLockFile
  lockFile qlockFile >>= exitIfBad "Failed to obtain the job-queue lock"
  qlock <- newMVar ()

  finally
    (forever $ listener qlock creader server)
    (closeServer socket_path server)

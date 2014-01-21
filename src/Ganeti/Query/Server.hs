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
import Control.Monad (forever, when, zipWithM, liftM)
import Data.Bits (bitSize)
import qualified Data.Set as Set (toList)
import Data.IORef
import Data.Maybe (fromMaybe)
import qualified Text.JSON as J
import Text.JSON (encode, showJSON, JSValue(..))
import System.Info (arch)
import System.Directory

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
import Ganeti.JQScheduler
import Ganeti.Logging
import Ganeti.Luxi
import qualified Ganeti.Query.Language as Qlang
import qualified Ganeti.Query.Cluster as QCluster
import Ganeti.Path (queueDir, jobQueueLockFile, jobQueueDrainFile)
import Ganeti.Rpc
import Ganeti.Query.Query
import Ganeti.Query.Filter (makeSimpleFilter)
import Ganeti.Types
import qualified Ganeti.UDSServer as U (Handler(..), listener)
import Ganeti.Utils (lockFile, exitIfBad, watchFile)
import qualified Ganeti.Version as Version

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
handleCallWrapper :: MVar () -> JQStatus ->  Result ConfigData
                     -> LuxiOp -> IO (ErrorResult JSValue)
handleCallWrapper _ _ (Bad msg) _ =
  return . Bad . ConfigurationError $
           "I do not have access to a valid configuration, cannot\
           \ process queries: " ++ msg
handleCallWrapper qlock qstat (Ok config) op = handleCall qlock qstat config op

-- | Actual luxi operation handler.
handleCall :: MVar () -> JQStatus
              -> ConfigData -> LuxiOp -> IO (ErrorResult JSValue)
handleCall _ _ cdata QueryClusterInfo =
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
            , ("vcs_version", showJSON Version.version)
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
            , ("max_running_jobs",
               showJSON $ clusterMaxRunningJobs cluster)
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
            , ("gluster_storage_dir",
               showJSON $ clusterGlusterStorageDir cluster)
            , ("maintain_node_health",
               showJSON $ clusterMaintainNodeHealth cluster)
            , ("ctime", showJSON $ clusterCtime cluster)
            , ("mtime", showJSON $ clusterMtime cluster)
            , ("uuid", showJSON $ clusterUuid cluster)
            , ("tags", showJSON $ clusterTags cluster)
            , ("uid_pool", showJSON $ clusterUidPool cluster)
            , ("default_iallocator",
               showJSON $ clusterDefaultIallocator cluster)
            , ("default_iallocator_params",
              showJSON $ clusterDefaultIallocatorParams cluster)
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

handleCall _ _ cfg (QueryTags kind name) = do
  let tags = case kind of
               TagKindCluster  -> Ok . clusterTags $ configCluster cfg
               TagKindGroup    -> groupTags <$> Config.getGroup    cfg name
               TagKindNode     -> nodeTags  <$> Config.getNode     cfg name
               TagKindInstance -> instTags  <$> Config.getInstance cfg name
               TagKindNetwork  -> Bad $ OpPrereqError
                                        "Network tag is not allowed"
                                        ECodeInval
  return (J.showJSON <$> tags)

handleCall _ _ cfg (Query qkind qfields qfilter) = do
  result <- query cfg True (Qlang.Query qkind qfields qfilter)
  return $ J.showJSON <$> result

handleCall _ _ _ (QueryFields qkind qfields) = do
  let result = queryFields (Qlang.QueryFields qkind qfields)
  return $ J.showJSON <$> result

handleCall _ _ cfg (QueryNodes names fields lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRNode)
    (map Left names) fields lock

handleCall _ _ cfg (QueryInstances names fields lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRInstance)
    (map Left names) fields lock

handleCall _ _ cfg (QueryGroups names fields lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRGroup)
    (map Left names) fields lock

handleCall _ _ cfg (QueryJobs names fields) =
  handleClassicQuery cfg (Qlang.ItemTypeLuxi Qlang.QRJob)
    (map (Right . fromIntegral . fromJobId) names)  fields False

handleCall _ _ cfg (QueryNetworks names fields lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRNetwork)
    (map Left names) fields lock

handleCall _ _ cfg (QueryConfigValues fields) = do
  let params = [ ("cluster_name", return . showJSON . clusterClusterName
                                    . configCluster $ cfg)
               , ("watcher_pause", liftM (maybe JSNull showJSON)
                                     QCluster.isWatcherPaused)
               , ("master_node", return . genericResult (const JSNull) showJSON
                                   $ QCluster.clusterMasterNodeName cfg)
               , ("drain_flag", liftM (showJSON . not) isQueueOpen)
               ] :: [(String, IO JSValue)]
  let answer = map (fromMaybe (return JSNull) . flip lookup params) fields
  answerEval <- sequence answer
  return . Ok . showJSON $ answerEval

handleCall qlock qstat cfg (SubmitJobToDrainedQueue ops) =
  do
    let mcs = Config.getMasterCandidates cfg
    jobid <- allocateJobId mcs qlock
    case jobid of
      Bad s -> return . Bad . GenericError $ s
      Ok jid -> do
        ts <- currentTimestamp
        job <- liftM (setReceivedTimestamp ts)
                 $ queuedJobFromOpCodes jid ops
        qDir <- queueDir
        write_result <- writeJobToDisk qDir job
        case write_result of
          Bad s -> return . Bad . GenericError $ s
          Ok () -> do
            _ <- replicateManyJobs qDir mcs [job]
            _ <- forkIO $ enqueueNewJobs qstat [job]
            return . Ok . showJSON . fromJobId $ jid

handleCall qlock qstat cfg (SubmitJob ops) =
  do
    open <- isQueueOpen
    if not open
       then return . Bad . GenericError $ "Queue drained"
       else handleCall qlock qstat cfg (SubmitJobToDrainedQueue ops)

handleCall qlock qstat cfg (SubmitManyJobs lops) =
  do
    open <- isQueueOpen
    if not open
      then return . Bad . GenericError $ "Queue drained"
      else do
        let mcs = Config.getMasterCandidates cfg
        result_jobids <- allocateJobIds mcs qlock (length lops)
        case result_jobids of
          Bad s -> return . Bad . GenericError $ s
          Ok jids -> do
            ts <- currentTimestamp
            jobs <- liftM (map $ setReceivedTimestamp ts)
                      $ zipWithM queuedJobFromOpCodes jids lops
            qDir <- queueDir
            write_results <- mapM (writeJobToDisk qDir) jobs
            let annotated_results = zip write_results jobs
                succeeded = map snd $ filter (isOk . fst) annotated_results
            when (any isBad write_results) . logWarning
              $ "Writing some jobs failed " ++ show annotated_results
            replicateManyJobs qDir mcs succeeded
            _ <- forkIO $ enqueueNewJobs qstat succeeded
            return . Ok . JSArray
              . map (\(res, job) ->
                      if isOk res
                        then showJSON (True, fromJobId $ qjId job)
                        else showJSON (False, genericResult id (const "") res))
              $ annotated_results

handleCall _ _ cfg (WaitForJobChange jid fields prev_job prev_log tmout) = do
  let compute_fn = computeJobUpdate cfg jid fields prev_log
  qDir <- queueDir
  -- verify if the job is finalized, and return immediately in this case
  jobresult <- loadJobFromDisk qDir False jid
  case jobresult of
    Ok (job, _) | not (jobFinalized job) -> do
      let jobfile = liveJobFile qDir jid
      answer <- watchFile jobfile (min tmout C.luxiWfjcTimeout)
                  (prev_job, JSArray []) compute_fn
      return . Ok $ showJSON answer
    _ -> liftM (Ok . showJSON) compute_fn

handleCall _ _ cfg (SetWatcherPause time) = do
  let mcs = Config.getMasterCandidates cfg
      masters = genericResult (const []) return
                  . Config.getNode cfg . clusterMasterNode
                  $ configCluster cfg
  _ <- executeRpcCall (masters ++ mcs) $ RpcCallSetWatcherPause time
  return . Ok . maybe JSNull showJSON $ time

handleCall _ _ cfg (SetDrainFlag value) = do
  let mcs = Config.getMasterCandidates cfg
  fpath <- jobQueueDrainFile
  if value
     then writeFile fpath ""
     else removeFile fpath
  _ <- executeRpcCall mcs $ RpcCallSetDrainFlag value
  return . Ok . showJSON $ True

handleCall _ qstat  cfg (CancelJob jid) = do
  let jName = (++) "job " . show $ fromJobId jid
  dequeueResult <- dequeueJob qstat jid
  case dequeueResult of
    Ok True -> do
      logDebug $ jName ++ " dequeued, marking as canceled"
      qDir <- queueDir
      readResult <- loadJobFromDisk qDir True jid
      let jobFileFailed = return . Ok . showJSON . (,) False
                            . (++) ("Dequeued " ++ jName
                                    ++ ", but failed to mark as cancelled: ")
                          :: String -> IO (ErrorResult JSValue)
      case readResult of
        Bad s -> jobFileFailed s
        Ok (job, _) -> do
          now <- currentTimestamp
          let job' = cancelQueuedJob now job
              mcs = Config.getMasterCandidates cfg
          write_result <- writeJobToDisk qDir job'
          case write_result of
            Bad s -> jobFileFailed s
            Ok () -> do
              replicateManyJobs qDir mcs [job']
              return . Ok . showJSON $ (True, "Dequeued " ++ jName)
    Ok False -> do
      logDebug $ jName ++ " not queued; trying to cancel directly"
      cancelJob jid
    Bad s -> return . Ok . showJSON $ (False, s)

handleCall qlock _ cfg (ArchiveJob jid) = do
  let archiveFailed = putMVar qlock  () >> (return . Ok $ showJSON False)
                      :: IO (ErrorResult JSValue)
  qDir <- queueDir
  takeMVar qlock
  result <- loadJobFromDisk qDir False jid
  case result of
    Bad _ -> archiveFailed
    Ok (job, _) -> if jobFinalized job
                     then do
                       let mcs = Config.getMasterCandidates cfg
                           live = liveJobFile qDir jid
                           archive = archivedJobFile qDir jid
                       renameResult <- try $ renameFile live archive
                                       :: IO (Either IOError ())
                       putMVar qlock ()
                       case renameResult of
                         Left e -> return . Bad . JobQueueError
                                     $ "Archiving failed in an unexpected way: "
                                         ++ show e
                         Right () -> do
                           _ <- executeRpcCall mcs
                                  $ RpcCallJobqueueRename [(live, archive)]
                          return . Ok $ showJSON True
                     else archiveFailed

handleCall _ _ _ op =
  return . Bad $
    GenericError ("Luxi call '" ++ strOfOp op ++ "' not implemented")

{-# ANN handleCall "HLint: ignore Too strict if" #-}

-- | Query the status of a job and return the requested fields
-- and the logs newer than the given log number.
computeJobUpdate :: ConfigData -> JobId -> [String] -> JSValue
                    -> IO (JSValue, JSValue)
computeJobUpdate cfg jid fields prev_log = do
  let sjid = show $ fromJobId jid
  logDebug $ "Inspecting fields " ++ show fields ++ " of job " ++ sjid
  let fromJSArray (JSArray xs) = xs
      fromJSArray _ = []
  let logFilter JSNull (JSArray _) = True
      logFilter (JSRational _ n) (JSArray (JSRational _ m:_)) = n < m
      logFilter _ _ = False
  let filterLogs n logs = JSArray (filter (logFilter n) (logs >>= fromJSArray))
  jobQuery <- handleClassicQuery cfg (Qlang.ItemTypeLuxi Qlang.QRJob)
                [Right . fromIntegral $ fromJobId jid] ("oplog" : fields) False
  let (rfields, rlogs) = case jobQuery of
        Ok (JSArray [JSArray (JSArray logs : answer)]) ->
          (answer, filterLogs prev_log logs)
        _ -> (map (const JSNull) fields, JSArray [])
  logDebug $ "Updates for job " ++ sjid ++ " are " ++ encode (rfields, rlogs)
  return (JSArray rfields, rlogs)


type LuxiConfig = (MVar (), JQStatus, ConfigReader)

luxiExec
    :: LuxiConfig
    -> LuxiOp
    -> IO (Bool, GenericResult GanetiException JSValue)
luxiExec (qlock, qstat, creader) args = do
  cfg <- creader
  result <- handleCallWrapper qlock qstat cfg args
  return (True, result)

luxiHandler :: LuxiConfig -> U.Handler LuxiOp JSValue
luxiHandler cfg = U.Handler { U.hParse         = decodeLuxiCall
                            , U.hInputLogShort = strOfOp
                            , U.hInputLogLong  = show
                            , U.hExec          = luxiExec cfg
                            }

-- | Type alias for prepMain results
type PrepResult = (Server, IORef (Result ConfigData), JQStatus)

-- | Check function for luxid.
checkMain :: CheckFn ()
checkMain _ = return $ Right ()

-- | Prepare function for luxid.
prepMain :: PrepFn () PrepResult
prepMain _ _ = do
  socket_path <- Path.defaultQuerySocket
  cleanupSocket socket_path
  s <- describeError "binding to the Luxi socket"
         Nothing (Just socket_path) $ getLuxiServer True socket_path
  cref <- newIORef (Bad "Configuration not yet loaded")
  jq <- emptyJQStatus cref
  return (s, cref, jq)

-- | Main function.
main :: MainFn () PrepResult
main _ _ (server, cref, jq) = do
  initConfigReader id cref
  let creader = readIORef cref
  initJQScheduler jq

  qlockFile <- jobQueueLockFile
  lockFile qlockFile >>= exitIfBad "Failed to obtain the job-queue lock"
  qlock <- newMVar ()

  finally
    (forever $ U.listener (luxiHandler (qlock, jq, creader)) server)
    (closeServer server)

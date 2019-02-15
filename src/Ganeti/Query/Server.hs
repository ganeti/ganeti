{-# LANGUAGE FlexibleContexts #-}

{-| Implementation of the Ganeti Query2 server.

-}

{-

Copyright (C) 2012, 2013, 2014 Google Inc.
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

module Ganeti.Query.Server
  ( main
  , checkMain
  , prepMain
  ) where

import Control.Applicative
import Control.Concurrent
import Control.Exception
import Control.Lens ((.~))
import Control.Monad (forever, when, mzero, guard, zipWithM, liftM, void)
import Control.Monad.Base (MonadBase, liftBase)
import Control.Monad.Error (MonadError)
import Control.Monad.IO.Class
import Control.Monad.Trans (lift)
import Control.Monad.Trans.Maybe
import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.Set as Set (toList)
import Data.IORef
import Data.List (intersperse)
import Data.Maybe (fromMaybe)
import qualified Text.JSON as J
import Text.JSON (encode, showJSON, JSValue(..))
import System.Info (arch)
import System.Directory
import System.Posix.Process (getProcessID)
import System.Posix.Signals as P

import qualified Ganeti.Constants as C
import qualified Ganeti.ConstantUtils as ConstantUtils (unFrozenSet)
import Ganeti.Errors
import qualified Ganeti.Path as Path
import Ganeti.Daemon
import Ganeti.Daemon.Utils (handleMasterVerificationOptions)
import Ganeti.Objects
import Ganeti.Objects.Lens (configFiltersL)
import qualified Ganeti.Config as Config
import qualified Ganeti.Compat as Compat
import Ganeti.ConfigReader
import Ganeti.BasicTypes
import Ganeti.JQueue
import Ganeti.JQScheduler
import Ganeti.JSON (TimeAsDoubleJSON(..), alterContainerL, lookupContainer)
import Ganeti.Locking.Locks (ClientId(..), ClientType(ClientOther))
import Ganeti.Logging
import Ganeti.Luxi
import qualified Ganeti.Query.Language as Qlang
import qualified Ganeti.Query.Cluster as QCluster
import Ganeti.Path ( queueDir, jobQueueLockFile, jobQueueDrainFile )
import Ganeti.Rpc
import qualified Ganeti.Query.Exec as Exec
import Ganeti.Query.Query
import Ganeti.Query.Filter (makeSimpleFilter)
import Ganeti.THH.HsRPC (runRpcClient, RpcClientMonad)
import Ganeti.Types
import qualified Ganeti.UDSServer as U (Handler(..), listener)
import Ganeti.Utils ( lockFile, exitIfBad, exitUnless, watchFile
                    , safeRenameFile, newUUID, isUUID )
import Ganeti.Utils.Monad (orM)
import Ganeti.Utils.MVarLock
import qualified Ganeti.Version as Version
import Ganeti.WConfd.Client ( getWConfdClient, withLockedConfig, writeConfig
                            , cleanupLocks)


-- | Creates a `ClientId` that identifies the current luxi
-- (process, thread).
--
-- This means that this `ClientId` will be different for each request
-- handled by luxid.
makeLuxidClientId :: JQStatus -> IO ClientId
makeLuxidClientId status = do
  pid <- getProcessID
  tid <- myThreadId
  return ClientId
           { ciIdentifier = ClientOther $ "luxid-" ++ show tid
           , ciLockFile = jqLivelock status
           , ciPid = pid
           }

-- | Creates a connection to WConfd and locks the config, allowing
-- to run some WConfd RPC commands given the locked config.
--
-- This is needed when luxid wants to change the config.
--
-- Example:
--
-- > cid <- makeLuxidClientId ...
-- > withLockedWconfdConfig cid $ \lockedCfg -> do
-- >   -- some (IO) action that needs to be run inside having the lock
-- >   writeConfig cid (updateConfig lockedCfg)
withLockedWconfdConfig
  :: (MonadBase IO m, MonadError GanetiException m)
  => ClientId
  -> (ConfigData -> RpcClientMonad a)
  -> m a
withLockedWconfdConfig cid f = do
  wconfdClient <- liftBase $ getWConfdClient =<< Path.defaultWConfdSocket
  runRpcClient (withLockedConfig cid False f) wconfdClient

-- | Helper for classic queries.
handleQuery :: [Qlang.ItemType -> Qlang.FilterField] -- ^ Fields to put into
                                                     -- the query
            -> ConfigData      -- ^ Cluster config
            -> Qlang.ItemType  -- ^ Query type
            -> [Either String Integer] -- ^ Requested names
                                       -- (empty means all)
            -> [String]        -- ^ Requested fields
            -> Bool            -- ^ Whether to do sync queries or not
            -> IO (GenericResult GanetiException JSValue)
handleQuery _ _ _ _ _ True =
  return . Bad $ OpPrereqError "Sync queries are not allowed" ECodeInval
handleQuery filterFields cfg qkind names fields _ = do
  let simpleNameFilter field = makeSimpleFilter (field qkind) names
      flt = Qlang.OrFilter $ map simpleNameFilter filterFields
  qr <- query cfg True (Qlang.Query qkind fields flt)
  return $ showJSON <$> (qr >>= queryCompat)

-- | Helper for classic queries.
-- Queries `name` and `uuid` fields.
handleClassicQuery :: ConfigData      -- ^ Cluster config
                   -> Qlang.ItemType  -- ^ Query type
                   -> [Either String Integer] -- ^ Requested names
                                              -- (empty means all)
                   -> [String]        -- ^ Requested fields
                   -> Bool            -- ^ Whether to do sync queries or not
                   -> IO (GenericResult GanetiException JSValue)
handleClassicQuery = handleQuery [nameField, uuidField]

-- | Like `handleClassicQuery`, but filters only by UUID.
handleUuidQuery :: ConfigData      -- ^ Cluster config
                -> Qlang.ItemType  -- ^ Query type
                -> [Either String Integer] -- ^ Requested names
                                           -- (empty means all)
                -> [String]        -- ^ Requested fields
                -> Bool            -- ^ Whether to do sync queries or not
                -> IO (GenericResult GanetiException JSValue)
handleUuidQuery = handleQuery [uuidField]

-- | Minimal wrapper to handle the missing config case.
handleCallWrapper :: Lock -> JQStatus ->  Result ConfigData
                     -> LuxiOp -> IO (ErrorResult JSValue)
handleCallWrapper _ _ (Bad msg) _ =
  return . Bad . ConfigurationError $
           "I do not have access to a valid configuration, cannot\
           \ process queries: " ++ msg
handleCallWrapper qlock qstat (Ok config) op = handleCall qlock qstat config op

-- | Actual luxi operation handler.
handleCall :: Lock -> JQStatus
              -> ConfigData -> LuxiOp -> IO (ErrorResult JSValue)
handleCall _ _ cdata QueryClusterInfo =
  let cluster = configCluster cdata
      master = QCluster.clusterMasterNodeName cdata
      hypervisors = clusterEnabledHypervisors cluster
      diskTemplates = clusterEnabledDiskTemplates cluster
      def_hv = case hypervisors of
                 x:_ -> showJSON x
                 [] -> JSNull
      bits = show (Compat.finiteBitSize (0::Int)) ++ "bits"
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
            , ("max_tracked_jobs",
               showJSON $ clusterMaxTrackedJobs cluster)
            , ("mac_prefix",  showJSON $ clusterMacPrefix cluster)
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
            , ("ctime", showJSON . TimeAsDoubleJSON $ clusterCtime cluster)
            , ("mtime", showJSON . TimeAsDoubleJSON $ clusterMtime cluster)
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
            , ("install_image", showJSON $ clusterInstallImage cluster)
            , ("instance_communication_network",
               showJSON (clusterInstanceCommunicationNetwork cluster))
            , ("zeroing_image", showJSON $ clusterZeroingImage cluster)
            , ("compression_tools",
               showJSON $ clusterCompressionTools cluster)
            , ("enabled_user_shutdown",
               showJSON $ clusterEnabledUserShutdown cluster)
            , ("enabled_data_collectors",
               showJSON . fmap dataCollectorActive
                        $ clusterDataCollectors cluster)
            , ("data_collector_interval",
               showJSON . fmap dataCollectorInterval
                        $ clusterDataCollectors cluster)
            , ("modify_ssh_setup",
               showJSON $ clusterModifySshSetup cluster)
            , ("ssh_key_type", showJSON $ clusterSshKeyType cluster)
            , ("ssh_key_bits", showJSON $ clusterSshKeyBits cluster)
            ]

  in case master of
    Ok _ -> return . Ok . J.makeObj $ obj
    Bad ex -> return $ Bad ex

handleCall _ _ cfg (QueryTags kind name) = do
  let tags = case kind of
               TagKindCluster  -> Ok . clusterTags $ configCluster cfg
               TagKindGroup    -> groupTags   <$> Config.getGroup    cfg name
               TagKindNode     -> nodeTags    <$> Config.getNode     cfg name
               TagKindInstance -> instTags    <$> Config.getInstance cfg name
               TagKindNetwork  -> networkTags <$> Config.getNetwork  cfg name
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

handleCall _ _ cfg (QueryFilters uuids fields) =
  handleUuidQuery cfg (Qlang.ItemTypeLuxi Qlang.QRFilter)
    (map Left uuids) fields False

handleCall _ status _ (ReplaceFilter mUuid priority predicates action
                                     reason) =
  -- Handles both adding new filter and changing existing ones.
  runResultT $ do

    -- Check that uuid `String` is actually a UUID.
    uuid <- case mUuid of
      Nothing -> liftIO newUUID  -- Request to add a new filter
      Just u                     -- Request to edit an existing filter
        | isUUID u  -> return u
        | otherwise -> fail "Unable to parse UUID"

    timestamp <- liftIO $ reasonTrailTimestamp <$> currentTimestamp
    let luxidReason = ("luxid", "", timestamp)

    -- Ask WConfd to change the config for us.
    cid <- liftIO $ makeLuxidClientId status
    withLockedWconfdConfig cid $ \lockedCfg -> do
      -- Reading the latest JobID inside the Wconfd lock to really get the
      -- most recent one (locking may block us for some time).
      serial <- liftIO readSerialFromDisk
      case serial of
        Bad err -> fail $ "AddFilter: reading current JobId failed: " ++ err
        Ok watermark -> do
          let rule = FilterRule { frWatermark = watermark
                                , frPriority = priority
                                , frPredicates = predicates
                                , frAction = action
                                , frReasonTrail = reason ++ [luxidReason]
                                , frUuid = UTF8.fromString uuid
                                }
          writeConfig cid
            . (configFiltersL . alterContainerL (UTF8.fromString uuid)
                 .~ Just rule)
            $ lockedCfg

    -- Return UUID of added/replaced filter.
    return $ showJSON uuid

handleCall _ status cfg (DeleteFilter uuid) = runResultT $ do
  -- Check if filter exists.
  _ <- lookupContainer
    (failError $ "Filter rule with UUID " ++ uuid ++ " does not exist")
    (UTF8.fromString uuid)
    (configFilters cfg)

  -- Ask WConfd to change the config for us.
  cid <- liftIO $ makeLuxidClientId status
  withLockedWconfdConfig cid $ \lockedCfg ->
    writeConfig cid
      . (configFiltersL . alterContainerL (UTF8.fromString uuid) .~ Nothing)
      $ lockedCfg

  return JSNull

handleCall _ _ cfg (QueryNetworks names fields lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRNetwork)
    (map Left names) fields lock

handleCall _ _ cfg (QueryConfigValues fields) = do
  let clusterProperty fn = showJSON . fn . configCluster $ cfg
  let params = [ ("cluster_name", return $ clusterProperty clusterClusterName)
               , ("watcher_pause", liftM (maybe JSNull showJSON)
                                     QCluster.isWatcherPaused)
               , ("master_node", return . genericResult (const JSNull) showJSON
                                   $ QCluster.clusterMasterNodeName cfg)
               , ("drain_flag", liftM (showJSON . not) isQueueOpen)
               , ("modify_ssh_setup",
                  return $ clusterProperty clusterModifySshSetup)
               , ("ssh_key_type", return $ clusterProperty clusterSshKeyType)
               , ("ssh_key_bits", return $ clusterProperty clusterSshKeyBits)
               ] :: [(String, IO JSValue)]
  let answer = map (fromMaybe (return JSNull) . flip lookup params) fields
  answerEval <- sequence answer
  return . Ok . showJSON $ answerEval

handleCall _ _ cfg (QueryExports nodes lock) =
  handleClassicQuery cfg (Qlang.ItemTypeOpCode Qlang.QRExport)
    (map Left nodes) ["node", "export"] lock

handleCall qlock qstat cfg (SubmitJobToDrainedQueue ops) = runResultT $ do
    jid <- mkResultT $ allocateJobId (Config.getMasterCandidates cfg) qlock
    ts <- liftIO currentTimestamp
    job <- liftM (extendJobReasonTrail . setReceivedTimestamp ts)
             $ queuedJobFromOpCodes jid ops
    qDir <- liftIO queueDir
    _ <- writeAndReplicateJob cfg qDir job
    _ <- liftIO . forkIO $ enqueueNewJobs qstat [job]
    return . showJSON . fromJobId $ jid

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
            jobs <- liftM (map $ extendJobReasonTrail . setReceivedTimestamp ts)
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

handleCall _ _ cfg (WaitForJobChange jid fields prev_job prev_log tmout) =
  waitForJobChange jid prev_job tmout $ computeJobUpdate cfg jid fields prev_log

handleCall _ _ cfg (SetWatcherPause time) = do
  let mcs = Config.getMasterOrCandidates cfg
  _ <- executeRpcCall mcs $ RpcCallSetWatcherPause time
  return . Ok . maybe JSNull showJSON $ fmap TimeAsDoubleJSON time

handleCall _ _ cfg (SetDrainFlag value) = do
  let mcs = Config.getMasterCandidates cfg
  fpath <- jobQueueDrainFile
  if value
     then writeFile fpath ""
     else removeFile fpath
  _ <- executeRpcCall mcs $ RpcCallSetDrainFlag value
  return . Ok . showJSON $ True

handleCall _ qstat cfg (ChangeJobPriority jid prio) = do
  let jName = (++) "job " . show $ fromJobId jid
  maybeJob <- setJobPriority qstat jid prio
  case maybeJob of
    Bad s -> return . Ok $ showJSON (False, s)
    Ok (Just job) -> runResultT $ do
      let mcs = Config.getMasterCandidates cfg
      qDir <- liftIO queueDir
      liftIO $ replicateManyJobs qDir mcs [job]
      return $ showJSON (True, "Priorities of pending opcodes for "
                               ++ jName ++ " have been changed"
                               ++ " to " ++ show prio)
    Ok Nothing -> do
      logDebug $ jName ++ " started, will signal"
      fmap showJSON <$> tellJobPriority (jqLivelock qstat) jid prio

handleCall _ qstat  cfg (CancelJob jid kill) = do
  let jName = (++) "job " . show $ fromJobId jid
  dequeueResult <- dequeueJob qstat jid
  case dequeueResult of
    Ok True ->
      let jobFileFailed = (,) False
                          . (++) ("Dequeued " ++ jName
                                  ++ ", but failed to mark as cancelled: ")
          jobFileSucceeded _ = (True, "Dequeued " ++ jName)
      in liftM (Ok . showJSON . genericResult jobFileFailed jobFileSucceeded)
         . runResultT $ do
            logDebug $ jName ++ " dequeued, marking as canceled"
            qDir <- liftIO queueDir
            (job, _) <- ResultT $ loadJobFromDisk qDir True jid
            now <- liftIO currentTimestamp
            let job' = cancelQueuedJob now job
            writeAndReplicateJob cfg qDir job'
    Ok False -> do
      logDebug $ jName ++ " not queued; trying to cancel directly"
      result <- fmap showJSON <$> cancelJob kill (jqLivelock qstat) jid
      when kill . void . forkIO $ do
        _ <- orM
             . intersperse (threadDelay C.luxidJobDeathDelay >> return False)
             . replicate C.luxidJobDeathDetectionRetries
             $ cleanupIfDead qstat jid
        wconfdsocket <- Path.defaultWConfdSocket
        wconfdclient <- getWConfdClient wconfdsocket
        void . runResultT $ runRpcClient cleanupLocks wconfdclient
      return result
    Bad s -> return . Ok . showJSON $ (False, s)

handleCall qlock _ cfg (ArchiveJob jid) =
  -- By adding a layer of MaybeT, we can prematurely end a computation
  -- using 'mzero' or other 'MonadPlus' primitive and return 'Ok False'.
  runResultT . liftM (showJSON . fromMaybe False) . runMaybeT $ do
    qDir <- liftIO queueDir
    let mcs = Config.getMasterCandidates cfg
        live = liveJobFile qDir jid
        archive = archivedJobFile qDir jid
    withLock qlock $ do
      (job, _) <- (lift . mkResultT $ loadJobFromDisk qDir False jid)
                  `orElse` mzero
      guard $ jobFinalized job
      lift . withErrorT JobQueueError
           . annotateError "Archiving failed in an unexpected way"
           . mkResultT $ safeRenameFile queueDirPermissions live archive
    _ <- liftIO . executeRpcCall mcs
                $ RpcCallJobqueueRename [(live, archive)]
    return True

handleCall qlock _ cfg (AutoArchiveJobs age timeout) = do
  qDir <- queueDir
  resultJids <- getJobIDs [qDir]
  case resultJids of
    Bad s -> return . Bad . JobQueueError $ show s
    Ok jids -> do
      result <- withLock qlock
                  . archiveJobs cfg age timeout
                  $ sortJobIDs jids
      return . Ok $ showJSON result

handleCall _ _ _ (PickupJob _) =
  return . Bad
    $ GenericError "Luxi call 'PickupJob' is for internal use only"

{-# ANN handleCall "HLint: ignore Too strict if" #-}

-- | Special-case handler for WaitForJobChange RPC call for fields == ["status"]
-- that doesn't require the use of ConfigData
handleWaitForJobChangeStatus :: JobId -> JSValue -> JSValue -> Int
                                -> IO (ErrorResult JSValue)
handleWaitForJobChangeStatus jid prev_job prev_log tmout =
  waitForJobChange jid prev_job tmout $ computeJobUpdateStatus jid prev_log

-- | Common WaitForJobChange functionality shared between handleCall and
-- handleWaitForJobChangeStatus
waitForJobChange :: JobId -> JSValue -> Int -> IO (JSValue, JSValue)
                          -> IO (ErrorResult JSValue)
waitForJobChange jid prev_job tmout compute_fn = do
  qDir <- queueDir
  -- verify if the job is finalized, and return immediately in this case
  jobresult <- loadJobFromDisk qDir False jid
  case jobresult of
    Bad s -> return . Bad $ JobLost s
    Ok (job, _) | not (jobFinalized job) -> do
      let jobfile = liveJobFile qDir jid
      answer <- watchFile jobfile (min tmout C.luxiWfjcTimeout)
                  (prev_job, JSArray []) compute_fn
      return . Ok $ showJSON answer
    _ -> liftM (Ok . showJSON) compute_fn

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

-- | A version of computeJobUpdate hardcoded to only return logs and the status
-- field. By hardcoding this we avoid using the luxi Query infrastructure and
-- the ConfigData value it requires.
computeJobUpdateStatus :: JobId -> JSValue -> IO (JSValue, JSValue)
computeJobUpdateStatus jid prev_log = do
  qdir <- queueDir
  loadResult <- loadJobFromDisk qdir True jid
  let sjid = show $ fromJobId jid
  logDebug $ "Inspecting status of job " ++ sjid
  let (rfields, rlogs) = case loadResult of
       Ok (job, _) -> (J.JSArray [status], newlogs)
          where status  = showJSON $ calcJobStatus job -- like "status" jobField
                oplogs  = map qoLog (qjOps job)        -- like "oplog" jobField
                newer   = case J.readJSON prev_log of
                  J.Ok n -> (\(idx, _time, _type, _msg) -> n < idx)
                  _      -> const True
                newlogs = showJSON $ concatMap (filter newer) oplogs
       _ -> (JSArray[JSNull], JSArray [])
  logDebug $ "Updates for job " ++ sjid ++ " are " ++ encode (rfields, rlogs)
  return (rfields, rlogs)

type LuxiConfig = (Lock, JQStatus, ConfigReader)

luxiExec
    :: LuxiConfig
    -> LuxiOp
    -> IO (Bool, GenericResult GanetiException JSValue)
luxiExec (qlock, qstat, creader) args =
  case args of
    -- Special case WaitForJobChange handling to avoid passing a ConfigData to
    -- a potentially long-lived thread. ConfigData uses lots of heap, and
    -- multiple handler threads retaining different versions of ConfigData
    -- increases luxi's memory use for concurrent jobs that modify config.
    WaitForJobChange jid fields prev_job prev_log tmout
      | fields == ["status"] -> do
        result <- handleWaitForJobChangeStatus jid prev_job prev_log tmout
        return (True, result)
    _ -> do
     cfg <- creader
     result <- handleCallWrapper qlock qstat cfg args
     return (True, result)

luxiHandler :: LuxiConfig -> U.Handler LuxiOp IO JSValue
luxiHandler cfg = U.Handler { U.hParse         = decodeLuxiCall
                            , U.hInputLogShort = strOfOp
                            , U.hInputLogLong  = show
                            , U.hExec          = luxiExec cfg
                            }

-- | Type alias for prepMain results
type PrepResult = (Server, IORef (Result ConfigData), JQStatus)

-- | Activate the master IP address.
activateMasterIP :: IO (Result ())
activateMasterIP = runResultT $ do
  liftIO $ logDebug "Activating master IP address"
  conf_file <- liftIO Path.clusterConfFile
  config <- mkResultT $ Config.loadConfig conf_file
  let mnp = Config.getMasterNetworkParameters config
      masters = Config.getMasterNodes config
      ems = clusterUseExternalMipScript $ configCluster config
  liftIO . logDebug $ "Master IP params: " ++ show mnp
  res <- liftIO . executeRpcCall masters $ RpcCallNodeActivateMasterIp mnp ems
  _ <- liftIO $ logRpcErrors res
  liftIO $ logDebug "finished activating master IP address"
  return ()

-- | Check function for luxid.
checkMain :: CheckFn ()
checkMain = handleMasterVerificationOptions

-- | Prepare function for luxid.
prepMain :: PrepFn () PrepResult
prepMain _ _ = do
  Exec.isForkSupported
    >>= flip exitUnless "The daemon must be compiled without -threaded"

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
  -- Subscribe to config udpates. If the config changes, write new config and
  -- check if the changes should trigger the scheduler.
  initConfigReader $ \newConfig -> do

    runScheduler <- atomicModifyIORef cref $ \oldConfig ->
      case (oldConfig, newConfig) of
        (Ok old, Ok new) -> (newConfig, configChangeNeedsRescheduling old new)
        _                -> (newConfig, True) -- no old or new config, schedule

    when runScheduler (updateStatusAndScheduleSomeJobs jq)

  let creader = readIORef cref

  qlockFile <- jobQueueLockFile
  _ <- lockFile qlockFile >>= exitIfBad "Failed to obtain the job-queue lock"
  qlock <- newLock

  _ <- P.installHandler P.sigCHLD P.Ignore Nothing

  _ <- forkIO . void $ activateMasterIP

  initJQScheduler jq

  finally
    (forever $ U.listener (luxiHandler (qlock, jq, creader)) server)
    (closeServer server >> removeFile qlockFile)

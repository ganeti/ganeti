{-# LANGUAGE BangPatterns #-}

{-| Implementation of the Ganeti confd server functionality.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.Confd.Server
  ( main
  ) where

import Control.Concurrent
import Control.Exception
import Control.Monad (forever)
import qualified Data.ByteString as B
import Data.IORef
import Data.List
import qualified Data.Map as M
import qualified Network.Socket as S
import System.Posix.Files
import System.Posix.Types
import System.Time
import qualified Text.JSON as J
import System.INotify

import Ganeti.Daemon
import Ganeti.HTools.JSON
import Ganeti.HTools.Types
import Ganeti.HTools.Utils
import Ganeti.Objects
import Ganeti.Confd
import Ganeti.Config
import Ganeti.Hash
import Ganeti.Logging
import qualified Ganeti.Constants as C

-- * Types and constants definitions

-- | What we store as configuration.
type CRef = IORef (Result (ConfigData, LinkIpMap))

-- | File stat identifier.
type FStat = (EpochTime, FileID, FileOffset)

-- | Null 'FStat' value.
nullFStat :: FStat
nullFStat = (-1, -1, -1)

-- | A small type alias for readability.
type StatusAnswer = (ConfdReplyStatus, J.JSValue)

-- | Reload model data type.
data ReloadModel = ReloadNotify      -- ^ We are using notifications
                 | ReloadPoll Int    -- ^ We are using polling
                   deriving (Eq, Show)

-- | Server state data type.
data ServerState = ServerState
  { reloadModel  :: ReloadModel
  , reloadTime   :: Integer
  , reloadFStat  :: FStat
  }

-- | Maximum no-reload poll rounds before reverting to inotify.
maxIdlePollRounds :: Int
maxIdlePollRounds = 2

-- | Reload timeout in microseconds.
configReloadTimeout :: Int
configReloadTimeout = C.confdConfigReloadTimeout * 1000000

-- | Ratelimit timeout in microseconds.
configReloadRatelimit :: Int
configReloadRatelimit = C.confdConfigReloadRatelimit * 1000000

-- | Initial poll round.
initialPoll :: ReloadModel
initialPoll = ReloadPoll 0

-- | Initial server state.
initialState :: ServerState
initialState = ServerState initialPoll 0 nullFStat

-- | Reload status data type.
data ConfigReload = ConfigToDate    -- ^ No need to reload
                  | ConfigReloaded  -- ^ Configuration reloaded
                  | ConfigIOError   -- ^ Error during configuration reload

-- | Unknown entry standard response.
queryUnknownEntry :: StatusAnswer
queryUnknownEntry = (ReplyStatusError, J.showJSON ConfdErrorUnknownEntry)

{- not used yet
-- | Internal error standard response.
queryInternalError :: StatusAnswer
queryInternalError = (ReplyStatusError, J.showJSON ConfdErrorInternal)
-}

-- | Argument error standard response.
queryArgumentError :: StatusAnswer
queryArgumentError = (ReplyStatusError, J.showJSON ConfdErrorArgument)

-- | Returns the current time.
getCurrentTime :: IO Integer
getCurrentTime = do
  TOD ctime _ <- getClockTime
  return ctime

-- * Confd base functionality

-- | Returns the HMAC key.
getClusterHmac :: IO HashKey
getClusterHmac = fmap B.unpack $ B.readFile C.confdHmacKey

-- | Computes the node role.
nodeRole :: ConfigData -> String -> Result ConfdNodeRole
nodeRole cfg name =
  let cmaster = clusterMasterNode . configCluster $ cfg
      mnode = M.lookup name . configNodes $ cfg
  in case mnode of
       Nothing -> Bad "Node not found"
       Just node | cmaster == name -> Ok NodeRoleMaster
                 | nodeDrained node -> Ok NodeRoleDrained
                 | nodeOffline node -> Ok NodeRoleOffline
                 | nodeMasterCandidate node -> Ok NodeRoleCandidate
       _ -> Ok NodeRoleRegular

-- | Does an instance ip -> instance -> primary node -> primary ip
-- transformation.
getNodePipByInstanceIp :: ConfigData
                       -> LinkIpMap
                       -> String
                       -> String
                       -> StatusAnswer
getNodePipByInstanceIp cfg linkipmap link instip =
  case M.lookup instip (M.findWithDefault M.empty link linkipmap) of
    Nothing -> queryUnknownEntry
    Just instname ->
      case getInstPrimaryNode cfg instname of
        Bad _ -> queryUnknownEntry -- either instance or node not found
        Ok node -> (ReplyStatusOk, J.showJSON (nodePrimaryIp node))

-- | Builds the response to a given query.
buildResponse :: (ConfigData, LinkIpMap) -> ConfdRequest -> Result StatusAnswer
buildResponse (cfg, _) (ConfdRequest { confdRqType = ReqPing }) =
  return (ReplyStatusOk, J.showJSON (configVersion cfg))

buildResponse cdata req@(ConfdRequest { confdRqType = ReqClusterMaster }) =
  case confdRqQuery req of
    EmptyQuery -> return (ReplyStatusOk, J.showJSON master_name)
    PlainQuery _ -> return queryArgumentError
    DictQuery reqq -> do
      mnode <- getNode cfg master_name
      let fvals =map (\field -> case field of
                                  ReqFieldName -> master_name
                                  ReqFieldIp -> clusterMasterIp cluster
                                  ReqFieldMNodePip -> nodePrimaryIp mnode
                     ) (confdReqQFields reqq)
      return (ReplyStatusOk, J.showJSON fvals)
    where master_name = clusterMasterNode cluster
          cluster = configCluster cfg
          cfg = fst cdata

buildResponse cdata req@(ConfdRequest { confdRqType = ReqNodeRoleByName }) = do
  node_name <- case confdRqQuery req of
                 PlainQuery str -> return str
                 _ -> fail $ "Invalid query type " ++ show (confdRqQuery req)
  role <- nodeRole (fst cdata) node_name
  return (ReplyStatusOk, J.showJSON role)

buildResponse cdata (ConfdRequest { confdRqType = ReqNodePipList }) =
  -- note: we use foldlWithKey because that's present accross more
  -- versions of the library
  return (ReplyStatusOk, J.showJSON $
          M.foldlWithKey (\accu _ n -> nodePrimaryIp n:accu) []
          (configNodes (fst cdata)))

buildResponse cdata (ConfdRequest { confdRqType = ReqMcPipList }) =
  -- note: we use foldlWithKey because that's present accross more
  -- versions of the library
  return (ReplyStatusOk, J.showJSON $
          M.foldlWithKey (\accu _ n -> if nodeMasterCandidate n
                                         then nodePrimaryIp n:accu
                                         else accu) []
          (configNodes (fst cdata)))

buildResponse (cfg, linkipmap)
              req@(ConfdRequest { confdRqType = ReqInstIpsList }) = do
  link <- case confdRqQuery req of
            PlainQuery str -> return str
            EmptyQuery -> return (getDefaultNicLink cfg)
            _ -> fail "Invalid query type"
  return (ReplyStatusOk, J.showJSON $ getInstancesIpByLink linkipmap link)

buildResponse cdata (ConfdRequest { confdRqType = ReqNodePipByInstPip
                                  , confdRqQuery = DictQuery query}) =
  let (cfg, linkipmap) = cdata
      link = maybe (getDefaultNicLink cfg) id (confdReqQLink query)
  in case confdReqQIp query of
       Just ip -> return $ getNodePipByInstanceIp cfg linkipmap link ip
       Nothing -> return (ReplyStatusOk,
                          J.showJSON $
                           map (getNodePipByInstanceIp cfg linkipmap link)
                           (confdReqQIpList query))

buildResponse _ (ConfdRequest { confdRqType = ReqNodePipByInstPip }) =
  return queryArgumentError

buildResponse cdata req@(ConfdRequest { confdRqType = ReqNodeDrbd }) = do
  let cfg = fst cdata
  node_name <- case confdRqQuery req of
                 PlainQuery str -> return str
                 _ -> fail $ "Invalid query type " ++ show (confdRqQuery req)
  node <- getNode cfg node_name
  let minors = concatMap (getInstMinorsForNode (nodeName node)) .
               M.elems . configInstances $ cfg
      encoded = [J.JSArray [J.showJSON a, J.showJSON b, J.showJSON c,
                             J.showJSON d, J.showJSON e, J.showJSON f] |
                 (a, b, c, d, e, f) <- minors]
  return (ReplyStatusOk, J.showJSON encoded)

-- | Parses a signed request.
parseRequest :: HashKey -> String -> Result (String, String, ConfdRequest)
parseRequest key str = do
  (SignedMessage hmac msg salt) <- fromJResult "parsing request" $ J.decode str
  req <- if verifyMac key (Just salt) msg hmac
           then fromJResult "parsing message" $ J.decode msg
           else Bad "HMAC verification failed"
  return (salt, msg, req)

-- | Creates a ConfdReply from a given answer.
serializeResponse :: Result StatusAnswer -> ConfdReply
serializeResponse r =
    let (status, result) = case r of
                    Bad err -> (ReplyStatusError, J.showJSON err)
                    Ok (code, val) -> (code, val)
    in ConfdReply { confdReplyProtocol = 1
                  , confdReplyStatus   = status
                  , confdReplyAnswer   = result
                  , confdReplySerial   = 0 }

-- | Signs a message with a given key and salt.
signMessage :: HashKey -> String -> String -> SignedMessage
signMessage key salt msg =
  SignedMessage { signedMsgMsg  = msg
                , signedMsgSalt = salt
                , signedMsgHmac = hmac
                }
    where hmac = computeMac key (Just salt) msg

-- * Configuration handling

-- ** Helper functions

-- | Helper function for logging transition into polling mode.
moveToPolling :: String -> INotify -> FilePath -> CRef -> MVar ServerState
              -> IO ReloadModel
moveToPolling msg inotify path cref mstate = do
  logInfo $ "Moving to polling mode: " ++ msg
  let inotiaction = addNotifier inotify path cref mstate
  _ <- forkIO $ onReloadTimer inotiaction path cref mstate
  return initialPoll

-- | Helper function for logging transition into inotify mode.
moveToNotify :: IO ReloadModel
moveToNotify = do
  logInfo "Moving to inotify mode"
  return ReloadNotify

-- ** Configuration loading

-- | (Re)loads the configuration.
updateConfig :: FilePath -> CRef -> IO ()
updateConfig path r = do
  newcfg <- loadConfig path
  let !newdata = case newcfg of
                   Ok !cfg -> Ok (cfg, buildLinkIpInstnameMap cfg)
                   Bad _ -> Bad "Cannot load configuration"
  writeIORef r newdata
  case newcfg of
    Ok cfg -> logInfo ("Loaded new config, serial " ++
                       show (configSerial cfg))
    Bad msg -> logError $ "Failed to load config: " ++ msg
  return ()

-- | Wrapper over 'updateConfig' that handles IO errors.
safeUpdateConfig :: FilePath -> FStat -> CRef -> IO (FStat, ConfigReload)
safeUpdateConfig path oldfstat cref = do
  Control.Exception.catch
        (do
          nt <- needsReload oldfstat path
          case nt of
            Nothing -> return (oldfstat, ConfigToDate)
            Just nt' -> do
                    updateConfig path cref
                    return (nt', ConfigReloaded)
        ) (\e -> do
             let msg = "Failure during configuration update: " ++
                       show (e::IOError)
             writeIORef cref (Bad msg)
             return (nullFStat, ConfigIOError)
          )

-- | Computes the file cache data from a FileStatus structure.
buildFileStatus :: FileStatus -> FStat
buildFileStatus ofs =
    let modt = modificationTime ofs
        inum = fileID ofs
        fsize = fileSize ofs
    in (modt, inum, fsize)

-- | Wrapper over 'buildFileStatus'. This reads the data from the
-- filesystem and then builds our cache structure.
getFStat :: FilePath -> IO FStat
getFStat p = getFileStatus p >>= (return . buildFileStatus)

-- | Check if the file needs reloading
needsReload :: FStat -> FilePath -> IO (Maybe FStat)
needsReload oldstat path = do
  newstat <- getFStat path
  return $ if newstat /= oldstat
             then Just newstat
             else Nothing

-- ** Watcher threads

-- $watcher
-- We have three threads/functions that can mutate the server state:
--
-- 1. the long-interval watcher ('onTimeoutTimer')
--
-- 2. the polling watcher ('onReloadTimer')
--
-- 3. the inotify event handler ('onInotify')
--
-- All of these will mutate the server state under 'modifyMVar' or
-- 'modifyMVar_', so that server transitions are more or less
-- atomic. The inotify handler remains active during polling mode, but
-- checks for polling mode and doesn't do anything in this case (this
-- check is needed even if we would unregister the event handler due
-- to how events are serialised).

-- | Long-interval reload watcher.
--
-- This is on top of the inotify-based triggered reload.
onTimeoutTimer :: IO Bool -> FilePath -> CRef -> MVar ServerState -> IO ()
onTimeoutTimer inotiaction path cref state = do
  threadDelay configReloadTimeout
  modifyMVar_ state (onTimeoutInner path cref)
  _ <- inotiaction
  onTimeoutTimer inotiaction path cref state

-- | Inner onTimeout handler.
--
-- This mutates the server state under a modifyMVar_ call. It never
-- changes the reload model, just does a safety reload and tried to
-- re-establish the inotify watcher.
onTimeoutInner :: FilePath -> CRef -> ServerState -> IO ServerState
onTimeoutInner path cref state  = do
  (newfstat, _) <- safeUpdateConfig path (reloadFStat state) cref
  return state { reloadFStat = newfstat }

-- | Short-interval (polling) reload watcher.
--
-- This is only active when we're in polling mode; it will
-- automatically exit when it detects that the state has changed to
-- notification.
onReloadTimer :: IO Bool -> FilePath -> CRef -> MVar ServerState -> IO ()
onReloadTimer inotiaction path cref state = do
  continue <- modifyMVar state (onReloadInner inotiaction path cref)
  if continue
    then do
      threadDelay configReloadRatelimit
      onReloadTimer inotiaction path cref state
    else -- the inotify watch has been re-established, we can exit
      return ()

-- | Inner onReload handler.
--
-- This again mutates the state under a modifyMVar call, and also
-- returns whether the thread should continue or not.
onReloadInner :: IO Bool -> FilePath -> CRef -> ServerState
              -> IO (ServerState, Bool)
onReloadInner _ _ _ state@(ServerState { reloadModel = ReloadNotify } ) =
  return (state, False)
onReloadInner inotiaction path cref
              state@(ServerState { reloadModel = ReloadPoll pround } ) = do
  (newfstat, reload) <- safeUpdateConfig path (reloadFStat state) cref
  let state' = state { reloadFStat = newfstat }
  -- compute new poll model based on reload data; however, failure to
  -- re-establish the inotifier means we stay on polling
  newmode <- case reload of
               ConfigToDate ->
                 if pround >= maxIdlePollRounds
                   then do -- try to switch to notify
                     result <- inotiaction
                     if result
                       then moveToNotify
                       else return initialPoll
                   else return (ReloadPoll (pround + 1))
               _ -> return initialPoll
  let continue = case newmode of
                   ReloadNotify -> False
                   _            -> True
  return (state' { reloadModel = newmode }, continue)

-- | Setup inotify watcher.
--
-- This tries to setup the watch descriptor; in case of any IO errors,
-- it will return False.
addNotifier :: INotify -> FilePath -> CRef -> MVar ServerState -> IO Bool
addNotifier inotify path cref mstate = do
  Control.Exception.catch
        (addWatch inotify [CloseWrite] path
                    (onInotify inotify path cref mstate) >> return True)
        (\e -> const (return False) (e::IOError))

-- | Inotify event handler.
onInotify :: INotify -> String -> CRef -> MVar ServerState -> Event -> IO ()
onInotify inotify path cref mstate Ignored = do
  logInfo "File lost, trying to re-establish notifier"
  modifyMVar_ mstate $ \state -> do
    result <- addNotifier inotify path cref mstate
    (newfstat, _) <- safeUpdateConfig path (reloadFStat state) cref
    let state' = state { reloadFStat = newfstat }
    if result
      then return state' -- keep notify
      else do
        mode <- moveToPolling "cannot re-establish inotify watch" inotify
                  path cref mstate
        return state' { reloadModel = mode }

onInotify inotify path cref mstate _ = do
  modifyMVar_ mstate $ \state ->
    if (reloadModel state == ReloadNotify)
       then do
         ctime <- getCurrentTime
         (newfstat, _) <- safeUpdateConfig path (reloadFStat state) cref
         let state' = state { reloadFStat = newfstat, reloadTime = ctime }
         if abs (reloadTime state - ctime) <
            fromIntegral C.confdConfigReloadRatelimit
           then do
             mode <- moveToPolling "too many reloads" inotify path cref mstate
             return state' { reloadModel = mode }
           else return state'
      else return state

-- ** Client input/output handlers

-- | Main loop for a given client.
responder :: CRef -> S.Socket -> HashKey -> String -> S.SockAddr -> IO ()
responder cfgref socket hmac msg peer = do
  ctime <- getCurrentTime
  case parseMessage hmac msg ctime of
    Ok (origmsg, rq) -> do
              logDebug $ "Processing request: " ++ origmsg
              mcfg <- readIORef cfgref
              let response = respondInner mcfg hmac rq
              _ <- S.sendTo socket response peer
              return ()
    Bad err -> logInfo $ "Failed to parse incoming message: " ++ err
  return ()

-- | Mesage parsing. This can either result in a good, valid message,
-- or fail in the Result monad.
parseMessage :: HashKey -> String -> Integer
             -> Result (String, ConfdRequest)
parseMessage hmac msg curtime = do
  (salt, origmsg, request) <- parseRequest hmac msg
  ts <- tryRead "Parsing timestamp" salt::Result Integer
  if (abs (ts - curtime) > (fromIntegral C.confdMaxClockSkew))
    then fail "Too old/too new timestamp or clock skew"
    else return (origmsg, request)

-- | Inner helper function for a given client. This generates the
-- final encoded message (as a string), ready to be sent out to the
-- client.
respondInner :: Result (ConfigData, LinkIpMap) -> HashKey
             -> ConfdRequest -> String
respondInner cfg hmac rq =
  let rsalt = confdRqRsalt rq
      innermsg = serializeResponse (cfg >>= flip buildResponse rq)
      innerserialised = J.encodeStrict innermsg
      outermsg = signMessage hmac rsalt innerserialised
      outerserialised = confdMagicFourcc ++ J.encodeStrict outermsg
  in outerserialised

-- | Main listener loop.
listener :: S.Socket -> HashKey
         -> (S.Socket -> HashKey -> String -> S.SockAddr -> IO ())
         -> IO ()
listener s hmac resp = do
  (msg, _, peer) <- S.recvFrom s 4096
  if confdMagicFourcc `isPrefixOf` msg
    then (forkIO $ resp s hmac (drop 4 msg) peer) >> return ()
    else logDebug "Invalid magic code!" >> return ()
  return ()

-- | Main function.
main :: DaemonOptions -> IO ()
main opts = do
  parseresult <- parseAddress opts C.defaultConfdPort
  (af_family, bindaddr) <- exitIfBad "parsing bind address" parseresult
  s <- S.socket af_family S.Datagram S.defaultProtocol
  S.bindSocket s bindaddr
  cref <- newIORef (Bad "Configuration not yet loaded")
  statemvar <- newMVar initialState
  hmac <- getClusterHmac
  -- Inotify setup
  inotify <- initINotify
  let inotiaction = addNotifier inotify C.clusterConfFile cref statemvar
  -- fork the timeout timer
  _ <- forkIO $ onTimeoutTimer inotiaction C.clusterConfFile cref statemvar
  -- fork the polling timer
  _ <- forkIO $ onReloadTimer inotiaction C.clusterConfFile cref statemvar
  -- and finally enter the responder loop
  forever $ listener s hmac (responder cref)

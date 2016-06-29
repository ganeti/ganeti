{-# LANGUAGE TupleSections #-}

{-| Implementation of the Ganeti confd server functionality.

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.
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

module Ganeti.Confd.Server
  ( main
  , checkMain
  , prepMain
  ) where

import Control.Applicative((<$>))
import Control.Concurrent
import Control.Monad (forever, liftM)
import Data.IORef
import Data.List
import qualified Data.Map as M
import Data.Maybe (fromMaybe)
import Network.BSD (getServicePortNumber)
import qualified Network.Socket as S
import System.Exit
import System.IO
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Daemon
import Ganeti.JSON (containerFromList, fromContainer)
import Ganeti.Objects
import Ganeti.Confd.Types
import Ganeti.Confd.Utils
import Ganeti.Config
import Ganeti.ConfigReader
import Ganeti.Hash
import Ganeti.Logging
import qualified Ganeti.Constants as C
import qualified Ganeti.Query.Cluster as QCluster
import Ganeti.Utils
import Ganeti.DataCollectors.Types (DataCollector(..))
import Ganeti.DataCollectors (collectors)

-- * Types and constants definitions

-- | What we store as configuration.
type CRef = IORef (Result (ConfigData, LinkIpMap))

-- | A small type alias for readability.
type StatusAnswer = (ConfdReplyStatus, J.JSValue, Int)

-- | Unknown entry standard response.
queryUnknownEntry :: StatusAnswer
queryUnknownEntry = (ReplyStatusError, J.showJSON ConfdErrorUnknownEntry, 0)

{- not used yet
-- | Internal error standard response.
queryInternalError :: StatusAnswer
queryInternalError = (ReplyStatusError, J.showJSON ConfdErrorInternal)
-}

-- | Argument error standard response.
queryArgumentError :: StatusAnswer
queryArgumentError = (ReplyStatusError, J.showJSON ConfdErrorArgument, 0)

-- | Converter from specific error to a string format.
gntErrorToResult :: ErrorResult a -> Result a
gntErrorToResult (Bad err) = Bad (show err)
gntErrorToResult (Ok x) = Ok x

-- * Confd base functionality

-- | Computes the node role
nodeRole :: ConfigData -> String -> Result ConfdNodeRole
nodeRole cfg name = do
  cmaster <- errToResult $ QCluster.clusterMasterNodeName cfg
  mnode <- errToResult $ getNode cfg name
  let nrole = case mnode of
                node | cmaster == name -> NodeRoleMaster
                     | nodeDrained node -> NodeRoleDrained
                     | nodeOffline node -> NodeRoleOffline
                     | nodeMasterCandidate node -> NodeRoleCandidate
                _ -> NodeRoleRegular
  return nrole

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
        Ok node -> (ReplyStatusOk, J.showJSON (nodePrimaryIp node),
                    clusterSerial $ configCluster cfg)

-- | Returns a node name for a given UUID
uuidToNodeName :: ConfigData -> String -> Result String
uuidToNodeName cfg uuid = gntErrorToResult $ nodeName <$> getNode cfg uuid

-- | Encodes a list of minors into a JSON representation, converting UUIDs to
-- names in the process
encodeMinors :: ConfigData -> (String, Int, String, String, String, String)
             -> Result J.JSValue
encodeMinors cfg (node_uuid, a, b, c, d, peer_uuid) = do
  node_name <- uuidToNodeName cfg node_uuid
  peer_name <- uuidToNodeName cfg peer_uuid
  return . J.JSArray $ [J.showJSON node_name, J.showJSON a, J.showJSON b,
                        J.showJSON c, J.showJSON d, J.showJSON peer_name]

-- | Builds the response to a given query.
buildResponse :: (ConfigData, LinkIpMap) -> ConfdRequest -> Result StatusAnswer
buildResponse (cfg, _) (ConfdRequest { confdRqType = ReqPing }) =
  return (ReplyStatusOk, J.showJSON (configVersion cfg), 0)

buildResponse cdata req@(ConfdRequest { confdRqType = ReqClusterMaster }) =
  case confdRqQuery req of
    EmptyQuery -> liftM ((ReplyStatusOk,,serial) . J.showJSON) master_name
    PlainQuery _ -> return queryArgumentError
    DictQuery reqq -> do
      mnode <- gntErrorToResult $ getNode cfg master_uuid
      mname <- master_name
      let fvals = map (\field -> case field of
                                   ReqFieldName -> mname
                                   ReqFieldIp -> clusterMasterIp cluster
                                   ReqFieldMNodePip -> nodePrimaryIp mnode
                      ) (confdReqQFields reqq)
      return (ReplyStatusOk, J.showJSON fvals, serial)
    where master_uuid = clusterMasterNode cluster
          master_name = errToResult $ QCluster.clusterMasterNodeName cfg
          cluster = configCluster cfg
          cfg = fst cdata
          serial = clusterSerial $ configCluster cfg

buildResponse cdata req@(ConfdRequest { confdRqType = ReqNodeRoleByName }) = do
  node_name <- case confdRqQuery req of
                 PlainQuery str -> return str
                 _ -> fail $ "Invalid query type " ++ show (confdRqQuery req)
  nrole <- nodeRole (fst cdata) node_name
  return (ReplyStatusOk, J.showJSON nrole,
          clusterSerial . configCluster $ fst cdata)

buildResponse cdata (ConfdRequest { confdRqType = ReqNodePipList }) =
  -- note: we use foldlWithKey because that's present accross more
  -- versions of the library
  return (ReplyStatusOk, J.showJSON $
          M.foldlWithKey (\accu _ n -> nodePrimaryIp n:accu) []
          (fromContainer . configNodes . fst $ cdata),
          clusterSerial . configCluster $ fst cdata)

buildResponse cdata (ConfdRequest { confdRqType = ReqMcPipList }) =
  -- note: we use foldlWithKey because that's present accross more
  -- versions of the library
  return (ReplyStatusOk, J.showJSON $
          M.foldlWithKey (\accu _ n -> if nodeMasterCandidate n
                                         then nodePrimaryIp n:accu
                                         else accu) []
          (fromContainer . configNodes . fst $ cdata),
          clusterSerial . configCluster $ fst cdata)

buildResponse (cfg, linkipmap)
              req@(ConfdRequest { confdRqType = ReqInstIpsList }) = do
  link <- case confdRqQuery req of
            PlainQuery str -> return str
            EmptyQuery -> return (getDefaultNicLink cfg)
            _ -> fail "Invalid query type"
  return (ReplyStatusOk, J.showJSON $ getInstancesIpByLink linkipmap link,
          clusterSerial $ configCluster cfg)

buildResponse cdata (ConfdRequest { confdRqType = ReqNodePipByInstPip
                                  , confdRqQuery = DictQuery query}) =
  let (cfg, linkipmap) = cdata
      link = fromMaybe (getDefaultNicLink cfg) (confdReqQLink query)
  in case confdReqQIp query of
       Just ip -> return $ getNodePipByInstanceIp cfg linkipmap link ip
       Nothing -> return (ReplyStatusOk,
                          J.showJSON $
                           map (getNodePipByInstanceIp cfg linkipmap link)
                           (confdReqQIpList query),
                          clusterSerial . configCluster $ fst cdata)

buildResponse _ (ConfdRequest { confdRqType = ReqNodePipByInstPip }) =
  return queryArgumentError

buildResponse cdata req@(ConfdRequest { confdRqType = ReqNodeDrbd }) = do
  let cfg = fst cdata
  node_name <- case confdRqQuery req of
                 PlainQuery str -> return str
                 _ -> fail $ "Invalid query type " ++ show (confdRqQuery req)
  node <- gntErrorToResult $ getNode cfg node_name
  let minors = concatMap (getInstMinorsForNode cfg (uuidOf node)) .
               M.elems . fromContainer . configInstances $ cfg
  encoded <- mapM (encodeMinors cfg) minors
  return (ReplyStatusOk, J.showJSON encoded, nodeSerial node)

-- | Return the list of instances for a node (as ([primary], [secondary])) given
-- the node name.
buildResponse cdata req@(ConfdRequest { confdRqType = ReqNodeInstances }) = do
  let cfg = fst cdata
  node_name <- case confdRqQuery req of
                PlainQuery str -> return str
                _ -> fail $ "Invalid query type " ++ show (confdRqQuery req)
  node <-
    case getNode cfg node_name of
      Ok n -> return n
      Bad e -> fail $ "Node not found in the configuration: " ++ show e
  let node_uuid = uuidOf node
      instances = getNodeInstances cfg node_uuid
  return (ReplyStatusOk, J.showJSON instances, nodeSerial node)

-- | Return the list of disks for an instance given the instance uuid.
buildResponse cdata req@(ConfdRequest { confdRqType = ReqInstanceDisks }) = do
  let cfg = fst cdata
  inst_name <-
    case confdRqQuery req of
      PlainQuery str -> return str
      _ -> fail $ "Invalid query type " ++ show (confdRqQuery req)
  inst <-
    case getInstance cfg inst_name of
      Ok i -> return i
      Bad e -> fail $ "Instance not found in the configuration: " ++ show e
  case getInstDisks cfg . uuidOf $ inst of
    Ok disks -> return (ReplyStatusOk, J.showJSON disks, instSerial inst)
    Bad e -> fail $ "Could not retrieve disks: " ++ show e

-- | Return arbitrary configuration value given by a path.
buildResponse cdata req@(ConfdRequest { confdRqType = ReqConfigQuery
                                      , confdRqQuery = pathQ }) = do
  let cfg = fst cdata
  path <-
    case pathQ of
      PlainQuery path -> return path
      _ -> fail $ "Invalid query type " ++ show (confdRqQuery req)
  let configValue = extractJSONPath path cfg
  case configValue of
    J.Ok jsvalue -> return (ReplyStatusOk, jsvalue,
                            clusterSerial $ configCluster cfg)
    J.Error _ -> return queryArgumentError

-- | Return activation state of data collectors
buildResponse (cdata,_) (ConfdRequest { confdRqType = ReqDataCollectors }) = do
  let mkConfig col =
        (dName col, DataCollectorConfig
                   (dActive col (dName col) cdata)
                   (dInterval col (dName col) cdata))
      datacollectors = containerFromList $ map mkConfig collectors
  return (ReplyStatusOk, J.showJSON datacollectors,
          clusterSerial . configCluster $ cdata)

-- | Creates a ConfdReply from a given answer.
serializeResponse :: Result StatusAnswer -> ConfdReply
serializeResponse r =
    let (status, result, serial) = case r of
                    Bad err -> (ReplyStatusError, J.showJSON err, 0)
                    Ok (code, val, ser) -> (code, val, ser)
    in ConfdReply { confdReplyProtocol = 1
                  , confdReplyStatus   = status
                  , confdReplyAnswer   = result
                  , confdReplySerial   = serial }

-- ** Client input/output handlers

-- | Main loop for a given client.
responder :: CRef -> S.Socket -> HashKey -> String -> S.SockAddr -> IO ()
responder cfgref socket hmac msg peer = do
  ctime <- getCurrentTime
  case parseRequest hmac msg ctime of
    Ok (origmsg, rq) -> do
              logDebug $ "Processing request: " ++ rStripSpace origmsg
              mcfg <- readIORef cfgref
              let response = respondInner mcfg hmac rq
              _ <- S.sendTo socket response peer
              logDebug $ "Response sent: " ++ response
              return ()
    Bad err -> logInfo $ "Failed to parse incoming message: " ++ err
  return ()

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
      outerserialised = C.confdMagicFourcc ++ J.encodeStrict outermsg
  in outerserialised

-- | Main listener loop.
listener :: S.Socket -> HashKey
         -> (S.Socket -> HashKey -> String -> S.SockAddr -> IO ())
         -> IO ()
listener s hmac resp = do
  (msg, _, peer) <- S.recvFrom s 4096
  if C.confdMagicFourcc `isPrefixOf` msg
    then forkIO (resp s hmac (drop 4 msg) peer) >> return ()
    else logDebug "Invalid magic code!" >> return ()
  return ()

-- | Type alias for prepMain results
type PrepResult = (S.Socket, IORef (Result (ConfigData, LinkIpMap)))

-- | Check function for confd.
checkMain :: CheckFn (S.Family, S.SockAddr)
checkMain opts = do
  defaultPort <- withDefaultOnIOError C.defaultConfdPort
                 . liftM fromIntegral
                 $ getServicePortNumber C.confd
  parseresult <- parseAddress opts defaultPort
  case parseresult of
    Bad msg -> do
      hPutStrLn stderr $ "parsing bind address: " ++ msg
      return . Left $ ExitFailure 1
    Ok v -> return $ Right v

-- | Prepare function for confd.
prepMain :: PrepFn (S.Family, S.SockAddr) PrepResult
prepMain _ (af_family, bindaddr) = do
  s <- S.socket af_family S.Datagram S.defaultProtocol
  S.setSocketOption s S.ReuseAddr 1
  S.bindSocket s bindaddr
  cref <- newIORef (Bad "Configuration not yet loaded")
  return (s, cref)

-- | Main function.
main :: MainFn (S.Family, S.SockAddr) PrepResult
main _ _ (s, cref) = do
  let cfg_transform :: Result ConfigData -> Result (ConfigData, LinkIpMap)
      cfg_transform = liftM (\cfg -> (cfg, buildLinkIpInstnameMap cfg))
  initConfigReader (writeIORef cref . cfg_transform)

  hmac <- getClusterHmac
  -- enter the responder loop
  forever $ listener s hmac (responder cref)

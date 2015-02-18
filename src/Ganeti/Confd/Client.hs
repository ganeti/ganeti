{-| Implementation of the Ganeti Confd client functionality.

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

module Ganeti.Confd.Client
  ( getConfdClient
  , query
  ) where

import Control.Concurrent
import Control.Exception (bracket)
import Control.Monad
import Data.List
import Data.Maybe
import qualified Network.Socket as S
import System.Posix.Time
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Confd.Types
import Ganeti.Confd.Utils
import qualified Ganeti.Constants as C
import Ganeti.Hash
import Ganeti.Ssconf
import Ganeti.Utils

-- | Builds a properly initialized ConfdClient.
-- The parameters (an IP address and the port number for the Confd client
-- to connect to) are mainly meant for testing purposes. If they are not
-- provided, the list of master candidates and the default port number will
-- be used.
getConfdClient :: Maybe String -> Maybe Int -> IO ConfdClient
getConfdClient addr portNum = S.withSocketsDo $ do
  hmac <- getClusterHmac
  candList <- getMasterCandidatesIps Nothing
  peerList <-
    case candList of
      (Ok p) -> return p
      (Bad msg) -> fail msg
  let addrList = maybe peerList (:[]) addr
      port = fromMaybe C.defaultConfdPort portNum
  return . ConfdClient hmac addrList $ fromIntegral port

-- | Sends a query to all the Confd servers the client is connected to.
-- Returns the most up-to-date result according to the serial number,
-- chosen between those received before the timeout.
query :: ConfdClient -> ConfdRequestType -> ConfdQuery -> IO (Maybe ConfdReply)
query client crType cQuery = do
  semaphore <- newMVar ()
  answer <- newMVar Nothing
  let dest = [(host, serverPort client) | host <- peers client]
      hmac = hmacKey client
      jobs = map (queryOneServer semaphore answer crType cQuery hmac) dest
      watchdog reqAnswers = do
        threadDelay $ 1000000 * C.confdClientExpireTimeout
        _ <- swapMVar reqAnswers 0
        putMVar semaphore ()
      waitForResult reqAnswers = do
        _ <- takeMVar semaphore
        l <- takeMVar reqAnswers
        unless (l == 0) $ do
          putMVar reqAnswers $ l - 1
          waitForResult reqAnswers
  reqAnswers <- newMVar . min C.confdDefaultReqCoverage $ length dest
  workers <- mapM forkIO jobs
  watcher <- forkIO $ watchdog reqAnswers
  waitForResult reqAnswers
  mapM_ killThread $ watcher:workers
  takeMVar answer

-- | Updates the reply to the query. As per the Confd design document,
-- only the reply with the highest serial number is kept.
updateConfdReply :: ConfdReply -> Maybe ConfdReply -> Maybe ConfdReply
updateConfdReply newValue Nothing = Just newValue
updateConfdReply newValue (Just currentValue) = Just $
  if confdReplyStatus newValue == ReplyStatusOk
      && (confdReplyStatus currentValue /= ReplyStatusOk
          || confdReplySerial newValue > confdReplySerial currentValue)
    then newValue
    else currentValue

-- | Send a query to a single server, waits for the result and stores it
-- in a shared variable. Then, sends a signal on another shared variable
-- acting as a semaphore.
-- This function is meant to be used as one of multiple threads querying
-- multiple servers in parallel.
queryOneServer
  :: MVar ()                 -- ^ The semaphore that will be signalled
  -> MVar (Maybe ConfdReply) -- ^ The shared variable for the result
  -> ConfdRequestType        -- ^ The type of the query to be sent
  -> ConfdQuery              -- ^ The content of the query
  -> HashKey                 -- ^ The hmac key to sign the message
  -> (String, S.PortNumber)  -- ^ The address and port of the server
  -> IO ()
queryOneServer semaphore answer crType cQuery hmac (host, port) = do
  request <- newConfdRequest crType cQuery
  timestamp <- fmap show epochTime
  let signedMsg =
        signMessage hmac timestamp (J.encodeStrict request)
      completeMsg = C.confdMagicFourcc ++ J.encodeStrict signedMsg
  addr <- resolveAddr (fromIntegral port) host
  (af_family, sockaddr) <-
    exitIfBad "Unable to resolve the IP address" addr
  replyMsg <- bracket (S.socket af_family S.Datagram S.defaultProtocol) S.sClose
                $ \s -> do
    _ <- S.sendTo s completeMsg sockaddr
    S.recv s C.maxUdpDataSize
  parsedReply <-
    if C.confdMagicFourcc `isPrefixOf` replyMsg
      then return . parseReply hmac (drop 4 replyMsg) $ confdRqRsalt request
      else fail "Invalid magic code!"
  reply <-
    case parsedReply of
      Ok (_, r) -> return r
      Bad msg -> fail msg
  modifyMVar_ answer $! return . updateConfdReply reply
  putMVar semaphore ()

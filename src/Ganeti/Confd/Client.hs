{-| Implementation of the Ganeti Confd client functionality.

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

module Ganeti.Confd.Client
  ( getConfdClient
  , query
  ) where

import Control.Concurrent
import Control.Monad
import Data.List
import qualified Network.Socket as S
import System.Posix.Time
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Confd.Types
import Ganeti.Confd.Utils
import qualified Ganeti.Constants as C
import Ganeti.Hash
import Ganeti.Ssconf

-- | Builds a properly initialized ConfdClient
getConfdClient :: IO ConfdClient
getConfdClient = S.withSocketsDo $ do
  hmac <- getClusterHmac
  candList <- getMasterCandidatesIps Nothing
  peerList <-
    case candList of
      (Ok p) -> return p
      (Bad msg) -> fail msg
  return . ConfdClient hmac peerList $ fromIntegral C.defaultConfdPort

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
  s <- S.socket S.AF_INET S.Datagram S.defaultProtocol
  hostAddr <- S.inet_addr host
  _ <- S.sendTo s completeMsg $ S.SockAddrInet port hostAddr
  replyMsg <- S.recv s C.maxUdpDataSize
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

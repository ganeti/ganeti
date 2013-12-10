{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti Unix Domain Socket JSON server interface.

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

module Ganeti.UDSServer
  ( ConnectConfig(..)
  , Client
  , Server
  , RecvResult(..)
  , MsgKeys(..)
  , strOfKey
  , connectClient
  , connectServer
  , acceptClient
  , closeClient
  , closeServer
  , buildResponse
  , parseCall
  , recvMsg
  , recvMsgExt
  , sendMsg
  -- * Client handler
  , Handler(..)
  , HandlerResult
  , listener
  ) where

import Control.Applicative
import Control.Concurrent (forkIO)
import Control.Exception (catch)
import Data.IORef
import qualified Data.ByteString as B
import qualified Data.ByteString.Lazy as BL
import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.ByteString.Lazy.UTF8 as UTF8L
import Data.Word (Word8)
import Control.Monad
import qualified Network.Socket as S
import System.Directory (removeFile)
import System.IO (hClose, hFlush, hWaitForInput, Handle, IOMode(..))
import System.IO.Error (isEOFError)
import System.Timeout
import Text.JSON (encodeStrict, decodeStrict)
import qualified Text.JSON as J
import Text.JSON.Types

import Ganeti.BasicTypes
import Ganeti.Errors (GanetiException)
import Ganeti.JSON
import Ganeti.Logging
import Ganeti.Runtime (GanetiDaemon(..), MiscGroup(..), GanetiGroup(..))
import Ganeti.THH
import Ganeti.Utils


-- * Utility functions

-- | Wrapper over System.Timeout.timeout that fails in the IO monad.
withTimeout :: Int -> String -> IO a -> IO a
withTimeout secs descr action = do
  result <- timeout (secs * 1000000) action
  case result of
    Nothing -> fail $ "Timeout in " ++ descr
    Just v -> return v


-- * Generic protocol functionality

-- | Result of receiving a message from the socket.
data RecvResult = RecvConnClosed    -- ^ Connection closed
                | RecvError String  -- ^ Any other error
                | RecvOk String     -- ^ Successfull receive
                  deriving (Show, Eq)


-- | The end-of-message separator.
eOM :: Word8
eOM = 3

-- | The end-of-message encoded as a ByteString.
bEOM :: B.ByteString
bEOM = B.singleton eOM

-- | Valid keys in the requests and responses.
data MsgKeys = Method
             | Args
             | Success
             | Result

-- | The serialisation of MsgKeys into strings in messages.
$(genStrOfKey ''MsgKeys "strOfKey")


data ConnectConfig = ConnectConfig
                     { connDaemon :: GanetiDaemon
                     , recvTmo :: Int
                     , sendTmo :: Int
                     }

-- | A client encapsulation.
data Client = Client { socket :: Handle           -- ^ The socket of the client
                     , rbuf :: IORef B.ByteString -- ^ Already received buffer
                     , clientConfig :: ConnectConfig
                     }

-- | A server encapsulation.
data Server = Server { sSocket :: S.Socket        -- ^ The bound server socket
                     , sPath :: FilePath          -- ^ The scoket's path
                     , serverConfig :: ConnectConfig
                     }


-- | Connects to the master daemon and returns a Client.
connectClient
  :: ConnectConfig    -- ^ configuration for the client
  -> Int              -- ^ connection timeout
  -> FilePath         -- ^ socket path
  -> IO Client
connectClient conf tmo path = do
  s <- S.socket S.AF_UNIX S.Stream S.defaultProtocol
  withTimeout tmo "creating a connection" $
              S.connect s (S.SockAddrUnix path)
  rf <- newIORef B.empty
  h <- S.socketToHandle s ReadWriteMode
  return Client { socket=h, rbuf=rf, clientConfig=conf }

-- | Creates and returns a server endpoint.
connectServer :: ConnectConfig -> Bool -> FilePath -> IO Server
connectServer conf setOwner path = do
  s <- S.socket S.AF_UNIX S.Stream S.defaultProtocol
  S.bindSocket s (S.SockAddrUnix path)
  when setOwner . setOwnerAndGroupFromNames path (connDaemon conf) $
    ExtraGroup DaemonsGroup
  S.listen s 5 -- 5 is the max backlog
  return Server { sSocket=s, sPath=path, serverConfig=conf }

-- | Closes a server endpoint.
-- FIXME: this should be encapsulated into a nicer type.
closeServer :: Server -> IO ()
closeServer server = do
  S.sClose (sSocket server)
  removeFile (sPath server)

-- | Accepts a client
acceptClient :: Server -> IO Client
acceptClient s = do
  -- second return is the address of the client, which we ignore here
  (client_socket, _) <- S.accept (sSocket s)
  new_buffer <- newIORef B.empty
  handle <- S.socketToHandle client_socket ReadWriteMode
  return Client { socket=handle
                , rbuf=new_buffer
                , clientConfig=serverConfig s
                }

-- | Closes the client socket.
closeClient :: Client -> IO ()
closeClient = hClose . socket

-- | Sends a message over a transport.
sendMsg :: Client -> String -> IO ()
sendMsg s buf = withTimeout (sendTmo $ clientConfig s) "sending a message" $ do
  let encoded = UTF8L.fromString buf
      handle = socket s
  BL.hPut handle encoded
  B.hPut handle bEOM
  hFlush handle

-- | Given a current buffer and the handle, it will read from the
-- network until we get a full message, and it will return that
-- message and the leftover buffer contents.
recvUpdate :: ConnectConfig -> Handle -> B.ByteString
           -> IO (B.ByteString, B.ByteString)
recvUpdate conf handle obuf = do
  nbuf <- withTimeout (recvTmo conf) "reading a response" $ do
            _ <- hWaitForInput handle (-1)
            B.hGetNonBlocking handle 4096
  let (msg, remaining) = B.break (eOM ==) nbuf
      newbuf = B.append obuf msg
  if B.null remaining
    then recvUpdate conf handle newbuf
    else return (newbuf, B.tail remaining)

-- | Waits for a message over a transport.
recvMsg :: Client -> IO String
recvMsg s = do
  cbuf <- readIORef $ rbuf s
  let (imsg, ibuf) = B.break (eOM ==) cbuf
  (msg, nbuf) <-
    if B.null ibuf      -- if old buffer didn't contain a full message
                        -- then we read from network:
      then recvUpdate (clientConfig s) (socket s) cbuf
      else return (imsg, B.tail ibuf)   -- else we return data from our buffer
  writeIORef (rbuf s) nbuf
  return $ UTF8.toString msg

-- | Extended wrapper over recvMsg.
recvMsgExt :: Client -> IO RecvResult
recvMsgExt s =
  Control.Exception.catch (liftM RecvOk (recvMsg s)) $ \e ->
    return $ if isEOFError e
               then RecvConnClosed
               else RecvError (show e)


-- | Parse the required keys out of a call.
parseCall :: (J.JSON mth, J.JSON args) => String -> Result (mth, args)
parseCall s = do
  arr <- fromJResult "parsing top-level JSON message" $
           decodeStrict s :: Result (JSObject JSValue)
  let keyFromObj :: (J.JSON a) => MsgKeys -> Result a
      keyFromObj = fromObj (fromJSObject arr) . strOfKey
  (,) <$> keyFromObj Method <*> keyFromObj Args


-- | Serialize the response to String.
buildResponse :: Bool    -- ^ Success
              -> JSValue -- ^ The arguments
              -> String  -- ^ The serialized form
buildResponse success args =
  let ja = [ (strOfKey Success, JSBool success)
           , (strOfKey Result, args)]
      jo = toJSObject ja
  in encodeStrict jo

-- | Logs an outgoing message.
logMsg
    :: (Show e, J.JSON e, MonadLog m)
    => Handler i o
    -> i                          -- ^ the received request (used for logging)
    -> GenericResult e J.JSValue  -- ^ A message to be sent
    -> m ()
logMsg handler req (Bad err) =
  logWarning $ "Failed to execute request " ++ hInputLogLong handler req ++ ": "
               ++ show err
logMsg handler req (Ok result) = do
  -- only log the first 2,000 chars of the result
  logDebug $ "Result (truncated): " ++ take 2000 (J.encode result)
  logInfo $ "Successfully handled " ++ hInputLogShort handler req

-- | Prepares an outgoing message.
prepareMsg
    :: (J.JSON e)
    => GenericResult e J.JSValue  -- ^ A message to be sent
    -> (Bool, J.JSValue)
prepareMsg (Bad err)   = (False, J.showJSON err)
prepareMsg (Ok result) = (True, result)


-- * Processing client requests

type HandlerResult o = IO (Bool, GenericResult GanetiException o)

data Handler i o = Handler
  { hParse         :: J.JSValue -> J.JSValue -> Result i
    -- ^ parses method and its arguments into the input type
  , hInputLogShort :: i -> String
    -- ^ short description of an input, for the INFO logging level
  , hInputLogLong  :: i -> String
    -- ^ long description of an input, for the DEBUG logging level
  , hExec          :: i -> HandlerResult o
    -- ^ executes the handler on an input
  }


handleJsonMessage
    :: (J.JSON o)
    => Handler i o              -- ^ handler
    -> i                        -- ^ parsed input
    -> HandlerResult J.JSValue
handleJsonMessage handler req = do
  (close, call_result) <- hExec handler req
  return (close, fmap J.showJSON call_result)

-- | Takes a request as a 'String', parses it, passes it to a handler and
-- formats its response.
handleRawMessage
    :: (J.JSON o)
    => Handler i o              -- ^ handler
    -> String                   -- ^ raw unparsed input
    -> IO (Bool, String)
handleRawMessage handler payload =
  case parseCall payload >>= uncurry (hParse handler) of
    Bad err -> do
         let errmsg = "Failed to parse request: " ++ err
         logWarning errmsg
         return (False, buildResponse False (J.showJSON errmsg))
    Ok req -> do
        logDebug $ "Request: " ++ hInputLogLong handler req
        (close, call_result_json) <- handleJsonMessage handler req
        logMsg handler req call_result_json
        let (status, response) = prepareMsg call_result_json
        return (close, buildResponse status response)

-- | Reads a request, passes it to a handler and sends a response back to the
-- client.
handleClient
    :: (J.JSON o)
    => Handler i o
    -> Client
    -> IO Bool
handleClient handler client = do
  msg <- recvMsgExt client
  logDebug $ "Received message: " ++ show msg
  case msg of
    RecvConnClosed -> logDebug "Connection closed" >>
                      return False
    RecvError err -> logWarning ("Error during message receiving: " ++ err) >>
                     return False
    RecvOk payload -> do
      (close, outMsg) <- handleRawMessage handler payload
      sendMsg client outMsg
      return close

-- | Main client loop: runs one loop of 'handleClient', and if that
-- doesn't report a finished (closed) connection, restarts itself.
clientLoop
    :: (J.JSON o)
    => Handler i o
    -> Client
    -> IO ()
clientLoop handler client = do
  result <- handleClient handler client
  if result
    then clientLoop handler client
    else closeClient client

-- | Main listener loop: accepts clients, forks an I/O thread to handle
-- that client.
listener
    :: (J.JSON o)
    => Handler i o
    -> Server
    -> IO ()
listener handler server = do
  client <- acceptClient server
  _ <- forkIO $ clientLoop handler client
  return ()

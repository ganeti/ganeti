{-# LANGUAGE TemplateHaskell #-}
{-# LANGUAGE FlexibleContexts #-}

{-| Implementation of the Ganeti Unix Domain Socket JSON server interface.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.UDSServer
  ( ConnectConfig(..)
  , ServerConfig(..)
  , Client
  , Server
  , RecvResult(..)
  , MsgKeys(..)
  , strOfKey
  -- * Unix sockets
  , openClientSocket
  , closeClientSocket
  , openServerSocket
  , closeServerSocket
  , acceptSocket
  -- * Client and server
  , connectClient
  , connectServer
  , pipeClient
  , acceptClient
  , closeClient
  , clientToFd
  , closeServer
  , buildResponse
  , parseResponse
  , buildCall
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
import Control.Concurrent.Lifted (fork, yield)
import Control.Monad.Base
import Control.Monad.Trans.Control
import Control.Exception (catch)
import Control.Monad
import qualified Data.ByteString as B
import qualified Data.ByteString.UTF8 as UTF8
import Data.IORef
import Data.List
import Data.Word (Word8)
import qualified Network.Socket as S
import System.Directory (removeFile)
import System.IO ( hClose, hFlush, hPutStr, hWaitForInput, Handle, IOMode(..)
                 , hSetBuffering, BufferMode(..))
import System.IO.Error (isEOFError)
import System.Posix.Types (Fd)
import System.Posix.IO (createPipe, fdToHandle, handleToFd)
import System.Timeout
import Text.JSON (encodeStrict, decodeStrict)
import qualified Text.JSON as J
import Text.JSON.Types

import Ganeti.BasicTypes
import Ganeti.Errors (GanetiException(..), ErrorResult)
import Ganeti.JSON (fromJResult, fromJVal, fromJResultE, fromObj)
import Ganeti.Logging
import Ganeti.THH
import Ganeti.Utils
import Ganeti.Constants (privateParametersBlacklist)

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


-- Information required for creating a server connection.
data ServerConfig = ServerConfig
                    { connPermissions :: FilePermissions
                    , connConfig :: ConnectConfig
                    }

-- Information required for creating a client or server connection.
data ConnectConfig = ConnectConfig
                     { recvTmo :: Int
                     , sendTmo :: Int
                     }

-- | A client encapsulation. Note that it has separate read and write handle.
-- For sockets it is the same handle. It is required for bi-directional
-- inter-process pipes though.
data Client = Client { rsocket :: Handle          -- ^ The read part of
                                                  -- the client socket
                     , wsocket :: Handle          -- ^ The write part of
                                                  -- the client socket
                     , rbuf :: IORef B.ByteString -- ^ Already received buffer
                     , clientConfig :: ConnectConfig
                     }

-- | A server encapsulation.
data Server = Server { sSocket :: S.Socket        -- ^ The bound server socket
                     , sPath :: FilePath          -- ^ The scoket's path
                     , serverConfig :: ConnectConfig
                     }

-- * Unix sockets

-- | Creates a Unix socket and connects it to the specified @path@,
-- where @timeout@ specifies the connection timeout.
openClientSocket
  :: Int              -- ^ connection timeout
  -> FilePath         -- ^ socket path
  -> IO Handle
openClientSocket tmo path = do
  sock <- S.socket S.AF_UNIX S.Stream S.defaultProtocol
  withTimeout tmo "creating a connection" $
              S.connect sock (S.SockAddrUnix path)
  S.socketToHandle sock ReadWriteMode

-- | Closes the handle.
-- Performing the operation on a handle that has already been closed has no
-- effect; doing so is not an error.
-- All other operations on a closed handle will fail.
closeClientSocket :: Handle -> IO ()
closeClientSocket = hClose

-- | Creates a Unix socket and binds it to the specified @path@.
openServerSocket :: FilePath -> IO S.Socket
openServerSocket path = do
  sock <- S.socket S.AF_UNIX S.Stream S.defaultProtocol
  S.bindSocket sock (S.SockAddrUnix path)
  return sock

closeServerSocket :: S.Socket -> FilePath -> IO ()
closeServerSocket sock path = do
  S.sClose sock
  removeFile path

acceptSocket :: S.Socket -> IO Handle
acceptSocket sock = do
  -- ignore client socket address
  (clientSock, _) <- S.accept sock
  S.socketToHandle clientSock ReadWriteMode

-- * Client and server

-- | Connects to the master daemon and returns a Client.
connectClient
  :: ConnectConfig    -- ^ configuration for the client
  -> Int              -- ^ connection timeout
  -> FilePath         -- ^ socket path
  -> IO Client
connectClient conf tmo path = do
  h <- openClientSocket tmo path
  rf <- newIORef B.empty
  return Client { rsocket=h, wsocket=h, rbuf=rf, clientConfig=conf }

-- | Creates and returns a server endpoint.
connectServer :: ServerConfig -> Bool -> FilePath -> IO Server
connectServer sconf setOwner path = do
  s <- openServerSocket path
  when setOwner $ do
    res <- ensurePermissions path (connPermissions sconf)
    exitIfBad "Error - could not set socket properties" res

  S.listen s 5 -- 5 is the max backlog
  return Server { sSocket = s, sPath = path, serverConfig = connConfig sconf }

-- | Creates a new bi-directional client pipe. The two returned clients
-- talk to each other through the pipe.
pipeClient :: ConnectConfig -> IO (Client, Client)
pipeClient conf =
  let newClient r w = do
        rf <- newIORef B.empty
        rh <- fdToHandle r
        wh <- fdToHandle w
        return Client { rsocket = rh, wsocket = wh
                      , rbuf = rf, clientConfig = conf }
  in do
    (r1, w1) <- createPipe
    (r2, w2) <- createPipe
    (,) <$> newClient r1 w2 <*> newClient r2 w1

-- | Closes a server endpoint.
closeServer :: (MonadBase IO m) => Server -> m ()
closeServer server =
  liftBase $ closeServerSocket (sSocket server) (sPath server)

-- | Accepts a client
acceptClient :: Server -> IO Client
acceptClient s = do
  handle <- acceptSocket (sSocket s)
  new_buffer <- newIORef B.empty
  return Client { rsocket=handle
                , wsocket=handle
                , rbuf=new_buffer
                , clientConfig=serverConfig s
                }

-- | Closes the client socket.
-- Performing the operation on a client that has already been closed has no
-- effect; doing so is not an error.
-- All other operations on a closed client will fail with an exception.
closeClient :: Client -> IO ()
closeClient client = do
  closeClientSocket . wsocket $ client
  closeClientSocket . rsocket $ client

-- | Extracts the read (the first) and the write (the second) file descriptor
-- of a client. This closes the underlying 'Handle's, therefore the original
-- client is closed and unusable after the call.
--
-- The purpose of this function is to keep the communication channel open,
-- while replacing a 'Client' with some other means.
clientToFd :: Client -> IO (Fd, Fd)
clientToFd client | rh == wh  = join (,) <$> handleToFd rh
                  | otherwise = (,) <$> handleToFd rh <*> handleToFd wh
  where
    rh = rsocket client
    wh = wsocket client

-- | Sends a message over a transport.
sendMsg :: Client -> String -> IO ()
sendMsg s buf = withTimeout (sendTmo $ clientConfig s) "sending a message" $ do
  t1 <- getCurrentTimeUSec
  let handle = wsocket s
  -- Allow buffering (up to 1MiB) when writing to the socket. Note that
  -- otherwise we get the default of sending each byte in a separate
  -- system call, resulting in very poor performance.
  hSetBuffering handle (BlockBuffering . Just $ 1024 * 1024)
  hPutStr handle buf
  B.hPut handle bEOM
  hFlush handle
  t2 <- getCurrentTimeUSec
  logDebug $ "sendMsg: " ++ show ((t2 - t1) `div` 1000) ++ "ms"

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
    else return (newbuf, B.copy (B.tail remaining))

-- | Waits for a message over a transport.
recvMsg :: Client -> IO String
recvMsg s = do
  cbuf <- readIORef $ rbuf s
  let (imsg, ibuf) = B.break (eOM ==) cbuf
  (msg, nbuf) <-
    if B.null ibuf      -- if old buffer didn't contain a full message
                        -- then we read from network:
      then recvUpdate (clientConfig s) (rsocket s) cbuf
      -- else we return data from our buffer, copying it so that the whole
      -- message isn't retained and can be garbage collected
      else return (imsg, B.copy (B.tail ibuf))
  writeIORef (rbuf s) nbuf
  return $ UTF8.toString msg

-- | Extended wrapper over recvMsg.
recvMsgExt :: Client -> IO RecvResult
recvMsgExt s =
  Control.Exception.catch (liftM RecvOk (recvMsg s)) $ \e ->
    return $ if isEOFError e
               then RecvConnClosed
               else RecvError (show e)


-- | Serialize a request to String.
buildCall :: (J.JSON mth, J.JSON args)
          => mth    -- ^ The method
          -> args   -- ^ The arguments
          -> String -- ^ The serialized form
buildCall mth args =
  let keyToObj :: (J.JSON a) => MsgKeys -> a -> (String, J.JSValue)
      keyToObj k v = (strOfKey k, J.showJSON v)
  in encodeStrict $ toJSObject [ keyToObj Method mth, keyToObj Args args ]

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

-- | Try to decode an error from the server response. This function
-- will always fail, since it's called only on the error path (when
-- status is False).
decodeError :: JSValue -> ErrorResult JSValue
decodeError val =
  case fromJVal val of
    Ok e -> Bad e
    Bad msg -> Bad $ GenericError msg

-- | Check that luxi responses contain the required keys and that the
-- call was successful.
parseResponse :: String -> ErrorResult JSValue
parseResponse s = do
  when (UTF8.replacement_char `elem` s) $
      failError "Failed to decode UTF-8,\
                \ detected replacement char after decoding"
  oarr <- fromJResultE "Parsing LUXI response" (decodeStrict s)
  let arr = J.fromJSObject oarr
  status <- fromObj arr (strOfKey Success)
  result <- fromObj arr (strOfKey Result)
  if status
    then return result
    else decodeError result

-- | Logs an outgoing message.
logMsg
    :: (Show e, J.JSON e, MonadLog m)
    => Handler i m o
    -> i                          -- ^ the received request (used for logging)
    -> GenericResult e J.JSValue  -- ^ A message to be sent
    -> m ()
logMsg handler req (Bad err) =
  logWarning $ "Failed to execute request " ++ hInputLogLong handler req ++ ": "
               ++ show err
logMsg handler req (Ok result) = do
  -- only log the first 2,000 chars of the result
  logDebug $ "Result (truncated): " ++ take 2000 (J.encode result)
  logDebug $ "Successfully handled " ++ hInputLogShort handler req

-- | Prepares an outgoing message.
prepareMsg
    :: (J.JSON e)
    => GenericResult e J.JSValue  -- ^ A message to be sent
    -> (Bool, J.JSValue)
prepareMsg (Bad err)   = (False, J.showJSON err)
prepareMsg (Ok result) = (True, result)


-- * Processing client requests

type HandlerResult m o = m (Bool, GenericResult GanetiException o)

data Handler i m o = Handler
  { hParse         :: J.JSValue -> J.JSValue -> Result i
    -- ^ parses method and its arguments into the input type
  , hInputLogShort :: i -> String
    -- ^ short description of an input, for the INFO logging level
  , hInputLogLong  :: i -> String
    -- ^ long description of an input, for the DEBUG logging level
  , hExec          :: i -> HandlerResult m o
    -- ^ executes the handler on an input
  }


handleJsonMessage
    :: (J.JSON o, Monad m)
    => Handler i m o            -- ^ handler
    -> i                        -- ^ parsed input
    -> HandlerResult m J.JSValue
handleJsonMessage handler req = do
  (close, call_result) <- hExec handler req
  return (close, fmap J.showJSON call_result)

-- | Takes a request as a 'String', parses it, passes it to a handler and
-- formats its response.
handleRawMessage
    :: (J.JSON o, MonadLog m)
    => Handler i m o            -- ^ handler
    -> String                   -- ^ raw unparsed input
    -> m (Bool, String)
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

isRisky :: RecvResult -> Bool
isRisky msg = case msg of
  RecvOk payload -> any (`isInfixOf` payload) privateParametersBlacklist
  _ -> False

-- | Reads a request, passes it to a handler and sends a response back to the
-- client.
handleClient
    :: (J.JSON o, MonadBase IO m, MonadLog m)
    => Handler i m o
    -> Client
    -> m Bool
handleClient handler client = do
  msg <- liftBase $ recvMsgExt client

  debugMode <- liftBase isDebugMode
  when (debugMode && isRisky msg) $
    logAlert "POSSIBLE LEAKING OF CONFIDENTIAL PARAMETERS. \
             \Daemon is running in debug mode. \
             \The text of the request has been logged."
  logDebug $ "Received message (truncated): " ++ take 500 (show msg)

  case msg of
    RecvConnClosed -> logDebug "Connection closed" >>
                      return False
    RecvError err -> logWarning ("Error during message receiving: " ++ err) >>
                     return False
    RecvOk payload -> do
      (close, outMsg) <- handleRawMessage handler payload
      liftBase $ sendMsg client outMsg
      return close


-- | Main client loop: runs one loop of 'handleClient', and if that
-- doesn't report a finished (closed) connection, restarts itself.
clientLoop
    :: (J.JSON o, MonadBase IO m, MonadLog m)
    => Handler i m o
    -> Client
    -> m ()
clientLoop handler client = do
  result <- handleClient handler client
  {- It's been observed sometimes that reading immediately after sending
     a response leads to worse performance, as there is nothing to read and
     the system calls are just wasted. Thus yielding before reading gives
     other threads a chance to proceed and provides a natural pause, leading
     to a bit more efficient communication.
  -}
  if result
    then yield >> clientLoop handler client
    else liftBase $ closeClient client

-- | Main listener loop: accepts clients, forks an I/O thread to handle
-- that client.
listener
    :: (J.JSON o, MonadBaseControl IO m, MonadLog m)
    => Handler i m o
    -> Server
    -> m ()
listener handler server = do
  client <- liftBase $ acceptClient server
  _ <- fork $ clientLoop handler client
  return ()

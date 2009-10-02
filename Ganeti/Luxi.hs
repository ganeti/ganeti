{-| Implementation of the Ganeti LUXI interface.

-}

{-

Copyright (C) 2009 Google Inc.

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

module Ganeti.Luxi
    ( LuxiOp(..)
    , Client
    , getClient
    , closeClient
    , callMethod
    ) where

import Data.List
import Data.IORef
import Control.Monad
import Text.JSON (JSObject, JSValue, toJSObject, encodeStrict, decodeStrict)
import qualified Text.JSON as J
import Text.JSON.Types
import System.Timeout
import qualified Network.Socket as S

import Ganeti.HTools.Utils
import Ganeti.HTools.Types

-- * Utility functions

-- | Wrapper over System.Timeout.timeout that fails in the IO monad.
withTimeout :: Int -> String -> IO a -> IO a
withTimeout secs descr action = do
    result <- timeout (secs * 1000000) action
    (case result of
       Nothing -> fail $ "Timeout in " ++ descr
       Just v -> return v)

-- * Generic protocol functionality

-- | Currently supported Luxi operations.
data LuxiOp = QueryInstances
            | QueryNodes
            | QueryJobs
            | SubmitManyJobs

-- | The serialisation of LuxiOps into strings in messages.
strOfOp :: LuxiOp -> String
strOfOp QueryNodes = "QueryNodes"
strOfOp QueryInstances = "QueryInstances"
strOfOp QueryJobs = "QueryJobs"
strOfOp SubmitManyJobs = "SubmitManyJobs"

-- | The end-of-message separator.
eOM :: Char
eOM = '\3'

-- | Valid keys in the requests and responses.
data MsgKeys = Method
             | Args
             | Success
             | Result

-- | The serialisation of MsgKeys into strings in messages.
strOfKey :: MsgKeys -> String
strOfKey Method = "method"
strOfKey Args = "args"
strOfKey Success = "success"
strOfKey Result = "result"

-- | Luxi client encapsulation.
data Client = Client { socket :: S.Socket   -- ^ The socket of the client
                     , rbuf :: IORef String -- ^ Already received buffer
                     }

-- | Connects to the master daemon and returns a luxi Client.
getClient :: String -> IO Client
getClient path = do
    s <- S.socket S.AF_UNIX S.Stream S.defaultProtocol
    withTimeout connTimeout "creating luxi connection" $
                S.connect s (S.SockAddrUnix path)
    rf <- newIORef ""
    return Client { socket=s, rbuf=rf}

-- | Closes the client socket.
closeClient :: Client -> IO ()
closeClient = S.sClose . socket

-- | Sends a message over a luxi transport.
sendMsg :: Client -> String -> IO ()
sendMsg s buf =
    let _send obuf = do
          sbytes <- withTimeout queryTimeout
                    "sending luxi message" $
                    S.send (socket s) obuf
          (if sbytes == length obuf
           then return ()
           else _send (drop sbytes obuf))
    in _send (buf ++ [eOM])

-- | Waits for a message over a luxi transport.
recvMsg :: Client -> IO String
recvMsg s = do
  let _recv obuf = do
              nbuf <- withTimeout queryTimeout "reading luxi response" $
                      S.recv (socket s) 4096
              let (msg, remaining) = break ((==) eOM) (obuf ++ nbuf)
              (if null remaining
               then _recv msg
               else return (msg, tail remaining))
  cbuf <- readIORef $ rbuf s
  (msg, nbuf) <- _recv cbuf
  writeIORef (rbuf s) nbuf
  return msg

-- | Serialize a request to String.
buildCall :: LuxiOp  -- ^ The method
          -> JSValue -- ^ The arguments
          -> String  -- ^ The serialized form
buildCall msg args =
    let ja = [(strOfKey Method,
               JSString $ toJSString $ strOfOp msg::JSValue),
              (strOfKey Args,
               args::JSValue)
             ]
        jo = toJSObject ja
    in encodeStrict jo

-- | Check that luxi responses contain the required keys and that the
-- call was successful.
validateResult :: String -> Result JSValue
validateResult s = do
  arr <- fromJResult $ decodeStrict s::Result (JSObject JSValue)
  status <- fromObj (strOfKey Success) arr::Result Bool
  let rkey = strOfKey Result
  (if status
   then fromObj rkey arr
   else fromObj rkey arr >>= fail)

-- | Generic luxi method call.
callMethod :: LuxiOp -> JSValue -> Client -> IO (Result JSValue)
callMethod method args s = do
  sendMsg s $ buildCall method args
  result <- recvMsg s
  let rval = validateResult result
  return rval

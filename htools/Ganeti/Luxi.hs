{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti LUXI interface.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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
  , LuxiReq(..)
  , Client
  , JobId
  , fromJobId
  , makeJobId
  , RecvResult(..)
  , strOfOp
  , getClient
  , getServer
  , acceptClient
  , closeClient
  , closeServer
  , callMethod
  , submitManyJobs
  , queryJobsStatus
  , buildCall
  , buildResponse
  , validateCall
  , decodeCall
  , recvMsg
  , recvMsgExt
  , sendMsg
  , allLuxiCalls
  ) where

import Control.Exception (catch)
import Data.IORef
import qualified Data.ByteString as B
import qualified Data.ByteString.Lazy as BL
import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.ByteString.Lazy.UTF8 as UTF8L
import Data.Word (Word8)
import Control.Monad
import Text.JSON (encodeStrict, decodeStrict)
import qualified Text.JSON as J
import Text.JSON.Pretty (pp_value)
import Text.JSON.Types
import System.Directory (removeFile)
import System.IO (hClose, hFlush, hWaitForInput, Handle, IOMode(..))
import System.IO.Error (isEOFError)
import System.Timeout
import qualified Network.Socket as S

import Ganeti.BasicTypes
import Ganeti.Constants
import Ganeti.Errors
import Ganeti.JSON
import Ganeti.OpParams (pTagsObject)
import Ganeti.OpCodes
import qualified Ganeti.Query.Language as Qlang
import Ganeti.THH
import Ganeti.Types

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

-- | Currently supported Luxi operations and JSON serialization.
$(genLuxiOp "LuxiOp"
  [ (luxiReqQuery,
    [ simpleField "what"    [t| Qlang.ItemType |]
    , simpleField "fields"  [t| [String]  |]
    , simpleField "qfilter" [t| Qlang.Filter Qlang.FilterField |]
    ])
  , (luxiReqQueryFields,
    [ simpleField "what"    [t| Qlang.ItemType |]
    , simpleField "fields"  [t| [String]  |]
    ])
  , (luxiReqQueryNodes,
     [ simpleField "names"  [t| [String] |]
     , simpleField "fields" [t| [String] |]
     , simpleField "lock"   [t| Bool     |]
     ])
  , (luxiReqQueryGroups,
     [ simpleField "names"  [t| [String] |]
     , simpleField "fields" [t| [String] |]
     , simpleField "lock"   [t| Bool     |]
     ])
  , (luxiReqQueryInstances,
     [ simpleField "names"  [t| [String] |]
     , simpleField "fields" [t| [String] |]
     , simpleField "lock"   [t| Bool     |]
     ])
  , (luxiReqQueryJobs,
     [ simpleField "ids"    [t| [JobId]  |]
     , simpleField "fields" [t| [String] |]
     ])
  , (luxiReqQueryExports,
     [ simpleField "nodes" [t| [String] |]
     , simpleField "lock"  [t| Bool     |]
     ])
  , (luxiReqQueryConfigValues,
     [ simpleField "fields" [t| [String] |] ]
    )
  , (luxiReqQueryClusterInfo, [])
  , (luxiReqQueryTags,
     [ pTagsObject ])
  , (luxiReqSubmitJob,
     [ simpleField "job" [t| [MetaOpCode] |] ]
    )
  , (luxiReqSubmitManyJobs,
     [ simpleField "ops" [t| [[MetaOpCode]] |] ]
    )
  , (luxiReqWaitForJobChange,
     [ simpleField "job"      [t| JobId   |]
     , simpleField "fields"   [t| [String]|]
     , simpleField "prev_job" [t| JSValue |]
     , simpleField "prev_log" [t| JSValue |]
     , simpleField "tmout"    [t| Int     |]
     ])
  , (luxiReqArchiveJob,
     [ simpleField "job" [t| JobId |] ]
    )
  , (luxiReqAutoArchiveJobs,
     [ simpleField "age"   [t| Int |]
     , simpleField "tmout" [t| Int |]
     ])
  , (luxiReqCancelJob,
     [ simpleField "job" [t| JobId |] ]
    )
  , (luxiReqChangeJobPriority,
     [ simpleField "job"      [t| JobId |]
     , simpleField "priority" [t| Int |] ]
    )
  , (luxiReqSetDrainFlag,
     [ simpleField "flag" [t| Bool |] ]
    )
  , (luxiReqSetWatcherPause,
     [ simpleField "duration" [t| Double |] ]
    )
  ])

$(makeJSONInstance ''LuxiReq)

-- | List of all defined Luxi calls.
$(genAllConstr (drop 3) ''LuxiReq "allLuxiCalls")

-- | The serialisation of LuxiOps into strings in messages.
$(genStrOfOp ''LuxiOp "strOfOp")

-- | Type holding the initial (unparsed) Luxi call.
data LuxiCall = LuxiCall LuxiReq JSValue

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

-- | Luxi client encapsulation.
data Client = Client { socket :: Handle           -- ^ The socket of the client
                     , rbuf :: IORef B.ByteString -- ^ Already received buffer
                     }

-- | Connects to the master daemon and returns a luxi Client.
getClient :: String -> IO Client
getClient path = do
  s <- S.socket S.AF_UNIX S.Stream S.defaultProtocol
  withTimeout luxiDefCtmo "creating luxi connection" $
              S.connect s (S.SockAddrUnix path)
  rf <- newIORef B.empty
  h <- S.socketToHandle s ReadWriteMode
  return Client { socket=h, rbuf=rf }

-- | Creates and returns a server endpoint.
getServer :: FilePath -> IO S.Socket
getServer path = do
  s <- S.socket S.AF_UNIX S.Stream S.defaultProtocol
  S.bindSocket s (S.SockAddrUnix path)
  S.listen s 5 -- 5 is the max backlog
  return s

-- | Closes a server endpoint.
-- FIXME: this should be encapsulated into a nicer type.
closeServer :: FilePath -> S.Socket -> IO ()
closeServer path sock = do
  S.sClose sock
  removeFile path

-- | Accepts a client
acceptClient :: S.Socket -> IO Client
acceptClient s = do
  -- second return is the address of the client, which we ignore here
  (client_socket, _) <- S.accept s
  new_buffer <- newIORef B.empty
  handle <- S.socketToHandle client_socket ReadWriteMode
  return Client { socket=handle, rbuf=new_buffer }

-- | Closes the client socket.
closeClient :: Client -> IO ()
closeClient = hClose . socket

-- | Sends a message over a luxi transport.
sendMsg :: Client -> String -> IO ()
sendMsg s buf = withTimeout luxiDefRwto "sending luxi message" $ do
  let encoded = UTF8L.fromString buf
      handle = socket s
  BL.hPut handle encoded
  B.hPut handle bEOM
  hFlush handle

-- | Given a current buffer and the handle, it will read from the
-- network until we get a full message, and it will return that
-- message and the leftover buffer contents.
recvUpdate :: Handle -> B.ByteString -> IO (B.ByteString, B.ByteString)
recvUpdate handle obuf = do
  nbuf <- withTimeout luxiDefRwto "reading luxi response" $ do
            _ <- hWaitForInput handle (-1)
            B.hGetNonBlocking handle 4096
  let (msg, remaining) = B.break (eOM ==) nbuf
      newbuf = B.append obuf msg
  if B.null remaining
    then recvUpdate handle newbuf
    else return (newbuf, B.tail remaining)

-- | Waits for a message over a luxi transport.
recvMsg :: Client -> IO String
recvMsg s = do
  cbuf <- readIORef $ rbuf s
  let (imsg, ibuf) = B.break (eOM ==) cbuf
  (msg, nbuf) <-
    if B.null ibuf      -- if old buffer didn't contain a full message
      then recvUpdate (socket s) cbuf   -- then we read from network
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

-- | Serialize a request to String.
buildCall :: LuxiOp  -- ^ The method
          -> String  -- ^ The serialized form
buildCall lo =
  let ja = [ (strOfKey Method, J.showJSON $ strOfOp lo)
           , (strOfKey Args, opToArgs lo)
           ]
      jo = toJSObject ja
  in encodeStrict jo

-- | Serialize the response to String.
buildResponse :: Bool    -- ^ Success
              -> JSValue -- ^ The arguments
              -> String  -- ^ The serialized form
buildResponse success args =
  let ja = [ (strOfKey Success, JSBool success)
           , (strOfKey Result, args)]
      jo = toJSObject ja
  in encodeStrict jo

-- | Check that luxi request contains the required keys and parse it.
validateCall :: String -> Result LuxiCall
validateCall s = do
  arr <- fromJResult "parsing top-level luxi message" $
         decodeStrict s::Result (JSObject JSValue)
  let aobj = fromJSObject arr
  call <- fromObj aobj (strOfKey Method)::Result LuxiReq
  args <- fromObj aobj (strOfKey Args)
  return (LuxiCall call args)

-- | Converts Luxi call arguments into a 'LuxiOp' data structure.
--
-- This is currently hand-coded until we make it more uniform so that
-- it can be generated using TH.
decodeCall :: LuxiCall -> Result LuxiOp
decodeCall (LuxiCall call args) =
  case call of
    ReqQueryJobs -> do
              (jids, jargs) <- fromJVal args
              jids' <- case jids of
                         JSNull -> return []
                         _ -> fromJVal jids
              return $ QueryJobs jids' jargs
    ReqQueryInstances -> do
              (names, fields, locking) <- fromJVal args
              return $ QueryInstances names fields locking
    ReqQueryNodes -> do
              (names, fields, locking) <- fromJVal args
              return $ QueryNodes names fields locking
    ReqQueryGroups -> do
              (names, fields, locking) <- fromJVal args
              return $ QueryGroups names fields locking
    ReqQueryClusterInfo ->
              return QueryClusterInfo
    ReqQuery -> do
              (what, fields, qfilter) <- fromJVal args
              return $ Query what fields qfilter
    ReqQueryFields -> do
              (what, fields) <- fromJVal args
              fields' <- case fields of
                           JSNull -> return []
                           _ -> fromJVal fields
              return $ QueryFields what fields'
    ReqSubmitJob -> do
              [ops1] <- fromJVal args
              ops2 <- mapM (fromJResult (luxiReqToRaw call) . J.readJSON) ops1
              return $ SubmitJob ops2
    ReqSubmitManyJobs -> do
              [ops1] <- fromJVal args
              ops2 <- mapM (fromJResult (luxiReqToRaw call) . J.readJSON) ops1
              return $ SubmitManyJobs ops2
    ReqWaitForJobChange -> do
              (jid, fields, pinfo, pidx, wtmout) <-
                -- No instance for 5-tuple, code copied from the
                -- json sources and adapted
                fromJResult "Parsing WaitForJobChange message" $
                case args of
                  JSArray [a, b, c, d, e] ->
                    (,,,,) `fmap`
                    J.readJSON a `ap`
                    J.readJSON b `ap`
                    J.readJSON c `ap`
                    J.readJSON d `ap`
                    J.readJSON e
                  _ -> J.Error "Not enough values"
              return $ WaitForJobChange jid fields pinfo pidx wtmout
    ReqArchiveJob -> do
              [jid] <- fromJVal args
              return $ ArchiveJob jid
    ReqAutoArchiveJobs -> do
              (age, tmout) <- fromJVal args
              return $ AutoArchiveJobs age tmout
    ReqQueryExports -> do
              (nodes, lock) <- fromJVal args
              return $ QueryExports nodes lock
    ReqQueryConfigValues -> do
              [fields] <- fromJVal args
              return $ QueryConfigValues fields
    ReqQueryTags -> do
              (kind, name) <- fromJVal args
              item <- tagObjectFrom kind name
              return $ QueryTags item
    ReqCancelJob -> do
              [jid] <- fromJVal args
              return $ CancelJob jid
    ReqChangeJobPriority -> do
              (jid, priority) <- fromJVal args
              return $ ChangeJobPriority jid priority
    ReqSetDrainFlag -> do
              [flag] <- fromJVal args
              return $ SetDrainFlag flag
    ReqSetWatcherPause -> do
              [duration] <- fromJVal args
              return $ SetWatcherPause duration

-- | Check that luxi responses contain the required keys and that the
-- call was successful.
validateResult :: String -> ErrorResult JSValue
validateResult s = do
  when (UTF8.replacement_char `elem` s) $
       fail "Failed to decode UTF-8, detected replacement char after decoding"
  oarr <- fromJResult "Parsing LUXI response" (decodeStrict s)
  let arr = J.fromJSObject oarr
  status <- fromObj arr (strOfKey Success)
  result <- fromObj arr (strOfKey Result)
  if status
    then return result
    else decodeError result

-- | Try to decode an error from the server response. This function
-- will always fail, since it's called only on the error path (when
-- status is False).
decodeError :: JSValue -> ErrorResult JSValue
decodeError val =
  case fromJVal val of
    Ok e -> Bad e
    Bad msg -> Bad $ GenericError msg

-- | Generic luxi method call.
callMethod :: LuxiOp -> Client -> IO (ErrorResult JSValue)
callMethod method s = do
  sendMsg s $ buildCall method
  result <- recvMsg s
  let rval = validateResult result
  return rval

-- | Parse job submission result.
parseSubmitJobResult :: JSValue -> ErrorResult JobId
parseSubmitJobResult (JSArray [JSBool True, v]) =
  case J.readJSON v of
    J.Error msg -> Bad $ LuxiError msg
    J.Ok v' -> Ok v'
parseSubmitJobResult (JSArray [JSBool False, JSString x]) =
  Bad . LuxiError $ fromJSString x
parseSubmitJobResult v =
  Bad . LuxiError $ "Unknown result from the master daemon: " ++
      show (pp_value v)

-- | Specialized submitManyJobs call.
submitManyJobs :: Client -> [[MetaOpCode]] -> IO (ErrorResult [JobId])
submitManyJobs s jobs = do
  rval <- callMethod (SubmitManyJobs jobs) s
  -- map each result (status, payload) pair into a nice Result ADT
  return $ case rval of
             Bad x -> Bad x
             Ok (JSArray r) -> mapM parseSubmitJobResult r
             x -> Bad . LuxiError $
                  "Cannot parse response from Ganeti: " ++ show x

-- | Custom queryJobs call.
queryJobsStatus :: Client -> [JobId] -> IO (ErrorResult [JobStatus])
queryJobsStatus s jids = do
  rval <- callMethod (QueryJobs jids ["status"]) s
  return $ case rval of
             Bad x -> Bad x
             Ok y -> case J.readJSON y::(J.Result [[JobStatus]]) of
                       J.Ok vals -> if any null vals
                                    then Bad $
                                         LuxiError "Missing job status field"
                                    else Ok (map head vals)
                       J.Error x -> Bad $ LuxiError x

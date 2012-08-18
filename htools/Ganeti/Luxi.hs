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
  , QrViaLuxi(..)
  , ResultStatus(..)
  , LuxiReq(..)
  , Client
  , JobId
  , RecvResult(..)
  , strOfOp
  , checkRS
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
  ) where

import Control.Exception (catch)
import Data.IORef
import Data.Ratio (numerator, denominator)
import qualified Data.ByteString as B
import qualified Data.ByteString.UTF8 as UTF8
import Data.Word (Word8)
import Control.Monad
import Prelude hiding (catch)
import Text.JSON (encodeStrict, decodeStrict)
import qualified Text.JSON as J
import Text.JSON.Types
import System.Directory (removeFile)
import System.IO (hClose, hFlush, hWaitForInput, Handle, IOMode(..))
import System.IO.Error (isEOFError)
import System.Timeout
import qualified Network.Socket as S

import Ganeti.HTools.JSON
import Ganeti.HTools.Types
import Ganeti.HTools.Utils

import Ganeti.Constants
import Ganeti.Jobs (JobStatus)
import Ganeti.OpCodes (OpCode)
import Ganeti.THH

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
                  deriving (Show, Read, Eq)

-- | The Ganeti job type.
type JobId = Int

$(declareSADT "QrViaLuxi"
  [ ("QRLock", 'qrLock)
  , ("QRInstance", 'qrInstance)
  , ("QRNode", 'qrNode)
  , ("QRGroup", 'qrGroup)
  , ("QROs", 'qrOs)
  ])
$(makeJSONInstance ''QrViaLuxi)

-- | Currently supported Luxi operations and JSON serialization.
$(genLuxiOp "LuxiOp"
  [(luxiReqQuery,
    [ ("what",    [t| QrViaLuxi |], [| id |])
    , ("fields",  [t| [String]  |], [| id |])
    , ("qfilter", [t| ()        |], [| const JSNull |])
    ])
  , (luxiReqQueryNodes,
     [ ("names",  [t| [String] |], [| id |])
     , ("fields", [t| [String] |], [| id |])
     , ("lock",   [t| Bool     |], [| id |])
     ])
  , (luxiReqQueryGroups,
     [ ("names",  [t| [String] |], [| id |])
     , ("fields", [t| [String] |], [| id |])
     , ("lock",   [t| Bool     |], [| id |])
     ])
  , (luxiReqQueryInstances,
     [ ("names",  [t| [String] |], [| id |])
     , ("fields", [t| [String] |], [| id |])
     , ("lock",   [t| Bool     |], [| id |])
     ])
  , (luxiReqQueryJobs,
     [ ("ids",    [t| [Int]    |], [| id |])
     , ("fields", [t| [String] |], [| id |])
     ])
  , (luxiReqQueryExports,
     [ ("nodes", [t| [String] |], [| id |])
     , ("lock",  [t| Bool     |], [| id |])
     ])
  , (luxiReqQueryConfigValues,
     [ ("fields", [t| [String] |], [| id |]) ]
    )
  , (luxiReqQueryClusterInfo, [])
  , (luxiReqQueryTags,
     [ ("kind", [t| String |], [| id |])
     , ("name", [t| String |], [| id |])
     ])
  , (luxiReqSubmitJob,
     [ ("job", [t| [OpCode] |], [| id |]) ]
    )
  , (luxiReqSubmitManyJobs,
     [ ("ops", [t| [[OpCode]] |], [| id |]) ]
    )
  , (luxiReqWaitForJobChange,
     [ ("job",      [t| Int     |], [| id |])
     , ("fields",   [t| [String]|], [| id |])
     , ("prev_job", [t| JSValue |], [| id |])
     , ("prev_log", [t| JSValue |], [| id |])
     , ("tmout",    [t| Int     |], [| id |])
     ])
  , (luxiReqArchiveJob,
     [ ("job", [t| Int |], [| id |]) ]
    )
  , (luxiReqAutoArchiveJobs,
     [ ("age",   [t| Int |], [| id |])
     , ("tmout", [t| Int |], [| id |])
     ])
  , (luxiReqCancelJob,
     [ ("job", [t| Int |], [| id |]) ]
    )
  , (luxiReqSetDrainFlag,
     [ ("flag", [t| Bool |], [| id |]) ]
    )
  , (luxiReqSetWatcherPause,
     [ ("duration", [t| Double |], [| id |]) ]
    )
  ])

$(makeJSONInstance ''LuxiReq)

-- | The serialisation of LuxiOps into strings in messages.
$(genStrOfOp ''LuxiOp "strOfOp")

$(declareIADT "ResultStatus"
  [ ("RSNormal", 'rsNormal)
  , ("RSUnknown", 'rsUnknown)
  , ("RSNoData", 'rsNodata)
  , ("RSUnavailable", 'rsUnavail)
  , ("RSOffline", 'rsOffline)
  ])

$(makeJSONInstance ''ResultStatus)

-- | Type holding the initial (unparsed) Luxi call.
data LuxiCall = LuxiCall LuxiReq JSValue

-- | Check that ResultStatus is success or fail with descriptive message.
checkRS :: (Monad m) => ResultStatus -> a -> m a
checkRS RSNormal val    = return val
checkRS RSUnknown _     = fail "Unknown field"
checkRS RSNoData _      = fail "No data for a field"
checkRS RSUnavailable _ = fail "Ganeti reports unavailable data"
checkRS RSOffline _     = fail "Ganeti reports resource as offline"

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
  withTimeout connTimeout "creating luxi connection" $
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
sendMsg s buf = withTimeout queryTimeout "sending luxi message" $ do
  let encoded = UTF8.fromString buf
      handle = socket s
  B.hPut handle encoded
  B.hPut handle bEOM
  hFlush handle

-- | Given a current buffer and the handle, it will read from the
-- network until we get a full message, and it will return that
-- message and the leftover buffer contents.
recvUpdate :: Handle -> B.ByteString -> IO (B.ByteString, B.ByteString)
recvUpdate handle obuf = do
  nbuf <- withTimeout queryTimeout "reading luxi response" $ do
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
  catch (liftM RecvOk (recvMsg s)) $ \e ->
    if isEOFError e
      then return RecvConnClosed
      else return $ RecvError (show e)

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
              (jid, jargs) <- fromJVal args
              rid <- mapM parseJobId jid
              let rargs = map fromJSString jargs
              return $ QueryJobs rid rargs
    ReqQueryInstances -> do
              (names, fields, locking) <- fromJVal args
              return $ QueryInstances names fields locking
    ReqQueryNodes -> do
              (names, fields, locking) <- fromJVal args
              return $ QueryNodes names fields locking
    ReqQueryGroups -> do
              (names, fields, locking) <- fromJVal args
              return $ QueryGroups names fields locking
    ReqQueryClusterInfo -> do
              return QueryClusterInfo
    ReqQuery -> do
              (what, fields, _) <-
                fromJVal args::Result (QrViaLuxi, [String], JSValue)
              return $ Query what fields ()
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
              rid <- parseJobId jid
              return $ WaitForJobChange rid fields pinfo pidx wtmout
    ReqArchiveJob -> do
              [jid] <- fromJVal args
              rid <- parseJobId jid
              return $ ArchiveJob rid
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
              return $ QueryTags kind name
    ReqCancelJob -> do
              [job] <- fromJVal args
              rid <- parseJobId job
              return $ CancelJob rid
    ReqSetDrainFlag -> do
              [flag] <- fromJVal args
              return $ SetDrainFlag flag
    ReqSetWatcherPause -> do
              [duration] <- fromJVal args
              return $ SetWatcherPause duration

-- | Check that luxi responses contain the required keys and that the
-- call was successful.
validateResult :: String -> Result JSValue
validateResult s = do
  when (UTF8.replacement_char `elem` s) $
       fail "Failed to decode UTF-8, detected replacement char after decoding"
  oarr <- fromJResult "Parsing LUXI response"
          (decodeStrict s)::Result (JSObject JSValue)
  let arr = J.fromJSObject oarr
  status <- fromObj arr (strOfKey Success)::Result Bool
  let rkey = strOfKey Result
  if status
    then fromObj arr rkey
    else fromObj arr rkey >>= fail

-- | Generic luxi method call.
callMethod :: LuxiOp -> Client -> IO (Result JSValue)
callMethod method s = do
  sendMsg s $ buildCall method
  result <- recvMsg s
  let rval = validateResult result
  return rval

-- | Parses a job ID.
parseJobId :: JSValue -> Result JobId
parseJobId (JSString x) = tryRead "parsing job id" . fromJSString $ x
parseJobId (JSRational _ x) =
  if denominator x /= 1
    then Bad $ "Got fractional job ID from master daemon?! Value:" ++ show x
    -- FIXME: potential integer overflow here on 32-bit platforms
    else Ok . fromIntegral . numerator $ x
parseJobId x = Bad $ "Wrong type/value for job id: " ++ show x

-- | Parse job submission result.
parseSubmitJobResult :: JSValue -> Result JobId
parseSubmitJobResult (JSArray [JSBool True, v]) = parseJobId v
parseSubmitJobResult (JSArray [JSBool False, JSString x]) =
  Bad (fromJSString x)
parseSubmitJobResult v = Bad $ "Unknown result from the master daemon" ++
                         show v

-- | Specialized submitManyJobs call.
submitManyJobs :: Client -> [[OpCode]] -> IO (Result [JobId])
submitManyJobs s jobs = do
  rval <- callMethod (SubmitManyJobs jobs) s
  -- map each result (status, payload) pair into a nice Result ADT
  return $ case rval of
             Bad x -> Bad x
             Ok (JSArray r) -> mapM parseSubmitJobResult r
             x -> Bad ("Cannot parse response from Ganeti: " ++ show x)

-- | Custom queryJobs call.
queryJobsStatus :: Client -> [JobId] -> IO (Result [JobStatus])
queryJobsStatus s jids = do
  rval <- callMethod (QueryJobs jids ["status"]) s
  return $ case rval of
             Bad x -> Bad x
             Ok y -> case J.readJSON y::(J.Result [[JobStatus]]) of
                       J.Ok vals -> if any null vals
                                    then Bad "Missing job status field"
                                    else Ok (map head vals)
                       J.Error x -> Bad x

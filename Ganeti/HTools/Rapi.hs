{-| Implementation of the RAPI client interface.

-}

module Ganeti.HTools.Rapi
    (
      getNodes
    , getInstances
    ) where

import Network.Curl
import Network.Curl.Types ()
import Network.Curl.Code
import Data.Either ()
import Data.Maybe
import Control.Monad
import Text.JSON (JSObject, JSValue)
import Text.Printf (printf)
import Ganeti.HTools.Utils


-- Some constants

-- | The fixed drbd overhead per disk (only used with 1.2's sdx_size)
drbdOverhead = 128

getUrl :: String -> IO (Result String)
getUrl url = do
  (code, body) <- curlGetString url [CurlSSLVerifyPeer False,
                                     CurlSSLVerifyHost 0]
  return (case code of
            CurlOK -> Ok body
            _ -> Bad $ printf "Curl error for '%s', error %s"
                 url (show code))

getInstances :: String -> IO (Result String)
getInstances master = do
  let url2 = printf "https://%s:5080/2/instances?bulk=1" master
  body <- getUrl url2
  return $ (body >>= \x -> do
              arr <- loadJSArray x
              ilist <- mapM parseInstance arr
              return $ unlines ilist)

getNodes :: String -> IO (Result String)
getNodes master = do
  let url2 = printf "https://%s:5080/2/nodes?bulk=1" master
  body <- getUrl url2
  return $ (body >>= \x -> do
             arr <- loadJSArray x
             nlist <- mapM parseNode arr
             return $ unlines nlist)

parseInstance :: JSObject JSValue -> Result String
parseInstance a =
    let name = getStringElement "name" a
        disk = case getIntElement "disk_usage" a of
                 Bad _ -> let log_sz = liftM2 (+)
                                       (getIntElement "sda_size" a)
                                       (getIntElement "sdb_size" a)
                          in liftM2 (+) log_sz (Ok $ drbdOverhead * 2)
                 x@(Ok _) -> x
        bep = fromObj "beparams" a
        pnode = getStringElement "pnode" a
        snode = (liftM head $ getListElement "snodes" a)
                >>= readEitherString
        mem = case bep of
                Bad _ -> getIntElement "admin_ram" a
                Ok o -> getIntElement "memory" o
        running = getStringElement "status" a
    in
      name |+ (show `liftM` mem) |+
              (show `liftM` disk) |+
              running |+ pnode |+ snode

boolToYN :: Bool -> Result String
boolToYN True = Ok "Y"
boolToYN _ = Ok "N"

parseNode :: JSObject JSValue -> Result String
parseNode a =
    let name = getStringElement "name" a
        offline = getBoolElement "offline" a
        drained = getBoolElement "drained" a
        mtotal = getIntElement "mtotal" a
        mnode = getIntElement "mnode" a
        mfree = getIntElement "mfree" a
        dtotal = getIntElement "dtotal" a
        dfree = getIntElement "dfree" a
    in name |+
       (case offline of
          Ok True -> Ok "0|0|0|0|0|Y"
          _ ->
              (show `liftM` mtotal) |+ (show `liftM` mnode) |+
              (show `liftM` mfree) |+ (show `liftM` dtotal) |+
              (show `liftM` dfree) |+
              ((liftM2 (||) offline drained) >>= boolToYN)
       )

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

-- | Read an URL via curl and return the body if successful
getUrl :: (Monad m) => String -> IO (m String)
getUrl url = do
  (code, body) <- curlGetString url [CurlSSLVerifyPeer False,
                                     CurlSSLVerifyHost 0]
  return (case code of
            CurlOK -> return body
            _ -> fail $ printf "Curl error for '%s', error %s"
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
        disk = getIntElement "disk_usage" a
        mem = getObjectElement "beparams" a >>= getIntElement "memory"
        pnode = getStringElement "pnode" a
        snode = (liftM head $ getListElement "snodes" a) >>= readEitherString
        running = getStringElement "status" a
    in
      name |+ (show `liftM` mem) |+
              (show `liftM` disk) |+
              running |+ pnode |+ snode

boolToYN :: (Monad m) => Bool -> m String
boolToYN True = return "Y"
boolToYN _ = return "N"

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

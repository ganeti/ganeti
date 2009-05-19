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
import Text.JSON
import Text.Printf (printf)
import Ganeti.HTools.Utils


-- Some constants

-- | The fixed drbd overhead per disk (only used with 1.2's sdx_size)
drbdOverhead = 128

getUrl :: String -> IO (Either String String)
getUrl url = do
  (code, body) <- curlGetString url [CurlSSLVerifyPeer False,
                                     CurlSSLVerifyHost 0]
  return (case code of
            CurlOK -> Right body
            _ -> Left $ printf "Curl error for '%s', error %s"
                 url (show code))

tryRapi :: String -> String -> IO (Either String String)
tryRapi url1 url2 =
    do
      body1 <- getUrl url1
      (case body1 of
         Left _ -> getUrl url2
         Right _ -> return body1)

getInstances :: String -> IO (Either String String)
getInstances master =
    let
        url2 = printf "https://%s:5080/2/instances?bulk=1" master
        url1 = printf "http://%s:5080/instances?bulk=1" master
    in do
      body <- tryRapi url1 url2
      let inst = body `combineEithers`
                 loadJSArray `combineEithers`
                 (parseEitherList parseInstance)
      return inst

getNodes :: String -> IO (Either String String)
getNodes master =
    let
        url2 = printf "https://%s:5080/2/nodes?bulk=1" master
        url1 = printf "http://%s:5080/nodes?bulk=1" master
    in do
      body <- tryRapi url1 url2
      let inst = body `combineEithers`
                 loadJSArray `combineEithers`
                 (parseEitherList parseNode)
      return inst

parseInstance :: JSObject JSValue -> Either String String
parseInstance a =
    let name = getStringElement "name" a
        disk = case getIntElement "disk_usage" a of
                 Left _ -> let log_sz = applyEither2 (+)
                                        (getIntElement "sda_size" a)
                                        (getIntElement "sdb_size" a)
                           in applyEither2 (+) log_sz
                                  (Right $ drbdOverhead * 2)
                 Right x -> Right x
        bep = fromObj "beparams" a
        pnode = getStringElement "pnode" a
        snode = (eitherListHead $ getListElement "snodes" a)
                `combineEithers` readEitherString
        mem = case bep of
                Left _ -> getIntElement "admin_ram" a
                Right o -> getIntElement "memory" o
        running = getStringElement "status" a
    in
      concatEitherElems name $
                  concatEitherElems (show `applyEither1` mem) $
                  concatEitherElems (show `applyEither1` disk) $
                  concatEitherElems running $
                  concatEitherElems pnode snode

boolToYN :: Bool -> Either String String
boolToYN True = Right "Y"
boolToYN _ = Right "N"

parseNode :: JSObject JSValue -> Either String String
parseNode a =
    let name = getStringElement "name" a
        offline = getBoolElement "offline" a
        drained = getBoolElement "drained" a
        mtotal = getIntElement "mtotal" a
        mnode = getIntElement "mnode" a
        mfree = getIntElement "mfree" a
        dtotal = getIntElement "dtotal" a
        dfree = getIntElement "dfree" a
    in concatEitherElems name $
       (case offline of
          Right True -> Right "0|0|0|0|0|Y"
          _ ->
              concatEitherElems (show `applyEither1` mtotal) $
              concatEitherElems (show `applyEither1` mnode) $
              concatEitherElems (show `applyEither1` mfree) $
              concatEitherElems (show `applyEither1` dtotal) $
              concatEitherElems (show `applyEither1` dfree)
              ((applyEither2 (||) offline drained) `combineEithers` boolToYN)
       )

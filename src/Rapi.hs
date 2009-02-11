{-| Implementation of the RAPI client interface.

-}

module Rapi
    where

import Network.Curl
import Network.Curl.Types
import Network.Curl.Code
import Data.Either (either)
import Data.Maybe
import Control.Monad
import Text.JSON
import Text.Printf (printf)
import Utils


{-- Our cheap monad-like stuff.

Thi is needed since Either e a is already a monad instance somewhere
in the standard libraries (Control.Monad.Error) and we don't need that
entire thing.

-}
combine :: (Either String a) -> (a -> Either String b)  -> (Either String b)
combine (Left s) _ = Left s
combine (Right s) f = f s

ensureList :: [Either String a] -> Either String [a]
ensureList lst =
    foldr (\elem accu ->
               case (elem, accu) of
                 (Left x, _) -> Left x
                 (_, Left x) -> Left x -- should never happen
                 (Right e, Right a) -> Right (e:a)
          )
    (Right []) lst

loadJSArray :: String -> Either String [JSObject JSValue]
loadJSArray s = resultToEither $ decodeStrict s

getStringElement :: String -> JSObject JSValue -> Either String String
getStringElement key o =
    resultToEither $ valFromObj key o

getIntElement :: String -> JSObject JSValue -> Either String String
getIntElement key o =
    let tmp = resultToEither $ ((valFromObj key o)::Result Int)
    in case tmp of
         Left x -> Left x
         Right x -> Right $ show x

concatElems a b =
    case a of
      Left _ -> a
      Right [] -> b
      Right x ->
          case b of
            Left _ -> b
            Right y ->  Right (x ++ "|" ++ y)

getUrl :: String -> IO (Either String String)
getUrl url = do
  (code, body) <- curlGetString url [CurlSSLVerifyPeer False,
                                     CurlSSLVerifyHost 0]
  return (case code of
            CurlOK -> Right body
            _ -> Left $ printf "url:%s, error: %s" url (show code))

getInstances :: String -> IO (Either String String)
getInstances master =
    let url = printf "https://%s:5080/2/instances?bulk=1" master
    in do
      body <- getUrl  url
      let inst = body `combine` loadJSArray `combine` (parseList parseInstance)
      return inst

getNodes :: String -> IO (Either String String)
getNodes master =
    let url = printf "https://%s:5080/2/nodes?bulk=1" master
    in do
      body <- getUrl  url
      let inst = body `combine` loadJSArray `combine` (parseList parseNode)
      return inst

parseList :: (JSObject JSValue -> Either String String)
          -> [JSObject JSValue]
          ->Either String String
parseList fn idata =
    let ml = ensureList $ map fn idata
    in ml `combine` (Right . unlines)

parseInstance :: JSObject JSValue -> Either String String
parseInstance a =
    let name = getStringElement "name" a
        disk = case getIntElement "disk_usage" a of
                 Left _ -> getIntElement "sda_size" a
                 Right x -> Right x
        bep = (resultToEither $ valFromObj "beparams" a)
    in
      case bep of
        Left x -> Left x
        Right x -> let mem = getIntElement "memory" x
                   in concatElems name $ concatElems mem disk

parseNode :: JSObject JSValue -> Either String String
parseNode a =
    let name = getStringElement "name" a
        mtotal = getIntElement "mtotal" a
        mfree = getIntElement "mfree" a
        dtotal = getIntElement "dtotal" a
        dfree = getIntElement "dfree" a
    in concatElems name $ concatElems mtotal $ concatElems mfree $
       concatElems dtotal dfree

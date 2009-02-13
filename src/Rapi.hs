{-| Implementation of the RAPI client interface.

-}

module Rapi
    where

import Network.Curl
import Network.Curl.Types ()
import Network.Curl.Code
import Data.Either ()
import Data.Maybe
import Control.Monad
import Text.JSON
import Text.Printf (printf)
import Utils ()


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

listHead :: Either String [a] -> Either String a
listHead lst =
    case lst of
      Left x -> Left x
      Right (x:_) -> Right x
      Right [] -> Left "List empty"

loadJSArray :: String -> Either String [JSObject JSValue]
loadJSArray s = resultToEither $ decodeStrict s

fromObj :: JSON a => String -> JSObject JSValue -> Either String a
fromObj k o =
    case lookup k (fromJSObject o) of
      Nothing -> Left $ printf "key '%s' not found" k
      Just val -> resultToEither $ readJSON val

getStringElement :: String -> JSObject JSValue -> Either String String
getStringElement key o = fromObj key o

getIntElement :: String -> JSObject JSValue -> Either String String
getIntElement key o =
    let tmp = (fromObj key o)::Either String Int
    in case tmp of
         Left x -> Left x
         Right x -> Right $ show x

getListElement :: String -> JSObject JSValue
               -> Either String [JSValue]
getListElement key o = fromObj key o

readString :: JSValue -> Either String String
readString v =
    case v of
      JSString s -> Right $ fromJSString s
      _ -> Left "Wrong JSON type"

concatElems :: Either String String
            -> Either String String
            -> Either String String
concatElems = apply2 (\x y -> x ++ "|" ++ y)

apply2 :: (a -> b -> c)
       -> Either String a
       -> Either String b
       -> Either String c
apply2 fn a b =
    case (a, b) of
      (Right x, Right y) -> Right $ fn x y
      (Left x, _) -> Left x
      (_, Left y) -> Left y

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
      body2 <- getUrl url2
      return (case body1 of
                Left _ -> body2
                Right _ -> body1)

getInstances :: String -> IO (Either String String)
getInstances master =
    let
        url2 = printf "https://%s:5080/2/instances?bulk=1" master
        url1 = printf "http://%s:5080/instances?bulk=1" master
    in do
      body <- tryRapi url1 url2
      let inst = body `combine` loadJSArray `combine` (parseList parseInstance)
      return inst

getNodes :: String -> IO (Either String String)
getNodes master =
    let
        url2 = printf "https://%s:5080/2/nodes?bulk=1" master
        url1 = printf "http://%s:5080/nodes?bulk=1" master
    in do
      body <- tryRapi url1 url2
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
                 Left _ -> apply2 (\x y -> show $ ((read x)::Int) + ((read y)::Int))
                           (getIntElement "sda_size" a)
                           (getIntElement "sdb_size" a)
                 Right x -> Right x
        bep = fromObj "beparams" a
        pnode = getStringElement "pnode" a
        snode = (listHead $ getListElement "snodes" a) `combine` readString
        mem = case bep of
                Left _ -> getIntElement "admin_ram" a
                Right _ -> bep
    in
      concatElems name $ concatElems mem $
                  concatElems disk $ concatElems pnode snode

parseNode :: JSObject JSValue -> Either String String
parseNode a =
    let name = getStringElement "name" a
        mtotal = getIntElement "mtotal" a
        mfree = getIntElement "mfree" a
        dtotal = getIntElement "dtotal" a
        dfree = getIntElement "dfree" a
    in concatElems name $ concatElems mtotal $ concatElems mfree $
       concatElems dtotal dfree

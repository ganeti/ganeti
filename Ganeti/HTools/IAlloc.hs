{-| Implementation of the iallocator interface.

-}

module Ganeti.HTools.IAlloc
    (
      parseData
    , formatResponse
    ) where

import Data.Either ()
import Data.Maybe
import Control.Monad
import Text.JSON
import Text.Printf (printf)
import Ganeti.HTools.Utils ()


-- Some constants

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
getStringElement = fromObj

getIntElement :: String -> JSObject JSValue -> Either String Int
getIntElement = fromObj

getListElement :: String -> JSObject JSValue
               -> Either String [JSValue]
getListElement = fromObj

readString :: JSValue -> Either String String
readString v =
    case v of
      JSString s -> Right $ fromJSString s
      _ -> Left "Wrong JSON type"

concatElems :: Either String String
            -> Either String String
            -> Either String String
concatElems = apply2 (\x y -> x ++ "|" ++ y)

apply1 :: (a -> b) -> Either String a -> Either String b
apply1 fn a =
    case a of
      Left x -> Left x
      Right y -> Right $ fn y

apply2 :: (a -> b -> c)
       -> Either String a
       -> Either String b
       -> Either String c
apply2 fn a b =
    case (a, b) of
      (Right x, Right y) -> Right $ fn x y
      (Left x, _) -> Left x
      (_, Left y) -> Left y

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
                 Left _ -> let log_sz = apply2 (+)
                                        (getIntElement "sda_size" a)
                                        (getIntElement "sdb_size" a)
                           in apply2 (+) log_sz (Right $ 128 * 2)
                 Right x -> Right x
        bep = fromObj "beparams" a
        pnode = getStringElement "pnode" a
        snode = (listHead $ getListElement "snodes" a) `combine` readString
        mem = case bep of
                Left _ -> getIntElement "admin_ram" a
                Right o -> getIntElement "memory" o
        running = getStringElement "status" a
    in
      concatElems name $
                  concatElems (show `apply1` mem) $
                  concatElems (show `apply1` disk) $
                  concatElems running $
                  concatElems pnode snode

parseNode :: JSObject JSValue -> Either String String
parseNode a =
    let name = getStringElement "name" a
        mtotal = getIntElement "mtotal" a
        mnode = getIntElement "mnode" a
        mfree = getIntElement "mfree" a
        dtotal = getIntElement "dtotal" a
        dfree = getIntElement "dfree" a
    in concatElems name $
       concatElems (show `apply1` mtotal) $
       concatElems (show `apply1` mnode) $
       concatElems (show `apply1` mfree) $
       concatElems (show `apply1` dtotal) (show `apply1` dfree)

parseData :: String -> Maybe String

parseData x = Just x

formatResponse :: Bool -> String -> [String] -> String
formatResponse success info nodes =
    let
        e_success = ("success", JSBool success)
        e_info = ("info", JSString . toJSString $ info)
        e_nodes = ("nodes", JSArray $ map (JSString . toJSString) nodes)
    in encodeStrict $ makeObj [e_success, e_info, e_nodes]

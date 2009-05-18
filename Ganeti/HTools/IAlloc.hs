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

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
import Ganeti.HTools.Utils

data RqType
    = Allocate
    | Relocate
    deriving (Show)

parseInstance :: String -> JSObject JSValue -> Either String String
parseInstance n a =
    let name = Right n
        disk = case getIntElement "disk_usage" a of
                 Left _ -> let all_d = getListElement "disks" a `combineEithers`
                                       asObjectList
                               szd = all_d `combineEithers`
                                     (ensureEitherList .
                                      map (getIntElement "size"))
                               sze = applyEither1 (map (+128)) szd
                               szf = applyEither1 sum sze
                           in szf
                 Right x -> Right x
        nodes = getListElement "nodes" a
        pnode = eitherListHead nodes
                `combineEithers` readEitherString
        snode = applyEither1 (head . tail) nodes
                `combineEithers` readEitherString
        mem = getIntElement "memory" a
        running = Right "running" --getStringElement "status" a
    in
      concatEitherElems name $
                  concatEitherElems (show `applyEither1` mem) $
                  concatEitherElems (show `applyEither1` disk) $
                  concatEitherElems running $
                  concatEitherElems pnode snode

parseNode :: String -> JSObject JSValue -> Either String String
parseNode n a =
    let name = Right n
        mtotal = getIntElement "total_memory" a
        mnode = getIntElement "reserved_memory" a
        mfree = getIntElement "free_memory" a
        dtotal = getIntElement "total_disk" a
        dfree = getIntElement "free_disk" a
    in concatEitherElems name $
       concatEitherElems (show `applyEither1` mtotal) $
       concatEitherElems (show `applyEither1` mnode) $
       concatEitherElems (show `applyEither1` mfree) $
       concatEitherElems (show `applyEither1` dtotal)
                             (show `applyEither1` dfree)

validateRequest :: String -> Either String RqType
validateRequest rq =
    case rq of
      "allocate" -> Right Allocate
      "relocate" -> Right Relocate
      _ -> Left ("Invalid request type '" ++ rq ++ "'")

parseData :: String -> Either String (String, String)
parseData body =
    let
        decoded = resultToEither $ decodeStrict body
        obj = decoded -- decoded `combineEithers` fromJSObject
        -- request parser
        request = obj `combineEithers` getObjectElement "request"
        rname = request `combineEithers` getStringElement "name"
        rtype = request `combineEithers` getStringElement "type"
                `combineEithers` validateRequest
        -- existing intstance parsing
        ilist = obj `combineEithers` getObjectElement "instances"
        idata = applyEither1 fromJSObject ilist
        iobj = idata `combineEithers` (ensureEitherList .
                                       map (\(x,y) ->
                                           asJSObject y `combineEithers`
                                                      parseInstance x))
        ilines = iobj `combineEithers` (Right . unlines)
        -- existing node parsing
        nlist = obj `combineEithers` getObjectElement "nodes"
        ndata = applyEither1 fromJSObject nlist
        nobj = ndata `combineEithers` (ensureEitherList .
                                       map (\(x,y) ->
                                           asJSObject y `combineEithers`
                                                      parseNode x))
        nlines = nobj `combineEithers` (Right . unlines)
    in applyEither2 (,) nlines ilines

formatResponse :: Bool -> String -> [String] -> String
formatResponse success info nodes =
    let
        e_success = ("success", JSBool success)
        e_info = ("info", JSString . toJSString $ info)
        e_nodes = ("nodes", JSArray $ map (JSString . toJSString) nodes)
    in encodeStrict $ makeObj [e_success, e_info, e_nodes]

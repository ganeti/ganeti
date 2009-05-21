{-| Implementation of the iallocator interface.

-}

module Ganeti.HTools.IAlloc
    (
      parseData
    , formatResponse
    ) where

import Data.Either ()
--import Data.Maybe
import Control.Monad
import Text.JSON (JSObject, JSValue(JSBool, JSString, JSArray),
                  makeObj, encodeStrict, decodeStrict,
                  fromJSObject, toJSString)
--import Text.Printf (printf)
import Ganeti.HTools.Utils
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

data RqType
    = Allocate
    | Relocate
    deriving (Eq, Show)

data Request
    = RqAlloc String String String
    | RqReloc String String String
    deriving (Show)

parseBaseInstance :: String -> JSObject JSValue -> Result String
parseBaseInstance n a =
    let name = Ok n
        disk = case getIntElement "disk_usage" a of
                 Bad _ -> let all_d = getListElement "disks" a >>= asObjectList
                              szd = all_d >>=
                                    (sequence .
                                     map (getIntElement "size"))
                              sze = liftM (map (+128)) szd
                              szf = liftM sum sze
                           in szf
                 x@(Ok _) -> x
        mem = getIntElement "memory" a
        running = Ok "running" --getStringElement "status" a
    in
      name |+ (show `liftM` mem) |+
              (show `liftM` disk) |+ running

parseInstance :: String -> JSObject JSValue -> Result String
parseInstance n a = do
    base <- parseBaseInstance n a
    let
        nodes = getListElement "nodes" a
        pnode = liftM head nodes >>= readEitherString
        snode = liftM (head . tail) nodes >>= readEitherString
    return base |+ pnode |+ snode


parseNode :: String -> JSObject JSValue -> Result String
parseNode n a =
    let name = Ok n
        mtotal = getIntElement "total_memory" a
        mnode = getIntElement "reserved_memory" a
        mfree = getIntElement "free_memory" a
        dtotal = getIntElement "total_disk" a
        dfree = getIntElement "free_disk" a
    in name |+ (show `liftM` mtotal) |+
              (show `liftM` mnode) |+
              (show `liftM` mfree) |+
              (show `liftM` dtotal) |+
              (show `liftM` dfree)

validateRequest :: String -> Result RqType
validateRequest rq =
    case rq of
      "allocate" -> Ok Allocate
      "relocate" -> Ok Relocate
      _ -> Bad ("Invalid request type '" ++ rq ++ "'")

parseData :: String -> Result Request
parseData body =
    do
      decoded <- fromJResult $ decodeStrict body
      let obj = decoded
      -- request parser
      request <- getObjectElement "request" obj
      rname <- getStringElement "name" request
      rtype <-  getStringElement "type" request >>= validateRequest
      inew <- (\x -> if x == Allocate then parseBaseInstance rname request
                     else Ok "") rtype
      -- existing instance parsing
      ilist <- getObjectElement "instances" obj
      let idata = fromJSObject ilist
      iobj <- (sequence . map (\(x,y) -> asJSObject y >>= parseInstance x))
              idata
      let ilines = unlines iobj
      -- existing node parsing
      nlist <- getObjectElement "nodes" obj
      let ndata = fromJSObject nlist
      nobj <- (sequence . map (\(x,y) -> asJSObject y >>= parseNode x))
              ndata
      let nlines = unlines nobj
      return $ (\ r nl il inew rnam ->
                    case r of
                      Allocate -> RqAlloc inew nl il
                      Relocate -> RqReloc rnam nl il)
                 rtype nlines ilines inew rname

formatResponse :: Bool -> String -> [String] -> String
formatResponse success info nodes =
    let
        e_success = ("success", JSBool success)
        e_info = ("info", JSString . toJSString $ info)
        e_nodes = ("nodes", JSArray $ map (JSString . toJSString) nodes)
    in encodeStrict $ makeObj [e_success, e_info, e_nodes]

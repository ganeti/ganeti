{-| Implementation of the iallocator interface.

-}

module Ganeti.HTools.IAlloc
    (
      parseData
    , formatResponse
    , RqType(..)
    , Request(..)
    ) where

import Data.Either ()
--import Data.Maybe
import Control.Monad
import Text.JSON (JSObject, JSValue(JSBool, JSString, JSArray),
                  makeObj, encodeStrict, decodeStrict,
                  fromJSObject, toJSString)
--import Text.Printf (printf)
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Loader
import Ganeti.HTools.Utils
import Ganeti.HTools.Types

data RqType
    = Allocate Instance.Instance Int
    | Relocate Int Int [Int]
    deriving (Show)

data Request = Request RqType NodeList InstanceList String
    deriving (Show)

parseBaseInstance :: String
                  -> JSObject JSValue
                  -> Result (String, Instance.Instance)
parseBaseInstance n a = do
  disk <- case fromObj "disk_usage" a of
            Bad _ -> do
                all_d <- fromObj "disks" a >>= asObjectList
                szd <- mapM (fromObj "size") all_d
                let sze = map (+128) szd
                    szf = (sum sze)::Int
                return szf
            x@(Ok _) -> x
  mem <- fromObj "memory" a
  let running = "running"
  return $ (n, Instance.create n mem disk running 0 0)

parseInstance :: NameAssoc
              -> String
              -> JSObject JSValue
              -> Result (String, Instance.Instance)
parseInstance ktn n a = do
    base <- parseBaseInstance n a
    nodes <- fromObj "nodes" a
    pnode <- readEitherString $ head nodes
    pidx <- lookupNode ktn n pnode
    let snodes = tail nodes
    sidx <- (if null snodes then return Node.noSecondary
             else (readEitherString $ head snodes) >>= lookupNode ktn n)
    return (n, Instance.setBoth (snd base) pidx sidx)

parseNode :: String -> JSObject JSValue -> Result (String, Node.Node)
parseNode n a = do
    let name = n
    offline <- fromObj "offline" a
    drained <- fromObj "drained" a
    node <- (case offline of
               True -> return $ Node.create name 0 0 0 0 0 True
               _ -> do
                 mtotal <- fromObj "total_memory" a
                 mnode <- fromObj "reserved_memory" a
                 mfree <- fromObj "free_memory" a
                 dtotal <- fromObj "total_disk" a
                 dfree <- fromObj "free_disk" a
                 return $ Node.create n mtotal mnode mfree
                        dtotal dfree (offline || drained))
    return (name, node)

parseData :: String -> Result Request
parseData body = do
  decoded <- fromJResult $ decodeStrict body
  let obj = decoded
  -- request parser
  request <- fromObj "request" obj
  rname <- fromObj "name" request
  -- existing node parsing
  nlist <- fromObj "nodes" obj
  let ndata = fromJSObject nlist
  nobj <- (mapM (\(x,y) -> asJSObject y >>= parseNode x)) ndata
  let (ktn, nl) = assignIndices nobj
  -- existing instance parsing
  ilist <- fromObj "instances" obj
  let idata = fromJSObject ilist
  iobj <- (mapM (\(x,y) -> asJSObject y >>= parseInstance ktn x)) idata
  let (kti, il) = assignIndices iobj
  (map_n, map_i, csf) <- mergeData (nl, il)
  req_nodes <- fromObj "required_nodes" request
  optype <- fromObj "type" request
  rqtype <-
      case optype of
        "allocate" ->
            do
              inew <- parseBaseInstance rname request
              let io = snd inew
              return $ Allocate io req_nodes
        "relocate" ->
            do
              ridx <- lookupNode kti rname rname
              ex_nodes <- fromObj "relocate_from" request
              let ex_nodes' = map (stripSuffix $ length csf) ex_nodes
              ex_idex <- mapM (findByName map_n) ex_nodes'
              return $ Relocate ridx req_nodes ex_idex
        other -> fail $ ("Invalid request type '" ++ other ++ "'")
  return $ Request rqtype map_n map_i csf

formatResponse :: Bool -> String -> [String] -> String
formatResponse success info nodes =
    let
        e_success = ("success", JSBool success)
        e_info = ("info", JSString . toJSString $ info)
        e_nodes = ("nodes", JSArray $ map (JSString . toJSString) nodes)
    in encodeStrict $ makeObj [e_success, e_info, e_nodes]

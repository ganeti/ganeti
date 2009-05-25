{-| Implementation of the RAPI client interface.

-}

module Ganeti.HTools.Rapi
    (
      loadData
    ) where

import Network.Curl
import Network.Curl.Types ()
import Network.Curl.Code
import Data.List
import Control.Monad
import Text.JSON (JSObject, JSValue)
import Text.Printf (printf)

import Ganeti.HTools.Utils
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

-- | Read an URL via curl and return the body if successful
getUrl :: (Monad m) => String -> IO (m String)
getUrl url = do
  (code, body) <- curlGetString url [CurlSSLVerifyPeer False,
                                     CurlSSLVerifyHost 0]
  return (case code of
            CurlOK -> return body
            _ -> fail $ printf "Curl error for '%s', error %s"
                 url (show code))

-- | Append the default port if not passed in
formatHost :: String -> String
formatHost master =
    if elem ':' master then  master
    else "https://" ++ master ++ ":5080"

getInstances :: NameAssoc
             -> String
             -> Result [(String, Instance.Instance)]
getInstances ktn body = do
  arr <- loadJSArray body
  ilist <- mapM (parseInstance ktn) arr
  return ilist

getNodes :: String -> Result [(String, Node.Node)]
getNodes body = do
  arr <- loadJSArray body
  nlist <- mapM parseNode arr
  return nlist

parseInstance :: [(String, Int)]
              -> JSObject JSValue
              -> Result (String, Instance.Instance)
parseInstance ktn a = do
  name <- fromObj "name" a
  disk <- fromObj "disk_usage" a
  mem <- fromObj "beparams" a >>= fromObj "memory"
  pnode <- fromObj "pnode" a >>= lookupNode ktn name
  snodes <- fromObj "snodes" a
  snode <- (if null snodes then return Node.noSecondary
            else readEitherString (head snodes) >>= lookupNode ktn name)
  running <- fromObj "status" a
  let inst = Instance.create name mem disk running pnode snode
  return (name, inst)

parseNode :: JSObject JSValue -> Result (String, Node.Node)
parseNode a = do
    name <- fromObj "name" a
    offline <- fromObj "offline" a
    node <- (case offline of
               True -> return $ Node.create name 0 0 0 0 0 True
               _ -> do
                 drained <- fromObj "drained" a
                 mtotal <- fromObj "mtotal" a
                 mnode <- fromObj "mnode" a
                 mfree <- fromObj "mfree" a
                 dtotal <- fromObj "dtotal" a
                 dfree <- fromObj "dfree" a
                 return $ Node.create name mtotal mnode mfree
                        dtotal dfree (offline || drained))
    return (name, node)

loadData :: String -- ^ Cluster or URL to use as source
         -> IO (Result (Node.AssocList, Instance.AssocList))
loadData master = do -- IO monad
  let url = formatHost master
  node_body <- getUrl $ printf "%s/2/nodes?bulk=1" url
  inst_body <- getUrl $ printf "%s/2/instances?bulk=1" url
  return $ do -- Result monad
    node_data <- node_body >>= getNodes
    let (node_names, node_idx) = assignIndices node_data
    inst_data <- inst_body >>= getInstances node_names
    let (_, inst_idx) = assignIndices inst_data
    return (node_idx, inst_idx)

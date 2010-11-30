{-| Implementation of the RAPI client interface.

-}

{-

Copyright (C) 2009, 2010 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.HTools.Rapi
    (
      loadData
    , parseData
    ) where

import Network.Curl
import Network.Curl.Types ()
import Control.Monad
import Text.JSON (JSObject, JSValue, fromJSObject, decodeStrict)
import Text.JSON.Types (JSValue(..))
import Text.Printf (printf)

import Ganeti.HTools.Utils
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance

-- | Read an URL via curl and return the body if successful.
getUrl :: (Monad m) => String -> IO (m String)
getUrl url = do
  (code, body) <- curlGetString url [CurlSSLVerifyPeer False,
                                     CurlSSLVerifyHost 0,
                                     CurlTimeout (fromIntegral queryTimeout),
                                     CurlConnectTimeout
                                     (fromIntegral connTimeout)]
  return (case code of
            CurlOK -> return body
            _ -> fail $ printf "Curl error for '%s', error %s"
                 url (show code))

-- | Append the default port if not passed in.
formatHost :: String -> String
formatHost master =
    if ':' `elem` master then  master
    else "https://" ++ master ++ ":5080"

-- | Parse a instance list in JSON format.
getInstances :: NameAssoc
             -> String
             -> Result [(String, Instance.Instance)]
getInstances ktn body =
    loadJSArray "Parsing instance data" body >>=
    mapM (parseInstance ktn . fromJSObject)

-- | Parse a node list in JSON format.
getNodes :: String -> Result [(String, Node.Node)]
getNodes body = loadJSArray "Parsing node data" body >>=
                mapM (parseNode . fromJSObject)

-- | Construct an instance from a JSON object.
parseInstance :: NameAssoc
              -> [(String, JSValue)]
              -> Result (String, Instance.Instance)
parseInstance ktn a = do
  name <- tryFromObj "Parsing new instance" a "name"
  let owner_name = "Instance '" ++ name ++ "'"
  let extract s x = tryFromObj owner_name x s
  disk <- extract "disk_usage" a
  beparams <- liftM fromJSObject (extract "beparams" a)
  omem <- extract "oper_ram" a
  mem <- (case omem of
            JSRational _ _ -> annotateResult owner_name (fromJVal omem)
            _ -> extract "memory" beparams)
  vcpus <- extract "vcpus" beparams
  pnode <- extract "pnode" a >>= lookupNode ktn name
  snodes <- extract "snodes" a
  snode <- (if null snodes then return Node.noSecondary
            else readEitherString (head snodes) >>= lookupNode ktn name)
  running <- extract "status" a
  tags <- extract "tags" a
  let inst = Instance.create name mem disk vcpus running tags pnode snode
  return (name, inst)

-- | Construct a node from a JSON object.
parseNode :: [(String, JSValue)] -> Result (String, Node.Node)
parseNode a = do
  name <- tryFromObj "Parsing new node" a "name"
  let extract s = tryFromObj ("Node '" ++ name ++ "'") a s
  offline <- extract "offline"
  drained <- extract "drained"
  guuid   <- extract "group.uuid"
  node <- (if offline || drained
           then return $ Node.create name 0 0 0 0 0 0 True guuid
           else do
             mtotal  <- extract "mtotal"
             mnode   <- extract "mnode"
             mfree   <- extract "mfree"
             dtotal  <- extract "dtotal"
             dfree   <- extract "dfree"
             ctotal  <- extract "ctotal"
             return $ Node.create name mtotal mnode mfree
                    dtotal dfree ctotal False guuid)
  return (name, node)

-- | Loads the raw cluster data from an URL.
readData :: String -- ^ Cluster or URL to use as source
         -> IO (Result String, Result String, Result String)
readData master = do
  let url = formatHost master
  node_body <- getUrl $ printf "%s/2/nodes?bulk=1" url
  inst_body <- getUrl $ printf "%s/2/instances?bulk=1" url
  tags_body <- getUrl $ printf "%s/2/tags" url
  return (node_body, inst_body, tags_body)

-- | Builds the cluster data from the raw Rapi content
parseData :: (Result String, Result String, Result String)
          -> Result (Node.List, Instance.List, [String])
parseData (node_body, inst_body, tags_body) = do
  node_data <- node_body >>= getNodes
  let (node_names, node_idx) = assignIndices node_data
  inst_data <- inst_body >>= getInstances node_names
  let (_, inst_idx) = assignIndices inst_data
  tags_data <- tags_body >>= (fromJResult "Parsing tags data" . decodeStrict)
  return (node_idx, inst_idx, tags_data)

-- | Top level function for data loading
loadData :: String -- ^ Cluster or URL to use as source
            -> IO (Result (Node.List, Instance.List, [String]))
loadData master = readData master >>= return . parseData

{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti confd types.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.Confd.Types
  ( ConfdClient(..)
  , ConfdRequestType(..)
  , confdRequestTypeToRaw
  , ConfdReqField(..)
  , confdReqFieldToRaw
  , ConfdReqQ(..)
  , ConfdReplyStatus(..)
  , confdReplyStatusToRaw
  , ConfdNodeRole(..)
  , confdNodeRoleToRaw
  , ConfdErrorType(..)
  , confdErrorTypeToRaw
  , ConfdRequest(..)
  , newConfdRequest
  , ConfdReply(..)
  , ConfdQuery(..)
  , SignedMessage(..)
  ) where

import Text.JSON
import qualified Network.Socket as S

import qualified Ganeti.ConstantUtils as ConstantUtils
import Ganeti.Hash
import Ganeti.THH
import Ganeti.Utils (newUUID)

$(declareILADT "ConfdRequestType"
  [ ("ReqPing",             0)
  , ("ReqNodeRoleByName",   1)
  , ("ReqNodePipByInstPip", 2)
  , ("ReqClusterMaster",    3)
  , ("ReqNodePipList",      4)
  , ("ReqMcPipList",        5)
  , ("ReqInstIpsList",      6)
  , ("ReqNodeDrbd",         7)
  , ("ReqNodeInstances",    8)
  , ("ReqInstanceDisks",    9)
  ])
$(makeJSONInstance ''ConfdRequestType)

$(declareILADT "ConfdReqField"
  [ ("ReqFieldName",     0)
  , ("ReqFieldIp",       1)
  , ("ReqFieldMNodePip", 2)
  ])
$(makeJSONInstance ''ConfdReqField)

-- Confd request query fields. These are used to narrow down queries.
-- These must be strings rather than integers, because json-encoding
-- converts them to strings anyway, as they're used as dict-keys.

$(buildObject "ConfdReqQ" "confdReqQ"
  [ renameField "Ip" .
    optionalField $
    simpleField ConstantUtils.confdReqqIp [t| String |]
  , renameField "IpList" .
    defaultField [| [] |] $
    simpleField ConstantUtils.confdReqqIplist [t| [String] |]
  , renameField "Link" .
    optionalField $
    simpleField ConstantUtils.confdReqqLink [t| String |]
  , renameField "Fields" .
    defaultField [| [] |] $
    simpleField ConstantUtils.confdReqqFields [t| [ConfdReqField] |]
  ])

-- | Confd query type. This is complex enough that we can't
-- automatically derive it via THH.
data ConfdQuery = EmptyQuery
                | PlainQuery String
                | DictQuery  ConfdReqQ
                  deriving (Show, Eq)

instance JSON ConfdQuery where
  readJSON o = case o of
                 JSNull     -> return EmptyQuery
                 JSString s -> return . PlainQuery . fromJSString $ s
                 JSObject _ -> fmap DictQuery (readJSON o::Result ConfdReqQ)
                 _ -> fail $ "Cannot deserialise into ConfdQuery\
                             \ the value '" ++ show o ++ "'"
  showJSON cq = case cq of
                  EmptyQuery -> JSNull
                  PlainQuery s -> showJSON s
                  DictQuery drq -> showJSON drq

$(declareILADT "ConfdReplyStatus"
  [ ("ReplyStatusOk",      0)
  , ("ReplyStatusError",   1)
  , ("ReplyStatusNotImpl", 2)
  ])
$(makeJSONInstance ''ConfdReplyStatus)

$(declareILADT "ConfdNodeRole"
  [ ("NodeRoleMaster",    0)
  , ("NodeRoleCandidate", 1)
  , ("NodeRoleOffline",   2)
  , ("NodeRoleDrained",   3)
  , ("NodeRoleRegular",   4)
  ])
$(makeJSONInstance ''ConfdNodeRole)

-- Note that the next item is not a frozenset in Python, but we make
-- it a separate type for safety

$(declareILADT "ConfdErrorType"
  [ ("ConfdErrorUnknownEntry", 0)
  , ("ConfdErrorInternal",     1)
  , ("ConfdErrorArgument",     2)
  ])
$(makeJSONInstance ''ConfdErrorType)

$(buildObject "ConfdRequest" "confdRq"
  [ simpleField "protocol" [t| Int |]
  , simpleField "type"     [t| ConfdRequestType |]
  , defaultField [| EmptyQuery |] $ simpleField "query" [t| ConfdQuery |]
  , simpleField "rsalt"    [t| String |]
  ])

-- | Client side helper function for creating requests. It automatically fills
-- in some default values.
newConfdRequest :: ConfdRequestType -> ConfdQuery -> IO ConfdRequest
newConfdRequest reqType query = do
  rsalt <- newUUID
  return $ ConfdRequest ConstantUtils.confdProtocolVersion reqType query rsalt

$(buildObject "ConfdReply" "confdReply"
  [ simpleField "protocol" [t| Int              |]
  , simpleField "status"   [t| ConfdReplyStatus |]
  , simpleField "answer"   [t| JSValue          |]
  , simpleField "serial"   [t| Int              |]
  ])

$(buildObject "SignedMessage" "signedMsg"
  [ simpleField "hmac" [t| String |]
  , simpleField "msg"  [t| String |]
  , simpleField "salt" [t| String |]
  ])

-- | Data type containing information used by the Confd client.
data ConfdClient = ConfdClient
  { hmacKey :: HashKey         -- ^ The hmac used for authentication
  , peers :: [String]          -- ^ The list of nodes to query
  , serverPort :: S.PortNumber -- ^ The port where confd server is listening
  }

{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti confd types.

-}

{-

Copyright (C) 2011, 2012 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
  [ ("ReqPing",              0)
  , ("ReqNodeRoleByName",    1)
  , ("ReqNodePipByInstPip",  2)
  , ("ReqClusterMaster",     3)
  , ("ReqNodePipList",       4)
  , ("ReqMcPipList",         5)
  , ("ReqInstIpsList",       6)
  , ("ReqNodeDrbd",          7)
  , ("ReqNodeInstances",     8)
  , ("ReqInstanceDisks",     9)
  , ("ReqConfigQuery",      10)
  , ("ReqDataCollectors",   11)
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

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
  ( C.confdProtocolVersion
  , C.confdMaxClockSkew
  , C.confdConfigReloadTimeout
  , C.confdConfigReloadRatelimit
  , C.confdMagicFourcc
  , C.confdDefaultReqCoverage
  , C.confdClientExpireTimeout
  , C.maxUdpDataSize
  , ConfdRequestType(..)
  , ConfdReqQ(..)
  , ConfdReqField(..)
  , ConfdReplyStatus(..)
  , ConfdNodeRole(..)
  , ConfdErrorType(..)
  , ConfdRequest(..)
  , ConfdReply(..)
  , ConfdQuery(..)
  , SignedMessage(..)
  ) where

import Text.JSON

import qualified Ganeti.Constants as C
import Ganeti.THH
import Ganeti.JSON

{-
   Note that we re-export as is from Constants the following simple items:
   - confdProtocolVersion
   - confdMaxClockSkew
   - confdConfigReloadTimeout
   - confdConfigReloadRatelimit
   - confdMagicFourcc
   - confdDefaultReqCoverage
   - confdClientExpireTimeout
   - maxUdpDataSize

-}

$(declareIADT "ConfdRequestType"
  [ ("ReqPing",             'C.confdReqPing )
  , ("ReqNodeRoleByName",   'C.confdReqNodeRoleByname )
  , ("ReqNodePipList",      'C.confdReqNodePipList )
  , ("ReqNodePipByInstPip", 'C.confdReqNodePipByInstanceIp )
  , ("ReqClusterMaster",    'C.confdReqClusterMaster )
  , ("ReqMcPipList",        'C.confdReqMcPipList )
  , ("ReqInstIpsList",      'C.confdReqInstancesIpsList )
  , ("ReqNodeDrbd",         'C.confdReqNodeDrbd )
  ])
$(makeJSONInstance ''ConfdRequestType)

$(declareSADT "ConfdReqField"
  [ ("ReqFieldName",     'C.confdReqfieldName )
  , ("ReqFieldIp",       'C.confdReqfieldIp )
  , ("ReqFieldMNodePip", 'C.confdReqfieldMnodePip )
  ])
$(makeJSONInstance ''ConfdReqField)

-- Confd request query fields. These are used to narrow down queries.
-- These must be strings rather than integers, because json-encoding
-- converts them to strings anyway, as they're used as dict-keys.

$(buildObject "ConfdReqQ" "confdReqQ"
  [ renameField "Ip" .
                optionalField $ simpleField C.confdReqqIp [t| String   |]
  , renameField "IpList" .
                defaultField [| [] |] $
                simpleField C.confdReqqIplist [t| [String] |]
  , renameField "Link" . optionalField $
                simpleField C.confdReqqLink [t| String   |]
  , renameField "Fields" . defaultField [| [] |] $
                simpleField C.confdReqqFields [t| [ConfdReqField] |]
  ])

-- | Confd query type. This is complex enough that we can't
-- automatically derive it via THH.
data ConfdQuery = EmptyQuery
                | PlainQuery String
                | DictQuery  ConfdReqQ
                  deriving (Show, Read, Eq)

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

$(declareIADT "ConfdReplyStatus"
  [ ( "ReplyStatusOk",      'C.confdReplStatusOk )
  , ( "ReplyStatusError",   'C.confdReplStatusError )
  , ( "ReplyStatusNotImpl", 'C.confdReplStatusNotimplemented )
  ])
$(makeJSONInstance ''ConfdReplyStatus)

$(declareIADT "ConfdNodeRole"
  [ ( "NodeRoleMaster",    'C.confdNodeRoleMaster )
  , ( "NodeRoleCandidate", 'C.confdNodeRoleCandidate )
  , ( "NodeRoleOffline",   'C.confdNodeRoleOffline )
  , ( "NodeRoleDrained",   'C.confdNodeRoleDrained )
  , ( "NodeRoleRegular",   'C.confdNodeRoleRegular )
  ])
$(makeJSONInstance ''ConfdNodeRole)


-- Note that the next item is not a frozenset in Python, but we make
-- it a separate type for safety

$(declareIADT "ConfdErrorType"
  [ ( "ConfdErrorUnknownEntry", 'C.confdErrorUnknownEntry )
  , ( "ConfdErrorInternal",     'C.confdErrorInternal )
  , ( "ConfdErrorArgument",     'C.confdErrorArgument )
  ])
$(makeJSONInstance ''ConfdErrorType)

$(buildObject "ConfdRequest" "confdRq"
  [ simpleField "protocol" [t| Int |]
  , simpleField "type"     [t| ConfdRequestType |]
  , defaultField [| EmptyQuery |] $ simpleField "query" [t| ConfdQuery |]
  , simpleField "rsalt"    [t| String |]
  ])

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

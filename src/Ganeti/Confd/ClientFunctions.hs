{-| Some utility functions, based on the Confd client, providing data
 in a ready-to-use way.
-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.Confd.ClientFunctions
  ( getInstances
  , getInstanceDisks
  ) where

import Control.Monad (liftM)
import qualified Text.JSON as J

import Ganeti.BasicTypes as BT
import Ganeti.Confd.Types
import Ganeti.Confd.Client
import Ganeti.Objects


-- | Get the list of instances the given node is ([primary], [secondary]) for.
-- The server address and the server port parameters are mainly intended
-- for testing purposes. If they are Nothing, the default values will be used.
getInstances
  :: String
  -> Maybe String
  -> Maybe Int
  -> BT.ResultT String IO ([Ganeti.Objects.Instance], [Ganeti.Objects.Instance])
getInstances node srvAddr srvPort = do
  client <- liftIO $ getConfdClient srvAddr srvPort
  reply <- liftIO . query client ReqNodeInstances $ PlainQuery node
  case fmap (J.readJSON . confdReplyAnswer) reply of
    Just (J.Ok instances) -> return instances
    Just (J.Error msg) -> fail msg
    Nothing -> fail "No answer from the Confd server"

-- | Get the list of disks that belong to a given instance
-- The server address and the server port parameters are mainly intended
-- for testing purposes. If they are Nothing, the default values will be used.
getDisks
  :: Ganeti.Objects.Instance
  -> Maybe String
  -> Maybe Int
  -> BT.ResultT String IO [Ganeti.Objects.Disk]
getDisks inst srvAddr srvPort = do
  client <- liftIO $ getConfdClient srvAddr srvPort
  reply <- liftIO . query client ReqInstanceDisks . PlainQuery . uuidOf $ inst
  case fmap (J.readJSON . confdReplyAnswer) reply of
    Just (J.Ok disks) -> return disks
    Just (J.Error msg) -> fail msg
    Nothing -> fail "No answer from the Confd server"

-- | Get the list of instances on the given node along with their disks
-- The server address and the server port parameters are mainly intended
-- for testing purposes. If they are Nothing, the default values will be used.
getInstanceDisks
  :: String
  -> Maybe String
  -> Maybe Int
  -> BT.ResultT String IO [(Ganeti.Objects.Instance, [Ganeti.Objects.Disk])]
getInstanceDisks node srvAddr srvPort =
  liftM (uncurry (++)) (getInstances node srvAddr srvPort) >>=
    mapM (\i -> liftM ((,) i) (getDisks i srvAddr srvPort))

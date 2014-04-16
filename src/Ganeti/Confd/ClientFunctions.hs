{-| Some utility functions, based on the Confd client, providing data
 in a ready-to-use way.
-}

{-

Copyright (C) 2013 Google Inc.

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
  reply <- liftIO . query client ReqInstanceDisks . PlainQuery . instUuid $ inst
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

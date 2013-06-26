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
  ) where

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
  -> IO (BT.Result ([Ganeti.Objects.Instance], [Ganeti.Objects.Instance]))
getInstances node srvAddr srvPort = do
  client <- getConfdClient srvAddr srvPort
  reply <- query client ReqNodeInstances $ PlainQuery node
  return $
    case fmap (J.readJSON . confdReplyAnswer) reply of
      Just (J.Ok instances) -> BT.Ok instances
      Just (J.Error msg) -> BT.Bad msg
      Nothing -> BT.Bad "No answer from the Confd server"

{-| Instance status data collector.

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

module Ganeti.DataCollectors.InstStatus
  ( main
  , options
  , arguments
  ) where


import Data.Maybe
import qualified Data.Map as Map
import Network.BSD (getHostName)
import qualified Text.JSON as J

import qualified Ganeti.BasicTypes as BT
import Ganeti.Confd.Client
import Ganeti.Confd.Types
import Ganeti.Common
import Ganeti.DataCollectors.CLI
import Ganeti.DataCollectors.InstStatusTypes
import Ganeti.Hypervisor.Xen
import Ganeti.Objects
import Ganeti.Utils

-- * Command line options

options :: IO [OptType]
options = return
  [ oConfdAddr
  , oConfdPort
  ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Get the list of instances ([primary], [secondary]) on the given node.
-- Implemented as a function, even if used a single time, to specify in a
-- convenient and elegant way the return data type, required in order to
-- prevent incurring in the monomorphism restriction.
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

-- Builds the status of an instance using runtime information about the Xen
-- Domains, their uptime information and the static information provided by
-- the ConfD server.
buildStatus :: Map.Map String Domain -> Map.Map Int UptimeInfo -> Instance
  -> IO InstStatus
buildStatus domains uptimes inst = do
  let name = instName inst
      currDomain = Map.lookup name domains
      idNum = fmap domId currDomain
      currUInfo = idNum >>= (`Map.lookup` uptimes)
      uptime = fmap uInfoUptime currUInfo
      adminState = instAdminState inst
  return $
    InstStatus
      name
      (instUuid inst)
      adminState
      uptime
      (instMtime inst)

-- | Main function.
main :: Options -> [String] -> IO ()
main opts _ = do
  curNode <- getHostName
  let node = fromMaybe curNode $ optNode opts
  answer <- getInstances node (optConfdAddr opts) (optConfdPort opts)
  inst <- exitIfBad "Can't get instance info from ConfD" answer
  domains <- getInferredDomInfo
  uptimes <- getUptimeInfo
  let primaryInst =  fst inst
  iStatus <- mapM (buildStatus domains uptimes) primaryInst
  putStrLn $ J.encode iStatus

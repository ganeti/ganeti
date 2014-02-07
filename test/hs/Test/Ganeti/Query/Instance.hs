{-# LANGUAGE TupleSections, TemplateHaskell #-}

{-| Unittests for Instance Queries.

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

module Test.Ganeti.Query.Instance
  ( testQuery_Instance
  ) where

import qualified Data.Map as Map
import qualified Data.Set as Set
import System.Time (ClockTime(..))

import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Query.Instance
import Ganeti.Rpc
import Ganeti.Types

import Test.Ganeti.TestHelper
import Test.HUnit

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Creates an instance with the desired name, pnode uuid, and AdminState.
-- All other fields are placeholders.
createInstance :: String -> String -> AdminState -> Instance
createInstance name pnodeUuid adminState =
  Instance name pnodeUuid "" Kvm
    (GenericContainer Map.empty)
    (PartialBeParams Nothing Nothing Nothing Nothing Nothing Nothing)
    (GenericContainer Map.empty) (GenericContainer Map.empty)
    adminState [] [] DTDrbd8 False Nothing epochTime epochTime "" 0 Set.empty
  where epochTime = TOD 0 0

-- | A fake InstanceInfo to be used to check values.
fakeInstanceInfo :: InstanceInfo
fakeInstanceInfo = InstanceInfo 0 InstanceStateRunning 0 0

-- | Erroneous node response - the exact error does not matter.
responseError :: String -> (String, ERpcError a)
responseError name = (name, Left . RpcResultError $ "Insignificant error")

-- | Successful response - the error does not really matter.
responseSuccess :: String
                -> [String]
                -> (String, ERpcError RpcResultAllInstancesInfo)
responseSuccess name instNames = (name, Right .
  RpcResultAllInstancesInfo . map (, fakeInstanceInfo) $ instNames)

-- | The instance used for testing. Called Waldo as test cases involve trouble
-- finding information related to it.
waldoInstance :: Instance
waldoInstance = createInstance "Waldo" "prim" AdminUp

-- | Check that an error is thrown when the node is offline
case_nodeOffline :: Assertion
case_nodeOffline =
  let responses = [ responseError   "prim"
                  , responseError   "second"
                  , responseSuccess "node" ["NotWaldo", "DefinitelyNotWaldo"]
                  ]
  in case getInstanceInfo responses waldoInstance of
       Left _   -> return ()
       Right _  -> assertFailure
         "Error occurred when instance info is missing and node is offline"

-- | Check that a Right Nothing is returned when the node is online, yet no info
-- is present anywhere in the system.
case_nodeOnlineNoInfo :: Assertion
case_nodeOnlineNoInfo =
  let responses = [ responseSuccess "prim"   ["NotWaldo1"]
                  , responseSuccess "second" ["NotWaldo2"]
                  , responseError   "node"
                  ]
  in case getInstanceInfo responses waldoInstance of
       Left _         -> assertFailure
         "Error occurred when instance info could be found on primary"
       Right Nothing  -> return ()
       Right _        -> assertFailure
         "Some instance info found when none should be"

-- | Check the case when the info is on the primary node
case_infoOnPrimary :: Assertion
case_infoOnPrimary =
  let responses = [ responseSuccess "prim"   ["NotWaldo1", "Waldo"]
                  , responseSuccess "second" ["NotWaldo2"]
                  , responseSuccess "node"   ["NotWaldo3"]
                  ]
  in case getInstanceInfo responses waldoInstance of
       Left _                  -> assertFailure
         "Cannot retrieve instance info when present on primary node"
       Right (Just (_, True))  -> return ()
       Right _                 -> assertFailure
         "Instance info not found on primary node, despite being there"

-- | Check the case when the info is on the primary node
case_infoOnSecondary :: Assertion
case_infoOnSecondary =
  let responses = [ responseSuccess "prim"   ["NotWaldo1"]
                  , responseSuccess "second" ["Waldo", "NotWaldo2"]
                  , responseError   "node"
                  ]
  in case getInstanceInfo responses waldoInstance of
       Left _                   -> assertFailure
         "Cannot retrieve instance info when present on secondary node"
       Right (Just (_, False))  -> return ()
       Right _                  -> assertFailure
         "Instance info not found on secondary node, despite being there"

testSuite "Query_Instance"
  [ 'case_nodeOffline
  , 'case_nodeOnlineNoInfo
  , 'case_infoOnPrimary
  , 'case_infoOnSecondary
  ]

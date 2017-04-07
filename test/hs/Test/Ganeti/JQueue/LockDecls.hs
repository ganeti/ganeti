{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for the static lock declaration.

-}

{-

Copyright (C) 2016 Google Inc.
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

module Test.Ganeti.JQueue.LockDecls (testLockDecls) where

import Test.QuickCheck
import Test.HUnit
import Data.List
import Data.Maybe

import Prelude ()
import Ganeti.Prelude

import Test.Ganeti.TestHelper
import Test.Ganeti.Objects
import Test.Ganeti.OpCodes (genOpCodeFromId)
import Test.Ganeti.TestCommon

import qualified Ganeti.Constants as C
import Ganeti.JQueue.LockDecls
import Ganeti.OpCodes
import Ganeti.Objects


prop_staticWeight :: ConfigData -> Maybe OpCode -> [OpCode] -> Property
prop_staticWeight cfg op ops =
  let weight = staticWeight cfg op ops
      maxWeight = C.staticLockSureBlockWeight * 5
  in (weight >= 0 && weight <= (maxWeight+ C.staticLockBaseWeight)) ==? True

genExclusiveInstanceOp :: ConfigData -> Gen OpCode
genExclusiveInstanceOp cfg = do
  let list = [ "OP_INSTANCE_STARTUP"
             , "OP_INSTANCE_SHUTDOWN"
             , "OP_INSTANCE_REBOOT"
             , "OP_INSTANCE_RENAME"
             ]
  op_id <- elements list
  genOpCodeFromId op_id (Just cfg)

prop_instNameConflictCheck :: Property
prop_instNameConflictCheck = do
  forAll (genConfigDataWithValues 10 50) $ \ cfg ->
    forAll (genExclusiveInstanceOp cfg) $ \ op1 ->
      forAll (genExclusiveInstanceOp cfg) $ \ op2 ->
        forAll (genExclusiveInstanceOp cfg) $ \ op3 ->
          let w1 = staticWeight cfg (Just op1) [op3]
              w2 = staticWeight cfg (Just op2) [op3]
              iName1 = opInstanceName op1
              iName2 = opInstanceName op2
              iName3 = opInstanceName op3
              testResult
                | iName1 == iName2 = True
                | iName1 == iName3 = (w2 <= w1)
                | iName2 == iName3 = (w1 <= w2)
                | otherwise = True
          in testResult

genExclusiveNodeOp :: ConfigData -> Gen OpCode
genExclusiveNodeOp cfg = do
  let list = [ "OP_REPAIR_COMMAND"
             , "OP_NODE_MODIFY_STORAGE"
             , "OP_REPAIR_NODE_STORAGE"
             ]
  op_id <- elements list
  genOpCodeFromId op_id (Just cfg)

prop_nodeNameConflictCheck :: Property
prop_nodeNameConflictCheck = do
  forAll (genConfigDataWithValues 10 50) $ \ cfg ->
    forAll (genExclusiveNodeOp cfg) $ \ op1 ->
      forAll (genExclusiveNodeOp cfg) $ \ op2 ->
        forAll (genExclusiveNodeOp cfg) $ \ op3 ->
          let w1 = staticWeight cfg (Just op1) [op3]
              w2 = staticWeight cfg (Just op2) [op3]
              nName1 = opNodeName op1
              nName2 = opNodeName op2
              nName3 = opNodeName op3
              testResult
                | nName1 == nName2 = True
                | nName1 == nName3 = (w2 <= w1)
                | nName2 == nName3 = (w1 <= w2)
                | otherwise = True
          in testResult

case_queueLockOpOrder :: Assertion
case_queueLockOpOrder = do
  cfg <- generate $ genConfigDataWithValues 10 50
  diagnoseOp <- generate $ genOpCodeFromId "OP_OS_DIAGNOSE" (Just cfg)
  networkAddOp <- generate $ genOpCodeFromId "OP_NETWORK_ADD" (Just cfg)
  groupVerifyOp <- generate $ genOpCodeFromId "OP_GROUP_VERIFY_DISKS" (Just cfg)
  nodeAddOp <- generate $ genOpCodeFromId "OP_NODE_ADD" (Just cfg)
  currentOp <- generate $ genExclusiveInstanceOp cfg
  let w1 = staticWeight cfg (Just diagnoseOp) [currentOp]
      w2 = staticWeight cfg (Just networkAddOp) [currentOp]
      w3 = staticWeight cfg (Just groupVerifyOp) [currentOp]
      w4 = staticWeight cfg (Just nodeAddOp) [currentOp]
      weights = [w1, w2, w3, w4]
  assertEqual "weights should be sorted"
    weights
    (sort weights)


testSuite "LockDecls" [ 'prop_staticWeight
                      , 'prop_instNameConflictCheck
                      , 'prop_nodeNameConflictCheck
                      , 'case_queueLockOpOrder ]

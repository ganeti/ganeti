{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Test.Ganeti.HTools.Backend.Text (testHTools_Backend_Text) where

import Test.QuickCheck

import qualified Data.Map as Map
import Data.List
import Data.Maybe
import System.Time (ClockTime(..))

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools
import Test.Ganeti.HTools.Instance (genInstanceSmallerThanNode,
                                    genInstanceOnNodeList)
import Test.Ganeti.HTools.Node (genNode, genOnlineNode, genEmptyOnlineNode
                               , genUniqueNodeList)

import Ganeti.BasicTypes
import qualified Ganeti.HTools.AlgorithmParams as Alg
import qualified Ganeti.HTools.Backend.Text as Text
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.Utils as Utils

-- * Instance text loader tests

prop_Load_Instance :: String -> Int -> Int -> Int -> Types.InstanceStatus
                   -> NonEmptyList Char -> String
                   -> NonNegative Int -> NonNegative Int -> Bool
                   -> Types.DiskTemplate -> Int -> Property
prop_Load_Instance name mem dsk vcpus status
                   (NonEmpty pnode) snode
                   (NonNegative pdx) (NonNegative sdx) autobal dt su =
  pnode /= snode && pdx /= sdx ==>
  let vcpus_s = show vcpus
      dsk_s = show dsk
      mem_s = show mem
      su_s = show su
      status_s = Types.instanceStatusToRaw status
      ndx = if null snode
              then [(pnode, pdx)]
              else [(pnode, pdx), (snode, sdx)]
      nl = Map.fromList ndx
      tags = ""
      sbal = if autobal then "Y" else "N"
      sdt = Types.diskTemplateToRaw dt
      inst = Text.loadInst nl
             [name, mem_s, dsk_s, vcpus_s, status_s,
              sbal, pnode, snode, sdt, tags, su_s]
      fail1 = Text.loadInst nl
              [name, mem_s, dsk_s, vcpus_s, status_s,
               sbal, pnode, pnode, tags]
  in case inst of
       Bad msg -> failTest $ "Failed to load instance: " ++ msg
       Ok (_, i) -> counterexample "Mismatch in some field while\
                                   \ loading the instance" $
               Instance.name i == name &&
               Instance.vcpus i == vcpus &&
               Instance.mem i == mem &&
               Instance.pNode i == pdx &&
               Instance.sNode i == (if null snode
                                      then Node.noSecondary
                                      else sdx) &&
               Instance.autoBalance i == autobal &&
               Instance.spindleUse i == su &&
               isBad fail1

prop_Load_InstanceFail :: [(String, Int)] -> [String] -> Property
prop_Load_InstanceFail ktn fields =
  length fields < 10 || length fields > 12 ==>
    case Text.loadInst nl fields of
      Ok _ -> failTest "Managed to load instance from invalid data"
      Bad msg -> counterexample ("Unrecognised error message: " ++ msg) $
                 "Invalid/incomplete instance data: '" `isPrefixOf` msg
    where nl = Map.fromList ktn

genInstanceNodes :: Gen (Instance.Instance, Node.List, Types.NameAssoc)
genInstanceNodes = do
    (nl, na) <- genUniqueNodeList genOnlineNode
    inst <- genInstanceOnNodeList nl
    return (inst, nl, na)

prop_InstanceLSIdempotent :: Property
prop_InstanceLSIdempotent =
  forAll genInstanceNodes $ \(inst, nl, assoc) ->
    (Text.loadInst assoc . Utils.sepSplit '|' . Text.serializeInstance nl)
    inst ==? Ok (Instance.name inst, inst)

prop_Load_Node :: String -> Int -> Int -> Int -> Int -> Int
               -> Int -> Bool -> Bool
prop_Load_Node name tm nm fm td fd tc fo =
  let conv v = if v < 0
                 then "?"
                 else show v
      tm_s = conv tm
      nm_s = conv nm
      fm_s = conv fm
      td_s = conv td
      fd_s = conv fd
      tc_s = conv tc
      fo_s = if fo
               then "Y"
               else "N"
      any_broken = any (< 0) [tm, nm, fm, td, fd, tc]
      gid = Group.uuid defGroup
  in case Text.loadNode defGroupAssoc
       [name, tm_s, nm_s, fm_s, td_s, fd_s, tc_s, fo_s, gid] of
       Nothing -> False
       Just (name', node) ->
         if fo || any_broken
           then Node.offline node
           else Node.name node == name' && name' == name &&
                Node.alias node == name &&
                Node.tMem node == fromIntegral tm &&
                Node.nMem node == nm &&
                Node.fMem node == fm &&
                Node.tDsk node == fromIntegral td &&
                Node.fDsk node == fd &&
                Node.tCpu node == fromIntegral tc

prop_Load_NodeFail :: [String] -> Property
prop_Load_NodeFail fields =
  length fields /= 8 ==> isNothing $ Text.loadNode Map.empty fields

prop_NodeLSIdempotent :: Property
prop_NodeLSIdempotent =
  forAll (genNode (Just 1) Nothing) $ \node ->
  -- override failN1 to what loadNode returns by default
  let n = Node.setPolicy Types.defIPolicy $
          node { Node.failN1 = True, Node.offline = False }
  in
    (Text.loadNode defGroupAssoc.
         Utils.sepSplit '|' . Text.serializeNode defGroupList) n ==?
    Just (Node.name n, n)

prop_ISpecIdempotent :: Types.ISpec -> Property
prop_ISpecIdempotent ispec =
  case Text.loadISpec "dummy" . Utils.sepSplit ',' .
       Text.serializeISpec $ ispec of
    Bad msg -> failTest $ "Failed to load ispec: " ++ msg
    Ok ispec' -> ispec ==? ispec'

prop_MultipleMinMaxISpecsIdempotent :: [Types.MinMaxISpecs] -> Property
prop_MultipleMinMaxISpecsIdempotent minmaxes =
  case Text.loadMultipleMinMaxISpecs "dummy" . Utils.sepSplit ';' .
       Text.serializeMultipleMinMaxISpecs $ minmaxes of
    Bad msg -> failTest $ "Failed to load min/max ispecs: " ++ msg
    Ok minmaxes' -> minmaxes ==? minmaxes'

prop_IPolicyIdempotent :: Types.IPolicy -> Property
prop_IPolicyIdempotent ipol =
  case Text.loadIPolicy . Utils.sepSplit '|' $
       Text.serializeIPolicy owner ipol of
    Bad msg -> failTest $ "Failed to load ispec: " ++ msg
    Ok res -> (owner, ipol) ==? res
  where owner = "dummy"

-- | This property, while being in the text tests, does more than just
-- test end-to-end the serialisation and loading back workflow; it
-- also tests the Loader.mergeData and the actual
-- Cluster.iterateAlloc (for well-behaving w.r.t. instance
-- allocations, not for the business logic). As such, it's a quite
-- complex and slow test, and that's the reason we restrict it to
-- small cluster sizes.
prop_CreateSerialise :: Property
prop_CreateSerialise =
  forAll genTags $ \ctags ->
  forAll (choose (1, 20)) $ \maxiter ->
  forAll (choose (2, 10)) $ \count ->
  forAll genEmptyOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let nl = makeSmallCluster node count
      reqnodes = Instance.requiredNodes $ Instance.diskTemplate inst
      opts = Alg.defaultOptions
  in case Cluster.genAllocNodes defGroupList nl reqnodes True >>= \allocn ->
     Cluster.iterateAlloc opts nl Container.empty (Just maxiter) inst allocn
                          [] []
     of
       Bad msg -> failTest $ "Failed to allocate: " ++ msg
       Ok (_, _, _, [], _) -> counterexample
                              "Failed to allocate: no allocations" False
       Ok (_, nl', il', _, _) ->
         let cdata = Loader.ClusterData defGroupList nl' il' ctags
                     Types.defIPolicy
             saved = Text.serializeCluster cdata
         in case Text.parseData saved >>= Loader.mergeData [] [] [] [] (TOD 0 0)
            of
              Bad msg -> failTest $ "Failed to load/merge: " ++ msg
              Ok (Loader.ClusterData gl2 nl2 il2 ctags2 cpol2) ->
                let (_, nl3) = Loader.checkData nl2 il2
                in conjoin [ ctags ==? ctags2
                           , Types.defIPolicy ==? cpol2
                           , il' ==? il2
                           , defGroupList ==? gl2
                           , nl' ==? nl3
                           ]

testSuite "HTools/Backend/Text"
            [ 'prop_Load_Instance
            , 'prop_Load_InstanceFail
            , 'prop_InstanceLSIdempotent
            , 'prop_Load_Node
            , 'prop_Load_NodeFail
            , 'prop_NodeLSIdempotent
            , 'prop_ISpecIdempotent
            , 'prop_MultipleMinMaxISpecsIdempotent
            , 'prop_IPolicyIdempotent
            , 'prop_CreateSerialise
            ]

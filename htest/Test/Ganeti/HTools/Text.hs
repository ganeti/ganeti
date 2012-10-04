{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Test.Ganeti.HTools.Text (testHTools_Text) where

import Test.QuickCheck

import qualified Data.Map as Map
import Data.List
import Data.Maybe

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools
import Test.Ganeti.HTools.Instance (genInstanceSmallerThanNode)
import Test.Ganeti.HTools.Node (genNode, genOnlineNode)

import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Text as Text
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
       Types.Bad msg -> failTest $ "Failed to load instance: " ++ msg
       Types.Ok (_, i) -> printTestCase "Mismatch in some field while\
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
               Types.isBad fail1

prop_Load_InstanceFail :: [(String, Int)] -> [String] -> Property
prop_Load_InstanceFail ktn fields =
  length fields /= 10 && length fields /= 11 ==>
    case Text.loadInst nl fields of
      Types.Ok _ -> failTest "Managed to load instance from invalid data"
      Types.Bad msg -> printTestCase ("Unrecognised error message: " ++ msg) $
                       "Invalid/incomplete instance data: '" `isPrefixOf` msg
    where nl = Map.fromList ktn

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
    Types.Bad msg -> failTest $ "Failed to load ispec: " ++ msg
    Types.Ok ispec' -> ispec ==? ispec'

prop_IPolicyIdempotent :: Types.IPolicy -> Property
prop_IPolicyIdempotent ipol =
  case Text.loadIPolicy . Utils.sepSplit '|' $
       Text.serializeIPolicy owner ipol of
    Types.Bad msg -> failTest $ "Failed to load ispec: " ++ msg
    Types.Ok res -> (owner, ipol) ==? res
  where owner = "dummy"

-- | This property, while being in the text tests, does more than just
-- test end-to-end the serialisation and loading back workflow; it
-- also tests the Loader.mergeData and the actuall
-- Cluster.iterateAlloc (for well-behaving w.r.t. instance
-- allocations, not for the business logic). As such, it's a quite
-- complex and slow test, and that's the reason we restrict it to
-- small cluster sizes.
prop_CreateSerialise :: Property
prop_CreateSerialise =
  forAll genTags $ \ctags ->
  forAll (choose (1, 20)) $ \maxiter ->
  forAll (choose (2, 10)) $ \count ->
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let nl = makeSmallCluster node count
      reqnodes = Instance.requiredNodes $ Instance.diskTemplate inst
  in case Cluster.genAllocNodes defGroupList nl reqnodes True >>= \allocn ->
     Cluster.iterateAlloc nl Container.empty (Just maxiter) inst allocn [] []
     of
       Types.Bad msg -> failTest $ "Failed to allocate: " ++ msg
       Types.Ok (_, _, _, [], _) -> printTestCase
                                    "Failed to allocate: no allocations" False
       Types.Ok (_, nl', il', _, _) ->
         let cdata = Loader.ClusterData defGroupList nl' il' ctags
                     Types.defIPolicy
             saved = Text.serializeCluster cdata
         in case Text.parseData saved >>= Loader.mergeData [] [] [] [] of
              Types.Bad msg -> failTest $ "Failed to load/merge: " ++ msg
              Types.Ok (Loader.ClusterData gl2 nl2 il2 ctags2 cpol2) ->
                ctags ==? ctags2 .&&.
                Types.defIPolicy ==? cpol2 .&&.
                il' ==? il2 .&&.
                defGroupList ==? gl2 .&&.
                nl' ==? nl2

testSuite "HTools/Text"
            [ 'prop_Load_Instance
            , 'prop_Load_InstanceFail
            , 'prop_Load_Node
            , 'prop_Load_NodeFail
            , 'prop_NodeLSIdempotent
            , 'prop_ISpecIdempotent
            , 'prop_IPolicyIdempotent
            , 'prop_CreateSerialise
            ]

{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011 Google Inc.

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

module Ganeti.HTools.QC
  ( testUtils
  , testPeerMap
  , testContainer
  , testInstance
  , testNode
  , testText
  , testOpCodes
  , testJobs
  , testCluster
  , testLoader
  , testTypes
  ) where

import Test.QuickCheck
import Data.List (findIndex, intercalate, nub, isPrefixOf)
import Data.Maybe
import Control.Monad
import qualified Text.JSON as J
import qualified Data.Map
import qualified Data.IntMap as IntMap
import qualified Ganeti.OpCodes as OpCodes
import qualified Ganeti.Jobs as Jobs
import qualified Ganeti.Luxi
import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.ExtLoader
import qualified Ganeti.HTools.IAlloc as IAlloc
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Luxi
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.PeerMap as PeerMap
import qualified Ganeti.HTools.Rapi
import qualified Ganeti.HTools.Simu
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Utils as Utils
import qualified Ganeti.HTools.Version
import qualified Ganeti.Constants as C

import qualified Ganeti.HTools.Program.Hail
import qualified Ganeti.HTools.Program.Hbal
import qualified Ganeti.HTools.Program.Hscan
import qualified Ganeti.HTools.Program.Hspace

import Ganeti.HTools.QCHelper (testSuite)

-- * Constants

-- | Maximum memory (1TiB, somewhat random value).
maxMem :: Int
maxMem = 1024 * 1024

-- | Maximum disk (8TiB, somewhat random value).
maxDsk :: Int
maxDsk = 1024 * 1024 * 8

-- | Max CPUs (1024, somewhat random value).
maxCpu :: Int
maxCpu = 1024

defGroup :: Group.Group
defGroup = flip Group.setIdx 0 $
             Group.create "default" Utils.defaultGroupID Types.AllocPreferred

defGroupList :: Group.List
defGroupList = Container.fromList [(Group.idx defGroup, defGroup)]

defGroupAssoc :: Data.Map.Map String Types.Gdx
defGroupAssoc = Data.Map.singleton (Group.uuid defGroup) (Group.idx defGroup)

-- * Helper functions

-- | Simple checker for whether OpResult is fail or pass.
isFailure :: Types.OpResult a -> Bool
isFailure (Types.OpFail _) = True
isFailure _ = False

-- | Checks for equality with proper annotation.
(==?) :: (Show a, Eq a) => a -> a -> Property
(==?) x y = printTestCase
            ("Expected equality, but '" ++
             show x ++ "' /= '" ++ show y ++ "'") (x == y)
infix 3 ==?

-- | Update an instance to be smaller than a node.
setInstanceSmallerThanNode node inst =
  inst { Instance.mem = Node.availMem node `div` 2
       , Instance.dsk = Node.availDisk node `div` 2
       , Instance.vcpus = Node.availCpu node `div` 2
       }

-- | Create an instance given its spec.
createInstance mem dsk vcpus =
  Instance.create "inst-unnamed" mem dsk vcpus Types.Running [] True (-1) (-1)
    Types.DTDrbd8

-- | Create a small cluster by repeating a node spec.
makeSmallCluster :: Node.Node -> Int -> Node.List
makeSmallCluster node count =
  let fn = Node.buildPeers node Container.empty
      namelst = map (\n -> (Node.name n, n)) (replicate count fn)
      (_, nlst) = Loader.assignIndices namelst
  in nlst

-- | Make a small cluster, both nodes and instances.
makeSmallEmptyCluster :: Node.Node -> Int -> Instance.Instance
                      -> (Node.List, Instance.List, Instance.Instance)
makeSmallEmptyCluster node count inst =
  (makeSmallCluster node count, Container.empty,
   setInstanceSmallerThanNode node inst)

-- | Checks if a node is "big" enough.
isNodeBig :: Node.Node -> Int -> Bool
isNodeBig node size = Node.availDisk node > size * Types.unitDsk
                      && Node.availMem node > size * Types.unitMem
                      && Node.availCpu node > size * Types.unitCpu

canBalance :: Cluster.Table -> Bool -> Bool -> Bool -> Bool
canBalance tbl dm im evac = isJust $ Cluster.tryBalance tbl dm im evac 0 0

-- | Assigns a new fresh instance to a cluster; this is not
-- allocation, so no resource checks are done.
assignInstance :: Node.List -> Instance.List -> Instance.Instance ->
                  Types.Idx -> Types.Idx ->
                  (Node.List, Instance.List)
assignInstance nl il inst pdx sdx =
  let pnode = Container.find pdx nl
      snode = Container.find sdx nl
      maxiidx = if Container.null il
                  then 0
                  else fst (Container.findMax il) + 1
      inst' = inst { Instance.idx = maxiidx,
                     Instance.pNode = pdx, Instance.sNode = sdx }
      pnode' = Node.setPri pnode inst'
      snode' = Node.setSec snode inst'
      nl' = Container.addTwo pdx pnode' sdx snode' nl
      il' = Container.add maxiidx inst' il
  in (nl', il')

-- * Arbitrary instances

-- | Defines a DNS name.
newtype DNSChar = DNSChar { dnsGetChar::Char }

instance Arbitrary DNSChar where
  arbitrary = do
    x <- elements (['a'..'z'] ++ ['0'..'9'] ++ "_-")
    return (DNSChar x)

getName :: Gen String
getName = do
  n <- choose (1, 64)
  dn <- vector n::Gen [DNSChar]
  return (map dnsGetChar dn)

getFQDN :: Gen String
getFQDN = do
  felem <- getName
  ncomps <- choose (1, 4)
  frest <- vector ncomps::Gen [[DNSChar]]
  let frest' = map (map dnsGetChar) frest
  return (felem ++ "." ++ intercalate "." frest')

instance Arbitrary Types.InstanceStatus where
    arbitrary = elements [minBound..maxBound]

-- let's generate a random instance
instance Arbitrary Instance.Instance where
  arbitrary = do
    name <- getFQDN
    mem <- choose (0, maxMem)
    dsk <- choose (0, maxDsk)
    run_st <- arbitrary
    pn <- arbitrary
    sn <- arbitrary
    vcpus <- choose (0, maxCpu)
    return $ Instance.create name mem dsk vcpus run_st [] True pn sn
              Types.DTDrbd8

-- | Generas an arbitrary node based on sizing information.
genNode :: Maybe Int -- ^ Minimum node size in terms of units
        -> Maybe Int -- ^ Maximum node size (when Nothing, bounded
                     -- just by the max... constants)
        -> Gen Node.Node
genNode min_multiplier max_multiplier = do
  let (base_mem, base_dsk, base_cpu) =
        case min_multiplier of
          Just mm -> (mm * Types.unitMem,
                      mm * Types.unitDsk,
                      mm * Types.unitCpu)
          Nothing -> (0, 0, 0)
      (top_mem, top_dsk, top_cpu)  =
        case max_multiplier of
          Just mm -> (mm * Types.unitMem,
                      mm * Types.unitDsk,
                      mm * Types.unitCpu)
          Nothing -> (maxMem, maxDsk, maxCpu)
  name  <- getFQDN
  mem_t <- choose (base_mem, top_mem)
  mem_f <- choose (base_mem, mem_t)
  mem_n <- choose (0, mem_t - mem_f)
  dsk_t <- choose (base_dsk, top_dsk)
  dsk_f <- choose (base_dsk, dsk_t)
  cpu_t <- choose (base_cpu, top_cpu)
  offl  <- arbitrary
  let n = Node.create name (fromIntegral mem_t) mem_n mem_f
          (fromIntegral dsk_t) dsk_f (fromIntegral cpu_t) offl 0
  return $ Node.buildPeers n Container.empty

-- and a random node
instance Arbitrary Node.Node where
  arbitrary = genNode Nothing Nothing

-- replace disks
instance Arbitrary OpCodes.ReplaceDisksMode where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary OpCodes.OpCode where
  arbitrary = do
    op_id <- elements [ "OP_TEST_DELAY"
                      , "OP_INSTANCE_REPLACE_DISKS"
                      , "OP_INSTANCE_FAILOVER"
                      , "OP_INSTANCE_MIGRATE"
                      ]
    case op_id of
      "OP_TEST_DELAY" ->
        liftM3 OpCodes.OpTestDelay arbitrary arbitrary arbitrary
      "OP_INSTANCE_REPLACE_DISKS" ->
        liftM5 OpCodes.OpInstanceReplaceDisks arbitrary arbitrary
          arbitrary arbitrary arbitrary
      "OP_INSTANCE_FAILOVER" ->
        liftM3 OpCodes.OpInstanceFailover arbitrary arbitrary
          arbitrary
      "OP_INSTANCE_MIGRATE" ->
        liftM5 OpCodes.OpInstanceMigrate arbitrary arbitrary
          arbitrary arbitrary arbitrary
      _ -> fail "Wrong opcode"

instance Arbitrary Jobs.OpStatus where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Jobs.JobStatus where
  arbitrary = elements [minBound..maxBound]

newtype SmallRatio = SmallRatio Double deriving Show
instance Arbitrary SmallRatio where
  arbitrary = do
    v <- choose (0, 1)
    return $ SmallRatio v

instance Arbitrary Types.AllocPolicy where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Types.DiskTemplate where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Types.FailMode where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary a => Arbitrary (Types.OpResult a) where
  arbitrary = arbitrary >>= \c ->
              if c
                then liftM Types.OpGood arbitrary
                else liftM Types.OpFail arbitrary

-- * Actual tests

-- ** Utils tests

-- | If the list is not just an empty element, and if the elements do
-- not contain commas, then join+split should be idempotent.
prop_Utils_commaJoinSplit =
  forAll (arbitrary `suchThat`
          (\l -> l /= [""] && all (notElem ',') l )) $ \lst ->
  Utils.sepSplit ',' (Utils.commaJoin lst) ==? lst

-- | Split and join should always be idempotent.
prop_Utils_commaSplitJoin s =
  Utils.commaJoin (Utils.sepSplit ',' s) ==? s

-- | fromObjWithDefault, we test using the Maybe monad and an integer
-- value.
prop_Utils_fromObjWithDefault def_value random_key =
  -- a missing key will be returned with the default
  Utils.fromObjWithDefault [] random_key def_value == Just def_value &&
  -- a found key will be returned as is, not with default
  Utils.fromObjWithDefault [(random_key, J.showJSON def_value)]
       random_key (def_value+1) == Just def_value
    where _types = def_value :: Integer

-- | Test that functional if' behaves like the syntactic sugar if.
prop_Utils_if'if :: Bool -> Int -> Int -> Gen Prop
prop_Utils_if'if cnd a b =
  Utils.if' cnd a b ==? if cnd then a else b

-- | Test basic select functionality
prop_Utils_select :: Int      -- ^ Default result
                  -> [Int]    -- ^ List of False values
                  -> [Int]    -- ^ List of True values
                  -> Gen Prop -- ^ Test result
prop_Utils_select def lst1 lst2 =
  Utils.select def (flist ++ tlist) ==? expectedresult
  where expectedresult = Utils.if' (null lst2) def (head lst2)
        flist = map (\e -> (False, e)) lst1
        tlist = map (\e -> (True, e)) lst2

-- | Test basic select functionality with undefined default
prop_Utils_select_undefd :: [Int]            -- ^ List of False values
                         -> NonEmptyList Int -- ^ List of True values
                         -> Gen Prop         -- ^ Test result
prop_Utils_select_undefd lst1 (NonEmpty lst2) =
  Utils.select undefined (flist ++ tlist) ==? head lst2
  where flist = map (\e -> (False, e)) lst1
        tlist = map (\e -> (True, e)) lst2

-- | Test basic select functionality with undefined list values
prop_Utils_select_undefv :: [Int]            -- ^ List of False values
                         -> NonEmptyList Int -- ^ List of True values
                         -> Gen Prop         -- ^ Test result
prop_Utils_select_undefv lst1 (NonEmpty lst2) =
  Utils.select undefined cndlist ==? head lst2
  where flist = map (\e -> (False, e)) lst1
        tlist = map (\e -> (True, e)) lst2
        cndlist = flist ++ tlist ++ [undefined]

prop_Utils_parseUnit (NonNegative n) =
  Utils.parseUnit (show n) == Types.Ok n &&
  Utils.parseUnit (show n ++ "m") == Types.Ok n &&
  (case Utils.parseUnit (show n ++ "M") of
     Types.Ok m -> if n > 0
                     then m < n  -- for positive values, X MB is < than X MiB
                     else m == 0 -- but for 0, 0 MB == 0 MiB
     Types.Bad _ -> False) &&
  Utils.parseUnit (show n ++ "g") == Types.Ok (n*1024) &&
  Utils.parseUnit (show n ++ "t") == Types.Ok (n*1048576) &&
  Types.isBad (Utils.parseUnit (show n ++ "x")::Types.Result Int)
    where _types = n::Int

-- | Test list for the Utils module.
testSuite "Utils"
            [ 'prop_Utils_commaJoinSplit
            , 'prop_Utils_commaSplitJoin
            , 'prop_Utils_fromObjWithDefault
            , 'prop_Utils_if'if
            , 'prop_Utils_select
            , 'prop_Utils_select_undefd
            , 'prop_Utils_select_undefv
            , 'prop_Utils_parseUnit
            ]

-- ** PeerMap tests

-- | Make sure add is idempotent.
prop_PeerMap_addIdempotent pmap key em =
  fn puniq ==? fn (fn puniq)
    where _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key, em::PeerMap.Elem)
          fn = PeerMap.add key em
          puniq = PeerMap.accumArray const pmap

-- | Make sure remove is idempotent.
prop_PeerMap_removeIdempotent pmap key =
  fn puniq ==? fn (fn puniq)
    where _types = (pmap::PeerMap.PeerMap, key::PeerMap.Key)
          fn = PeerMap.remove key
          puniq = PeerMap.accumArray const pmap

-- | Make sure a missing item returns 0.
prop_PeerMap_findMissing pmap key =
  PeerMap.find key (PeerMap.remove key puniq) ==? 0
    where _types = (pmap::PeerMap.PeerMap, key::PeerMap.Key)
          puniq = PeerMap.accumArray const pmap

-- | Make sure an added item is found.
prop_PeerMap_addFind pmap key em =
  PeerMap.find key (PeerMap.add key em puniq) ==? em
    where _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key, em::PeerMap.Elem)
          puniq = PeerMap.accumArray const pmap

-- | Manual check that maxElem returns the maximum indeed, or 0 for null.
prop_PeerMap_maxElem pmap =
  PeerMap.maxElem puniq ==? if null puniq then 0
                              else (maximum . snd . unzip) puniq
    where _types = pmap::PeerMap.PeerMap
          puniq = PeerMap.accumArray const pmap

-- | List of tests for the PeerMap module.
testSuite "PeerMap"
            [ 'prop_PeerMap_addIdempotent
            , 'prop_PeerMap_removeIdempotent
            , 'prop_PeerMap_maxElem
            , 'prop_PeerMap_addFind
            , 'prop_PeerMap_findMissing
            ]

-- ** Container tests

-- we silence the following due to hlint bug fixed in later versions
{-# ANN prop_Container_addTwo "HLint: ignore Avoid lambda" #-}
prop_Container_addTwo cdata i1 i2 =
  fn i1 i2 cont == fn i2 i1 cont &&
  fn i1 i2 cont == fn i1 i2 (fn i1 i2 cont)
    where _types = (cdata::[Int],
                    i1::Int, i2::Int)
          cont = foldl (\c x -> Container.add x x c) Container.empty cdata
          fn x1 x2 = Container.addTwo x1 x1 x2 x2

prop_Container_nameOf node =
  let nl = makeSmallCluster node 1
      fnode = head (Container.elems nl)
  in Container.nameOf nl (Node.idx fnode) ==? Node.name fnode

-- | We test that in a cluster, given a random node, we can find it by
-- its name and alias, as long as all names and aliases are unique,
-- and that we fail to find a non-existing name.
prop_Container_findByName node othername =
  forAll (choose (1, 20)) $ \ cnt ->
  forAll (choose (0, cnt - 1)) $ \ fidx ->
  forAll (vector cnt) $ \ names ->
  (length . nub) (map fst names ++ map snd names) ==
  length names * 2 &&
  othername `notElem` (map fst names ++ map snd names) ==>
  let nl = makeSmallCluster node cnt
      nodes = Container.elems nl
      nodes' = map (\((name, alias), nn) -> (Node.idx nn,
                                             nn { Node.name = name,
                                                  Node.alias = alias }))
               $ zip names nodes
      nl' = Container.fromList nodes'
      target = snd (nodes' !! fidx)
  in Container.findByName nl' (Node.name target) == Just target &&
     Container.findByName nl' (Node.alias target) == Just target &&
     isNothing (Container.findByName nl' othername)

testSuite "Container"
            [ 'prop_Container_addTwo
            , 'prop_Container_nameOf
            , 'prop_Container_findByName
            ]

-- ** Instance tests

-- Simple instance tests, we only have setter/getters

prop_Instance_creat inst =
  Instance.name inst ==? Instance.alias inst

prop_Instance_setIdx inst idx =
  Instance.idx (Instance.setIdx inst idx) ==? idx
    where _types = (inst::Instance.Instance, idx::Types.Idx)

prop_Instance_setName inst name =
  Instance.name newinst == name &&
  Instance.alias newinst == name
    where _types = (inst::Instance.Instance, name::String)
          newinst = Instance.setName inst name

prop_Instance_setAlias inst name =
  Instance.name newinst == Instance.name inst &&
  Instance.alias newinst == name
    where _types = (inst::Instance.Instance, name::String)
          newinst = Instance.setAlias inst name

prop_Instance_setPri inst pdx =
  Instance.pNode (Instance.setPri inst pdx) ==? pdx
    where _types = (inst::Instance.Instance, pdx::Types.Ndx)

prop_Instance_setSec inst sdx =
  Instance.sNode (Instance.setSec inst sdx) ==? sdx
    where _types = (inst::Instance.Instance, sdx::Types.Ndx)

prop_Instance_setBoth inst pdx sdx =
  Instance.pNode si == pdx && Instance.sNode si == sdx
    where _types = (inst::Instance.Instance, pdx::Types.Ndx, sdx::Types.Ndx)
          si = Instance.setBoth inst pdx sdx

prop_Instance_shrinkMG inst =
  Instance.mem inst >= 2 * Types.unitMem ==>
    case Instance.shrinkByType inst Types.FailMem of
      Types.Ok inst' -> Instance.mem inst' == Instance.mem inst - Types.unitMem
      _ -> False

prop_Instance_shrinkMF inst =
  forAll (choose (0, 2 * Types.unitMem - 1)) $ \mem ->
    let inst' = inst { Instance.mem = mem}
    in Types.isBad $ Instance.shrinkByType inst' Types.FailMem

prop_Instance_shrinkCG inst =
  Instance.vcpus inst >= 2 * Types.unitCpu ==>
    case Instance.shrinkByType inst Types.FailCPU of
      Types.Ok inst' ->
        Instance.vcpus inst' == Instance.vcpus inst - Types.unitCpu
      _ -> False

prop_Instance_shrinkCF inst =
  forAll (choose (0, 2 * Types.unitCpu - 1)) $ \vcpus ->
    let inst' = inst { Instance.vcpus = vcpus }
    in Types.isBad $ Instance.shrinkByType inst' Types.FailCPU

prop_Instance_shrinkDG inst =
  Instance.dsk inst >= 2 * Types.unitDsk ==>
    case Instance.shrinkByType inst Types.FailDisk of
      Types.Ok inst' ->
        Instance.dsk inst' == Instance.dsk inst - Types.unitDsk
      _ -> False

prop_Instance_shrinkDF inst =
  forAll (choose (0, 2 * Types.unitDsk - 1)) $ \dsk ->
    let inst' = inst { Instance.dsk = dsk }
    in Types.isBad $ Instance.shrinkByType inst' Types.FailDisk

prop_Instance_setMovable inst m =
  Instance.movable inst' ==? m
    where inst' = Instance.setMovable inst m

testSuite "Instance"
            [ 'prop_Instance_creat
            , 'prop_Instance_setIdx
            , 'prop_Instance_setName
            , 'prop_Instance_setAlias
            , 'prop_Instance_setPri
            , 'prop_Instance_setSec
            , 'prop_Instance_setBoth
            , 'prop_Instance_shrinkMG
            , 'prop_Instance_shrinkMF
            , 'prop_Instance_shrinkCG
            , 'prop_Instance_shrinkCF
            , 'prop_Instance_shrinkDG
            , 'prop_Instance_shrinkDF
            , 'prop_Instance_setMovable
            ]

-- ** Text backend tests

-- Instance text loader tests

prop_Text_Load_Instance name mem dsk vcpus status
                        (NonEmpty pnode) snode
                        (NonNegative pdx) (NonNegative sdx) autobal dt =
  pnode /= snode && pdx /= sdx ==>
  let vcpus_s = show vcpus
      dsk_s = show dsk
      mem_s = show mem
      status_s = Types.instanceStatusToRaw status
      ndx = if null snode
              then [(pnode, pdx)]
              else [(pnode, pdx), (snode, sdx)]
      nl = Data.Map.fromList ndx
      tags = ""
      sbal = if autobal then "Y" else "N"
      sdt = Types.diskTemplateToRaw dt
      inst = Text.loadInst nl
             [name, mem_s, dsk_s, vcpus_s, status_s,
              sbal, pnode, snode, sdt, tags]
      fail1 = Text.loadInst nl
              [name, mem_s, dsk_s, vcpus_s, status_s,
               sbal, pnode, pnode, tags]
      _types = ( name::String, mem::Int, dsk::Int
               , vcpus::Int, status::Types.InstanceStatus
               , snode::String
               , autobal::Bool)
  in case inst of
       Types.Bad msg -> printTestCase ("Failed to load instance: " ++ msg)
                        False
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
               Types.isBad fail1

prop_Text_Load_InstanceFail ktn fields =
  length fields /= 10 ==>
    case Text.loadInst nl fields of
      Types.Ok _ -> printTestCase "Managed to load instance from invalid\
                                  \ data" False
      Types.Bad msg -> printTestCase ("Unrecognised error message: " ++ msg) $
                       "Invalid/incomplete instance data: '" `isPrefixOf` msg
    where nl = Data.Map.fromList ktn

prop_Text_Load_Node name tm nm fm td fd tc fo =
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

prop_Text_Load_NodeFail fields =
  length fields /= 8 ==> isNothing $ Text.loadNode Data.Map.empty fields

prop_Text_NodeLSIdempotent node =
  (Text.loadNode defGroupAssoc.
       Utils.sepSplit '|' . Text.serializeNode defGroupList) n ==
  Just (Node.name n, n)
    -- override failN1 to what loadNode returns by default
    where n = node { Node.failN1 = True, Node.offline = False }

testSuite "Text"
            [ 'prop_Text_Load_Instance
            , 'prop_Text_Load_InstanceFail
            , 'prop_Text_Load_Node
            , 'prop_Text_Load_NodeFail
            , 'prop_Text_NodeLSIdempotent
            ]

-- ** Node tests

prop_Node_setAlias node name =
  Node.name newnode == Node.name node &&
  Node.alias newnode == name
    where _types = (node::Node.Node, name::String)
          newnode = Node.setAlias node name

prop_Node_setOffline node status =
  Node.offline newnode ==? status
    where newnode = Node.setOffline node status

prop_Node_setXmem node xm =
  Node.xMem newnode ==? xm
    where newnode = Node.setXmem node xm

prop_Node_setMcpu node mc =
  Node.mCpu newnode ==? mc
    where newnode = Node.setMcpu node mc

-- | Check that an instance add with too high memory or disk will be
-- rejected.
prop_Node_addPriFM node inst =
  Instance.mem inst >= Node.fMem node && not (Node.failN1 node) &&
  not (Instance.instanceOffline inst) ==>
  case Node.addPri node inst'' of
    Types.OpFail Types.FailMem -> True
    _ -> False
  where _types = (node::Node.Node, inst::Instance.Instance)
        inst' = setInstanceSmallerThanNode node inst
        inst'' = inst' { Instance.mem = Instance.mem inst }

prop_Node_addPriFD node inst =
  Instance.dsk inst >= Node.fDsk node && not (Node.failN1 node) ==>
    case Node.addPri node inst'' of
      Types.OpFail Types.FailDisk -> True
      _ -> False
    where _types = (node::Node.Node, inst::Instance.Instance)
          inst' = setInstanceSmallerThanNode node inst
          inst'' = inst' { Instance.dsk = Instance.dsk inst }

prop_Node_addPriFC node inst (Positive extra) =
  not (Node.failN1 node) && not (Instance.instanceOffline inst) ==>
      case Node.addPri node inst'' of
        Types.OpFail Types.FailCPU -> True
        _ -> False
    where _types = (node::Node.Node, inst::Instance.Instance)
          inst' = setInstanceSmallerThanNode node inst
          inst'' = inst' { Instance.vcpus = Node.availCpu node + extra }

-- | Check that an instance add with too high memory or disk will be
-- rejected.
prop_Node_addSec node inst pdx =
  ((Instance.mem inst >= (Node.fMem node - Node.rMem node) &&
    not (Instance.instanceOffline inst)) ||
   Instance.dsk inst >= Node.fDsk node) &&
  not (Node.failN1 node) ==>
      isFailure (Node.addSec node inst pdx)
        where _types = (node::Node.Node, inst::Instance.Instance, pdx::Int)

-- | Check that an offline instance with reasonable disk size can always
-- be added.
prop_Node_addPriOffline =
  forAll (arbitrary `suchThat` ((> 0) . Node.fMem)) $ \node ->
  forAll (arbitrary `suchThat`
          (\ x ->  (Instance.dsk x  < Node.fDsk node) &&
                   Instance.instanceOffline x)) $ \inst ->
  case Node.addPri node inst of
    Types.OpGood _ -> True
    _ -> False

prop_Node_addSecOffline pdx =
  forAll (arbitrary `suchThat` ((> 0) . Node.fMem)) $ \node ->
  forAll (arbitrary `suchThat`
          (\ x ->  (Instance.dsk x  < Node.fDsk node) &&
                   Instance.instanceOffline x)) $ \inst ->
  case Node.addSec node inst pdx of
    Types.OpGood _ -> True
    _ -> False

-- | Checks for memory reservation changes.
prop_Node_rMem inst =
  not (Instance.instanceOffline inst) ==>
  forAll (arbitrary `suchThat` ((> Types.unitMem) . Node.fMem)) $ \node ->
  -- ab = auto_balance, nb = non-auto_balance
  -- we use -1 as the primary node of the instance
  let inst' = inst { Instance.pNode = -1, Instance.autoBalance = True }
      inst_ab = setInstanceSmallerThanNode node inst'
      inst_nb = inst_ab { Instance.autoBalance = False }
      -- now we have the two instances, identical except the
      -- autoBalance attribute
      orig_rmem = Node.rMem node
      inst_idx = Instance.idx inst_ab
      node_add_ab = Node.addSec node inst_ab (-1)
      node_add_nb = Node.addSec node inst_nb (-1)
      node_del_ab = liftM (`Node.removeSec` inst_ab) node_add_ab
      node_del_nb = liftM (`Node.removeSec` inst_nb) node_add_nb
  in case (node_add_ab, node_add_nb, node_del_ab, node_del_nb) of
       (Types.OpGood a_ab, Types.OpGood a_nb,
        Types.OpGood d_ab, Types.OpGood d_nb) ->
         printTestCase "Consistency checks failed" $
           Node.rMem a_ab >  orig_rmem &&
           Node.rMem a_ab - orig_rmem == Instance.mem inst_ab &&
           Node.rMem a_nb == orig_rmem &&
           Node.rMem d_ab == orig_rmem &&
           Node.rMem d_nb == orig_rmem &&
           -- this is not related to rMem, but as good a place to
           -- test as any
           inst_idx `elem` Node.sList a_ab &&
           inst_idx `notElem` Node.sList d_ab
       x -> printTestCase ("Failed to add/remove instances: " ++ show x) False

-- | Check mdsk setting.
prop_Node_setMdsk node mx =
  Node.loDsk node' >= 0 &&
  fromIntegral (Node.loDsk node') <= Node.tDsk node &&
  Node.availDisk node' >= 0 &&
  Node.availDisk node' <= Node.fDsk node' &&
  fromIntegral (Node.availDisk node') <= Node.tDsk node' &&
  Node.mDsk node' == mx'
    where _types = (node::Node.Node, mx::SmallRatio)
          node' = Node.setMdsk node mx'
          SmallRatio mx' = mx

-- Check tag maps
prop_Node_tagMaps_idempotent tags =
  Node.delTags (Node.addTags m tags) tags ==? m
    where m = Data.Map.empty

prop_Node_tagMaps_reject tags =
  not (null tags) ==>
  all (\t -> Node.rejectAddTags m [t]) tags
    where m = Node.addTags Data.Map.empty tags

prop_Node_showField node =
  forAll (elements Node.defaultFields) $ \ field ->
  fst (Node.showHeader field) /= Types.unknownField &&
  Node.showField node field /= Types.unknownField

prop_Node_computeGroups nodes =
  let ng = Node.computeGroups nodes
      onlyuuid = map fst ng
  in length nodes == sum (map (length . snd) ng) &&
     all (\(guuid, ns) -> all ((== guuid) . Node.group) ns) ng &&
     length (nub onlyuuid) == length onlyuuid &&
     (null nodes || not (null ng))

testSuite "Node"
            [ 'prop_Node_setAlias
            , 'prop_Node_setOffline
            , 'prop_Node_setMcpu
            , 'prop_Node_setXmem
            , 'prop_Node_addPriFM
            , 'prop_Node_addPriFD
            , 'prop_Node_addPriFC
            , 'prop_Node_addSec
            , 'prop_Node_addPriOffline
            , 'prop_Node_addSecOffline
            , 'prop_Node_rMem
            , 'prop_Node_setMdsk
            , 'prop_Node_tagMaps_idempotent
            , 'prop_Node_tagMaps_reject
            , 'prop_Node_showField
            , 'prop_Node_computeGroups
            ]

-- ** Cluster tests

-- | Check that the cluster score is close to zero for a homogeneous
-- cluster.
prop_Score_Zero node =
  forAll (choose (1, 1024)) $ \count ->
    (not (Node.offline node) && not (Node.failN1 node) && (count > 0) &&
     (Node.tDsk node > 0) && (Node.tMem node > 0)) ==>
  let fn = Node.buildPeers node Container.empty
      nlst = replicate count fn
      score = Cluster.compCVNodes nlst
  -- we can't say == 0 here as the floating point errors accumulate;
  -- this should be much lower than the default score in CLI.hs
  in score <= 1e-12

-- | Check that cluster stats are sane.
prop_CStats_sane node =
  forAll (choose (1, 1024)) $ \count ->
    (not (Node.offline node) && not (Node.failN1 node) &&
     (Node.availDisk node > 0) && (Node.availMem node > 0)) ==>
  let fn = Node.buildPeers node Container.empty
      nlst = zip [1..] $ replicate count fn::[(Types.Ndx, Node.Node)]
      nl = Container.fromList nlst
      cstats = Cluster.totalResources nl
  in Cluster.csAdsk cstats >= 0 &&
     Cluster.csAdsk cstats <= Cluster.csFdsk cstats

-- | Check that one instance is allocated correctly, without
-- rebalances needed.
prop_ClusterAlloc_sane node inst =
  forAll (choose (5, 20)) $ \count ->
  not (Node.offline node)
        && not (Node.failN1 node)
        && Node.availDisk node > 0
        && Node.availMem node > 0
        ==>
  let (nl, il, inst') = makeSmallEmptyCluster node count inst
  in case Cluster.genAllocNodes defGroupList nl 2 True >>=
     Cluster.tryAlloc nl il inst' of
       Types.Bad _ -> False
       Types.Ok as ->
         case Cluster.asSolution as of
           Nothing -> False
           Just (xnl, xi, _, cv) ->
             let il' = Container.add (Instance.idx xi) xi il
                 tbl = Cluster.Table xnl il' cv []
             in not (canBalance tbl True True False)

-- | Checks that on a 2-5 node cluster, we can allocate a random
-- instance spec via tiered allocation (whatever the original instance
-- spec), on either one or two nodes.
prop_ClusterCanTieredAlloc node inst =
  forAll (choose (2, 5)) $ \count ->
  forAll (choose (1, 2)) $ \rqnodes ->
  not (Node.offline node)
        && not (Node.failN1 node)
        && isNodeBig node 4
        ==>
  let nl = makeSmallCluster node count
      il = Container.empty
      allocnodes = Cluster.genAllocNodes defGroupList nl rqnodes True
  in case allocnodes >>= \allocnodes' ->
    Cluster.tieredAlloc nl il (Just 1) inst allocnodes' [] [] of
       Types.Bad _ -> False
       Types.Ok (_, _, il', ixes, cstats) -> not (null ixes) &&
                                             IntMap.size il' == length ixes &&
                                             length ixes == length cstats

-- | Checks that on a 4-8 node cluster, once we allocate an instance,
-- we can also evacuate it.
prop_ClusterAllocEvac node inst =
  forAll (choose (4, 8)) $ \count ->
  not (Node.offline node)
        && not (Node.failN1 node)
        && isNodeBig node 4
        ==>
  let (nl, il, inst') = makeSmallEmptyCluster node count inst
  in case Cluster.genAllocNodes defGroupList nl 2 True >>=
     Cluster.tryAlloc nl il inst' of
       Types.Bad _ -> False
       Types.Ok as ->
         case Cluster.asSolution as of
           Nothing -> False
           Just (xnl, xi, _, _) ->
             let sdx = Instance.sNode xi
                 il' = Container.add (Instance.idx xi) xi il
             in case IAlloc.processRelocate defGroupList xnl il'
                  (Instance.idx xi) 1 [sdx] of
                  Types.Ok _ -> True
                  _ -> False

-- | Check that allocating multiple instances on a cluster, then
-- adding an empty node, results in a valid rebalance.
prop_ClusterAllocBalance =
  forAll (genNode (Just 5) (Just 128)) $ \node ->
  forAll (choose (3, 5)) $ \count ->
  not (Node.offline node) && not (Node.failN1 node) ==>
  let nl = makeSmallCluster node count
      (hnode, nl') = IntMap.deleteFindMax nl
      il = Container.empty
      allocnodes = Cluster.genAllocNodes defGroupList nl' 2 True
      i_templ = createInstance Types.unitMem Types.unitDsk Types.unitCpu
  in case allocnodes >>= \allocnodes' ->
    Cluster.iterateAlloc nl' il (Just 5) i_templ allocnodes' [] [] of
       Types.Bad _ -> False
       Types.Ok (_, xnl, il', _, _) ->
         let ynl = Container.add (Node.idx hnode) hnode xnl
             cv = Cluster.compCV ynl
             tbl = Cluster.Table ynl il' cv []
         in canBalance tbl True True False

-- | Checks consistency.
prop_ClusterCheckConsistency node inst =
  let nl = makeSmallCluster node 3
      [node1, node2, node3] = Container.elems nl
      node3' = node3 { Node.group = 1 }
      nl' = Container.add (Node.idx node3') node3' nl
      inst1 = Instance.setBoth inst (Node.idx node1) (Node.idx node2)
      inst2 = Instance.setBoth inst (Node.idx node1) Node.noSecondary
      inst3 = Instance.setBoth inst (Node.idx node1) (Node.idx node3)
      ccheck = Cluster.findSplitInstances nl' . Container.fromList
  in null (ccheck [(0, inst1)]) &&
     null (ccheck [(0, inst2)]) &&
     (not . null $ ccheck [(0, inst3)])

-- | For now, we only test that we don't lose instances during the split.
prop_ClusterSplitCluster node inst =
  forAll (choose (0, 100)) $ \icnt ->
  let nl = makeSmallCluster node 2
      (nl', il') = foldl (\(ns, is) _ -> assignInstance ns is inst 0 1)
                   (nl, Container.empty) [1..icnt]
      gni = Cluster.splitCluster nl' il'
  in sum (map (Container.size . snd . snd) gni) == icnt &&
     all (\(guuid, (nl'', _)) -> all ((== guuid) . Node.group)
                                 (Container.elems nl'')) gni

testSuite "Cluster"
            [ 'prop_Score_Zero
            , 'prop_CStats_sane
            , 'prop_ClusterAlloc_sane
            , 'prop_ClusterCanTieredAlloc
            , 'prop_ClusterAllocEvac
            , 'prop_ClusterAllocBalance
            , 'prop_ClusterCheckConsistency
            , 'prop_ClusterSplitCluster
            ]

-- ** OpCodes tests

-- | Check that opcode serialization is idempotent.
prop_OpCodes_serialization op =
  case J.readJSON (J.showJSON op) of
    J.Error e -> printTestCase ("Cannot deserialise: " ++ e) False
    J.Ok op' -> op ==? op'
  where _types = op::OpCodes.OpCode

testSuite "OpCodes"
            [ 'prop_OpCodes_serialization ]

-- ** Jobs tests

-- | Check that (queued) job\/opcode status serialization is idempotent.
prop_OpStatus_serialization os =
  case J.readJSON (J.showJSON os) of
    J.Error e -> printTestCase ("Cannot deserialise: " ++ e) False
    J.Ok os' -> os ==? os'
  where _types = os::Jobs.OpStatus

prop_JobStatus_serialization js =
  case J.readJSON (J.showJSON js) of
    J.Error e -> printTestCase ("Cannot deserialise: " ++ e) False
    J.Ok js' -> js ==? js'
  where _types = js::Jobs.JobStatus

testSuite "Jobs"
            [ 'prop_OpStatus_serialization
            , 'prop_JobStatus_serialization
            ]

-- ** Loader tests

prop_Loader_lookupNode ktn inst node =
  Loader.lookupNode nl inst node ==? Data.Map.lookup node nl
    where nl = Data.Map.fromList ktn

prop_Loader_lookupInstance kti inst =
  Loader.lookupInstance il inst ==? Data.Map.lookup inst il
    where il = Data.Map.fromList kti

prop_Loader_assignIndices nodes =
  Data.Map.size nassoc == length nodes &&
  Container.size kt == length nodes &&
  (if not (null nodes)
   then maximum (IntMap.keys kt) == length nodes - 1
   else True)
    where (nassoc, kt) =
            Loader.assignIndices (map (\n -> (Node.name n, n)) nodes)

-- | Checks that the number of primary instances recorded on the nodes
-- is zero.
prop_Loader_mergeData ns =
  let na = Container.fromList $ map (\n -> (Node.idx n, n)) ns
  in case Loader.mergeData [] [] [] []
         (Loader.emptyCluster {Loader.cdNodes = na}) of
    Types.Bad _ -> False
    Types.Ok (Loader.ClusterData _ nl il _) ->
      let nodes = Container.elems nl
          instances = Container.elems il
      in (sum . map (length . Node.pList)) nodes == 0 &&
         null instances

-- | Check that compareNameComponent on equal strings works.
prop_Loader_compareNameComponent_equal :: String -> Bool
prop_Loader_compareNameComponent_equal s =
  Loader.compareNameComponent s s ==
    Loader.LookupResult Loader.ExactMatch s

-- | Check that compareNameComponent on prefix strings works.
prop_Loader_compareNameComponent_prefix :: NonEmptyList Char -> String -> Bool
prop_Loader_compareNameComponent_prefix (NonEmpty s1) s2 =
  Loader.compareNameComponent (s1 ++ "." ++ s2) s1 ==
    Loader.LookupResult Loader.PartialMatch s1

testSuite "Loader"
            [ 'prop_Loader_lookupNode
            , 'prop_Loader_lookupInstance
            , 'prop_Loader_assignIndices
            , 'prop_Loader_mergeData
            , 'prop_Loader_compareNameComponent_equal
            , 'prop_Loader_compareNameComponent_prefix
            ]

-- ** Types tests

prop_Types_AllocPolicy_serialisation apol =
  case J.readJSON (J.showJSON apol) of
    J.Ok p -> printTestCase ("invalid deserialisation " ++ show p) $
              p == apol
    J.Error s -> printTestCase ("failed to deserialise: " ++ s) False
      where _types = apol::Types.AllocPolicy

prop_Types_DiskTemplate_serialisation dt =
  case J.readJSON (J.showJSON dt) of
    J.Ok p -> printTestCase ("invalid deserialisation " ++ show p) $
              p == dt
    J.Error s -> printTestCase ("failed to deserialise: " ++ s)
                 False
      where _types = dt::Types.DiskTemplate

prop_Types_opToResult op =
  case op of
    Types.OpFail _ -> Types.isBad r
    Types.OpGood v -> case r of
                        Types.Bad _ -> False
                        Types.Ok v' -> v == v'
  where r = Types.opToResult op
        _types = op::Types.OpResult Int

prop_Types_eitherToResult ei =
  case ei of
    Left _ -> Types.isBad r
    Right v -> case r of
                 Types.Bad _ -> False
                 Types.Ok v' -> v == v'
    where r = Types.eitherToResult ei
          _types = ei::Either String Int

testSuite "Types"
            [ 'prop_Types_AllocPolicy_serialisation
            , 'prop_Types_DiskTemplate_serialisation
            , 'prop_Types_opToResult
            , 'prop_Types_eitherToResult
            ]

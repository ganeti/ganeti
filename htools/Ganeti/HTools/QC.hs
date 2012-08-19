{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans -fno-warn-unused-imports #-}

-- FIXME: should remove the no-warn-unused-imports option, once we get
-- around to testing function from all modules; until then, we keep
-- the (unused) imports here to generate correct coverage (0 for
-- modules we don't use)

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

module Ganeti.HTools.QC
  ( testUtils
  , testPeerMap
  , testContainer
  , testInstance
  , testNode
  , testText
  , testSimu
  , testOpCodes
  , testJobs
  , testCluster
  , testLoader
  , testTypes
  , testCLI
  , testJSON
  , testLuxi
  , testSsconf
  , testRpc
  , testQlang
  ) where

import Test.QuickCheck
import Test.QuickCheck.Monadic (assert, monadicIO, run, stop)
import Text.Printf (printf)
import Data.List (intercalate, nub, isPrefixOf)
import Data.Maybe
import qualified Data.Set as Set
import Control.Monad
import Control.Applicative
import qualified System.Console.GetOpt as GetOpt
import qualified Text.JSON as J
import qualified Data.Map
import qualified Data.IntMap as IntMap
import Control.Concurrent (forkIO)
import Control.Exception (bracket, catchJust)
import System.Directory (getTemporaryDirectory, removeFile)
import System.IO (hClose, openTempFile)
import System.IO.Error (isEOFErrorType, ioeGetErrorType)

import qualified Ganeti.Confd as Confd
import qualified Ganeti.Config as Config
import qualified Ganeti.Daemon as Daemon
import qualified Ganeti.Hash as Hash
import qualified Ganeti.BasicTypes as BasicTypes
import qualified Ganeti.Jobs as Jobs
import qualified Ganeti.Logging as Logging
import qualified Ganeti.Luxi as Luxi
import qualified Ganeti.Objects as Objects
import qualified Ganeti.OpCodes as OpCodes
import qualified Ganeti.Qlang as Qlang
import qualified Ganeti.Rpc as Rpc
import qualified Ganeti.Runtime as Runtime
import qualified Ganeti.Ssconf as Ssconf
import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.ExtLoader
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.IAlloc as IAlloc
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.JSON as JSON
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Luxi as HTools.Luxi
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.PeerMap as PeerMap
import qualified Ganeti.HTools.Rapi
import qualified Ganeti.HTools.Simu as Simu
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Utils as Utils
import qualified Ganeti.HTools.Version
import qualified Ganeti.Constants as C

import qualified Ganeti.HTools.Program as Program
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

-- | Max vcpu ratio (random value).
maxVcpuRatio :: Double
maxVcpuRatio = 1024.0

-- | Max spindle ratio (random value).
maxSpindleRatio :: Double
maxSpindleRatio = 1024.0

-- | Max nodes, used just to limit arbitrary instances for smaller
-- opcode definitions (e.g. list of nodes in OpTestDelay).
maxNodes :: Int
maxNodes = 32

-- | Max opcodes or jobs in a submit job and submit many jobs.
maxOpCodes :: Int
maxOpCodes = 16

-- | All disk templates (used later)
allDiskTemplates :: [Types.DiskTemplate]
allDiskTemplates = [minBound..maxBound]

-- | Null iPolicy, and by null we mean very liberal.
nullIPolicy :: Types.IPolicy
nullIPolicy = Types.IPolicy
  { Types.iPolicyMinSpec = Types.ISpec { Types.iSpecMemorySize = 0
                                       , Types.iSpecCpuCount   = 0
                                       , Types.iSpecDiskSize   = 0
                                       , Types.iSpecDiskCount  = 0
                                       , Types.iSpecNicCount   = 0
                                       , Types.iSpecSpindleUse = 0
                                       }
  , Types.iPolicyMaxSpec = Types.ISpec { Types.iSpecMemorySize = maxBound
                                       , Types.iSpecCpuCount   = maxBound
                                       , Types.iSpecDiskSize   = maxBound
                                       , Types.iSpecDiskCount  = C.maxDisks
                                       , Types.iSpecNicCount   = C.maxNics
                                       , Types.iSpecSpindleUse = maxBound
                                       }
  , Types.iPolicyStdSpec = Types.ISpec { Types.iSpecMemorySize = Types.unitMem
                                       , Types.iSpecCpuCount   = Types.unitCpu
                                       , Types.iSpecDiskSize   = Types.unitDsk
                                       , Types.iSpecDiskCount  = 1
                                       , Types.iSpecNicCount   = 1
                                       , Types.iSpecSpindleUse = 1
                                       }
  , Types.iPolicyDiskTemplates = [minBound..maxBound]
  , Types.iPolicyVcpuRatio = maxVcpuRatio -- somewhat random value, high
                                          -- enough to not impact us
  , Types.iPolicySpindleRatio = maxSpindleRatio
  }


defGroup :: Group.Group
defGroup = flip Group.setIdx 0 $
             Group.create "default" Types.defaultGroupID Types.AllocPreferred
                  nullIPolicy

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

-- | Show a message and fail the test.
failTest :: String -> Property
failTest msg = printTestCase msg False

-- | Update an instance to be smaller than a node.
setInstanceSmallerThanNode :: Node.Node
                           -> Instance.Instance -> Instance.Instance
setInstanceSmallerThanNode node inst =
  inst { Instance.mem = Node.availMem node `div` 2
       , Instance.dsk = Node.availDisk node `div` 2
       , Instance.vcpus = Node.availCpu node `div` 2
       }

-- | Create an instance given its spec.
createInstance :: Int -> Int -> Int -> Instance.Instance
createInstance mem dsk vcpus =
  Instance.create "inst-unnamed" mem dsk vcpus Types.Running [] True (-1) (-1)
    Types.DTDrbd8 1

-- | Create a small cluster by repeating a node spec.
makeSmallCluster :: Node.Node -> Int -> Node.List
makeSmallCluster node count =
  let origname = Node.name node
      origalias = Node.alias node
      nodes = map (\idx -> node { Node.name = origname ++ "-" ++ show idx
                                , Node.alias = origalias ++ "-" ++ show idx })
              [1..count]
      fn = flip Node.buildPeers Container.empty
      namelst = map (\n -> (Node.name n, fn n)) nodes
      (_, nlst) = Loader.assignIndices namelst
  in nlst

-- | Make a small cluster, both nodes and instances.
makeSmallEmptyCluster :: Node.Node -> Int -> Instance.Instance
                      -> (Node.List, Instance.List, Instance.Instance)
makeSmallEmptyCluster node count inst =
  (makeSmallCluster node count, Container.empty,
   setInstanceSmallerThanNode node inst)

-- | Checks if a node is "big" enough.
isNodeBig :: Int -> Node.Node -> Bool
isNodeBig size node = Node.availDisk node > size * Types.unitDsk
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

-- | Generates a list of a given size with non-duplicate elements.
genUniquesList :: (Eq a, Arbitrary a) => Int -> Gen [a]
genUniquesList cnt =
  foldM (\lst _ -> do
           newelem <- arbitrary `suchThat` (`notElem` lst)
           return (newelem:lst)) [] [1..cnt]

-- | Checks if an instance is mirrored.
isMirrored :: Instance.Instance -> Bool
isMirrored = (/= Types.MirrorNone) . Instance.mirrorType

-- | Returns the possible change node types for a disk template.
evacModeOptions :: Types.MirrorType -> [Types.EvacMode]
evacModeOptions Types.MirrorNone     = []
evacModeOptions Types.MirrorInternal = [minBound..maxBound] -- DRBD can do all
evacModeOptions Types.MirrorExternal = [Types.ChangePrimary, Types.ChangeAll]

-- * Arbitrary instances

-- | Defines a DNS name.
newtype DNSChar = DNSChar { dnsGetChar::Char }

instance Arbitrary DNSChar where
  arbitrary = do
    x <- elements (['a'..'z'] ++ ['0'..'9'] ++ "_-")
    return (DNSChar x)

instance Show DNSChar where
  show = show . dnsGetChar

-- | Generates a single name component.
getName :: Gen String
getName = do
  n <- choose (1, 64)
  dn <- vector n
  return (map dnsGetChar dn)

-- | Generates an entire FQDN.
getFQDN :: Gen String
getFQDN = do
  ncomps <- choose (1, 4)
  names <- vectorOf ncomps getName
  return $ intercalate "." names

-- | Combinator that generates a 'Maybe' using a sub-combinator.
getMaybe :: Gen a -> Gen (Maybe a)
getMaybe subgen = do
  bool <- arbitrary
  if bool
    then Just <$> subgen
    else return Nothing

-- | Generates a fields list. This uses the same character set as a
-- DNS name (just for simplicity).
getFields :: Gen [String]
getFields = do
  n <- choose (1, 32)
  vectorOf n getName

-- | Defines a tag type.
newtype TagChar = TagChar { tagGetChar :: Char }

-- | All valid tag chars. This doesn't need to match _exactly_
-- Ganeti's own tag regex, just enough for it to be close.
tagChar :: [Char]
tagChar = ['a'..'z'] ++ ['A'..'Z'] ++ ['0'..'9'] ++ ".+*/:@-"

instance Arbitrary TagChar where
  arbitrary = do
    c <- elements tagChar
    return (TagChar c)

-- | Generates a tag
genTag :: Gen [TagChar]
genTag = do
  -- the correct value would be C.maxTagLen, but that's way too
  -- verbose in unittests, and at the moment I don't see any possible
  -- bugs with longer tags and the way we use tags in htools
  n <- choose (1, 10)
  vector n

-- | Generates a list of tags (correctly upper bounded).
genTags :: Gen [String]
genTags = do
  -- the correct value would be C.maxTagsPerObj, but per the comment
  -- in genTag, we don't use tags enough in htools to warrant testing
  -- such big values
  n <- choose (0, 10::Int)
  tags <- mapM (const genTag) [1..n]
  return $ map (map tagGetChar) tags

instance Arbitrary Types.InstanceStatus where
    arbitrary = elements [minBound..maxBound]

-- | Generates a random instance with maximum disk/mem/cpu values.
genInstanceSmallerThan :: Int -> Int -> Int -> Gen Instance.Instance
genInstanceSmallerThan lim_mem lim_dsk lim_cpu = do
  name <- getFQDN
  mem <- choose (0, lim_mem)
  dsk <- choose (0, lim_dsk)
  run_st <- arbitrary
  pn <- arbitrary
  sn <- arbitrary
  vcpus <- choose (0, lim_cpu)
  dt <- arbitrary
  return $ Instance.create name mem dsk vcpus run_st [] True pn sn dt 1

-- | Generates an instance smaller than a node.
genInstanceSmallerThanNode :: Node.Node -> Gen Instance.Instance
genInstanceSmallerThanNode node =
  genInstanceSmallerThan (Node.availMem node `div` 2)
                         (Node.availDisk node `div` 2)
                         (Node.availCpu node `div` 2)

-- let's generate a random instance
instance Arbitrary Instance.Instance where
  arbitrary = genInstanceSmallerThan maxMem maxDsk maxCpu

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
          (fromIntegral dsk_t) dsk_f (fromIntegral cpu_t) offl 1 0
      n' = Node.setPolicy nullIPolicy n
  return $ Node.buildPeers n' Container.empty

-- | Helper function to generate a sane node.
genOnlineNode :: Gen Node.Node
genOnlineNode = do
  arbitrary `suchThat` (\n -> not (Node.offline n) &&
                              not (Node.failN1 n) &&
                              Node.availDisk n > 0 &&
                              Node.availMem n > 0 &&
                              Node.availCpu n > 0)

-- and a random node
instance Arbitrary Node.Node where
  arbitrary = genNode Nothing Nothing

-- replace disks
instance Arbitrary OpCodes.ReplaceDisksMode where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary OpCodes.OpCode where
  arbitrary = do
    op_id <- elements OpCodes.allOpIDs
    case op_id of
      "OP_TEST_DELAY" ->
        OpCodes.OpTestDelay <$> arbitrary <*> arbitrary
                 <*> resize maxNodes (listOf getFQDN)
      "OP_INSTANCE_REPLACE_DISKS" ->
        OpCodes.OpInstanceReplaceDisks <$> getFQDN <*> getMaybe getFQDN <*>
          arbitrary <*> resize C.maxDisks arbitrary <*> getMaybe getName
      "OP_INSTANCE_FAILOVER" ->
        OpCodes.OpInstanceFailover <$> getFQDN <*> arbitrary <*>
          getMaybe getFQDN
      "OP_INSTANCE_MIGRATE" ->
        OpCodes.OpInstanceMigrate <$> getFQDN <*> arbitrary <*>
          arbitrary <*> arbitrary <*> getMaybe getFQDN
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

instance Arbitrary Types.EvacMode where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary a => Arbitrary (Types.OpResult a) where
  arbitrary = arbitrary >>= \c ->
              if c
                then Types.OpGood <$> arbitrary
                else Types.OpFail <$> arbitrary

instance Arbitrary Types.ISpec where
  arbitrary = do
    mem_s <- arbitrary::Gen (NonNegative Int)
    dsk_c <- arbitrary::Gen (NonNegative Int)
    dsk_s <- arbitrary::Gen (NonNegative Int)
    cpu_c <- arbitrary::Gen (NonNegative Int)
    nic_c <- arbitrary::Gen (NonNegative Int)
    su    <- arbitrary::Gen (NonNegative Int)
    return Types.ISpec { Types.iSpecMemorySize = fromIntegral mem_s
                       , Types.iSpecCpuCount   = fromIntegral cpu_c
                       , Types.iSpecDiskSize   = fromIntegral dsk_s
                       , Types.iSpecDiskCount  = fromIntegral dsk_c
                       , Types.iSpecNicCount   = fromIntegral nic_c
                       , Types.iSpecSpindleUse = fromIntegral su
                       }

-- | Generates an ispec bigger than the given one.
genBiggerISpec :: Types.ISpec -> Gen Types.ISpec
genBiggerISpec imin = do
  mem_s <- choose (Types.iSpecMemorySize imin, maxBound)
  dsk_c <- choose (Types.iSpecDiskCount imin, maxBound)
  dsk_s <- choose (Types.iSpecDiskSize imin, maxBound)
  cpu_c <- choose (Types.iSpecCpuCount imin, maxBound)
  nic_c <- choose (Types.iSpecNicCount imin, maxBound)
  su    <- choose (Types.iSpecSpindleUse imin, maxBound)
  return Types.ISpec { Types.iSpecMemorySize = fromIntegral mem_s
                     , Types.iSpecCpuCount   = fromIntegral cpu_c
                     , Types.iSpecDiskSize   = fromIntegral dsk_s
                     , Types.iSpecDiskCount  = fromIntegral dsk_c
                     , Types.iSpecNicCount   = fromIntegral nic_c
                     , Types.iSpecSpindleUse = fromIntegral su
                     }

instance Arbitrary Types.IPolicy where
  arbitrary = do
    imin <- arbitrary
    istd <- genBiggerISpec imin
    imax <- genBiggerISpec istd
    num_tmpl <- choose (0, length allDiskTemplates)
    dts  <- genUniquesList num_tmpl
    vcpu_ratio <- choose (1.0, maxVcpuRatio)
    spindle_ratio <- choose (1.0, maxSpindleRatio)
    return Types.IPolicy { Types.iPolicyMinSpec = imin
                         , Types.iPolicyStdSpec = istd
                         , Types.iPolicyMaxSpec = imax
                         , Types.iPolicyDiskTemplates = dts
                         , Types.iPolicyVcpuRatio = vcpu_ratio
                         , Types.iPolicySpindleRatio = spindle_ratio
                         }

instance Arbitrary Objects.Hypervisor where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Objects.PartialNDParams where
  arbitrary = Objects.PartialNDParams <$> arbitrary <*> arbitrary

instance Arbitrary Objects.Node where
  arbitrary = Objects.Node <$> getFQDN <*> getFQDN <*> getFQDN
              <*> arbitrary <*> arbitrary <*> arbitrary <*> getFQDN
              <*> arbitrary <*> arbitrary <*> arbitrary <*> arbitrary
              <*> arbitrary <*> arbitrary <*> getFQDN <*> arbitrary
              <*> (Set.fromList <$> genTags)

instance Arbitrary Rpc.RpcCallAllInstancesInfo where
  arbitrary = Rpc.RpcCallAllInstancesInfo <$> arbitrary

instance Arbitrary Rpc.RpcCallInstanceList where
  arbitrary = Rpc.RpcCallInstanceList <$> arbitrary

instance Arbitrary Rpc.RpcCallNodeInfo where
  arbitrary = Rpc.RpcCallNodeInfo <$> arbitrary <*> arbitrary

-- | Custom 'Qlang.Filter' generator (top-level), which enforces a
-- (sane) limit on the depth of the generated filters.
genFilter :: Gen Qlang.Filter
genFilter = choose (0, 10) >>= genFilter'

-- | Custom generator for filters that correctly halves the state of
-- the generators at each recursive step, per the QuickCheck
-- documentation, in order not to run out of memory.
genFilter' :: Int -> Gen Qlang.Filter
genFilter' 0 =
  oneof [ return Qlang.EmptyFilter
        , Qlang.TrueFilter     <$> getName
        , Qlang.EQFilter       <$> getName <*> value
        , Qlang.LTFilter       <$> getName <*> value
        , Qlang.GTFilter       <$> getName <*> value
        , Qlang.LEFilter       <$> getName <*> value
        , Qlang.GEFilter       <$> getName <*> value
        , Qlang.RegexpFilter   <$> getName <*> getName
        , Qlang.ContainsFilter <$> getName <*> value
        ]
    where value = oneof [ Qlang.QuotedString <$> getName
                        , Qlang.NumericValue <$> arbitrary
                        ]
genFilter' n = do
  oneof [ Qlang.AndFilter  <$> vectorOf n'' (genFilter' n')
        , Qlang.OrFilter   <$> vectorOf n'' (genFilter' n')
        , Qlang.NotFilter  <$> genFilter' n'
        ]
  where n' = n `div` 2 -- sub-filter generator size
        n'' = max n' 2 -- but we don't want empty or 1-element lists,
                       -- so use this for and/or filter list length

instance Arbitrary Qlang.ItemType where
  arbitrary = elements [minBound..maxBound]

-- * Actual tests

-- ** Utils tests

-- | Helper to generate a small string that doesn't contain commas.
genNonCommaString :: Gen [Char]
genNonCommaString = do
  size <- choose (0, 20) -- arbitrary max size
  vectorOf size (arbitrary `suchThat` ((/=) ','))

-- | If the list is not just an empty element, and if the elements do
-- not contain commas, then join+split should be idempotent.
prop_Utils_commaJoinSplit :: Property
prop_Utils_commaJoinSplit =
  forAll (choose (0, 20)) $ \llen ->
  forAll (vectorOf llen genNonCommaString `suchThat` ((/=) [""])) $ \lst ->
  Utils.sepSplit ',' (Utils.commaJoin lst) ==? lst

-- | Split and join should always be idempotent.
prop_Utils_commaSplitJoin :: [Char] -> Property
prop_Utils_commaSplitJoin s =
  Utils.commaJoin (Utils.sepSplit ',' s) ==? s

-- | fromObjWithDefault, we test using the Maybe monad and an integer
-- value.
prop_Utils_fromObjWithDefault :: Integer -> String -> Bool
prop_Utils_fromObjWithDefault def_value random_key =
  -- a missing key will be returned with the default
  JSON.fromObjWithDefault [] random_key def_value == Just def_value &&
  -- a found key will be returned as is, not with default
  JSON.fromObjWithDefault [(random_key, J.showJSON def_value)]
       random_key (def_value+1) == Just def_value

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
          flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2

-- | Test basic select functionality with undefined default
prop_Utils_select_undefd :: [Int]            -- ^ List of False values
                         -> NonEmptyList Int -- ^ List of True values
                         -> Gen Prop         -- ^ Test result
prop_Utils_select_undefd lst1 (NonEmpty lst2) =
  Utils.select undefined (flist ++ tlist) ==? head lst2
    where flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2

-- | Test basic select functionality with undefined list values
prop_Utils_select_undefv :: [Int]            -- ^ List of False values
                         -> NonEmptyList Int -- ^ List of True values
                         -> Gen Prop         -- ^ Test result
prop_Utils_select_undefv lst1 (NonEmpty lst2) =
  Utils.select undefined cndlist ==? head lst2
    where flist = zip (repeat False) lst1
          tlist = zip (repeat True)  lst2
          cndlist = flist ++ tlist ++ [undefined]

prop_Utils_parseUnit :: NonNegative Int -> Property
prop_Utils_parseUnit (NonNegative n) =
  Utils.parseUnit (show n) ==? Types.Ok n .&&.
  Utils.parseUnit (show n ++ "m") ==? Types.Ok n .&&.
  Utils.parseUnit (show n ++ "M") ==? Types.Ok (truncate n_mb::Int) .&&.
  Utils.parseUnit (show n ++ "g") ==? Types.Ok (n*1024) .&&.
  Utils.parseUnit (show n ++ "G") ==? Types.Ok (truncate n_gb::Int) .&&.
  Utils.parseUnit (show n ++ "t") ==? Types.Ok (n*1048576) .&&.
  Utils.parseUnit (show n ++ "T") ==? Types.Ok (truncate n_tb::Int) .&&.
  printTestCase "Internal error/overflow?"
    (n_mb >=0 && n_gb >= 0 && n_tb >= 0) .&&.
  property (Types.isBad (Utils.parseUnit (show n ++ "x")::Types.Result Int))
  where n_mb = (fromIntegral n::Rational) * 1000 * 1000 / 1024 / 1024
        n_gb = n_mb * 1000
        n_tb = n_gb * 1000

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
prop_PeerMap_addIdempotent :: PeerMap.PeerMap
                           -> PeerMap.Key -> PeerMap.Elem -> Property
prop_PeerMap_addIdempotent pmap key em =
  fn puniq ==? fn (fn puniq)
    where fn = PeerMap.add key em
          puniq = PeerMap.accumArray const pmap

-- | Make sure remove is idempotent.
prop_PeerMap_removeIdempotent :: PeerMap.PeerMap -> PeerMap.Key -> Property
prop_PeerMap_removeIdempotent pmap key =
  fn puniq ==? fn (fn puniq)
    where fn = PeerMap.remove key
          puniq = PeerMap.accumArray const pmap

-- | Make sure a missing item returns 0.
prop_PeerMap_findMissing :: PeerMap.PeerMap -> PeerMap.Key -> Property
prop_PeerMap_findMissing pmap key =
  PeerMap.find key (PeerMap.remove key puniq) ==? 0
    where puniq = PeerMap.accumArray const pmap

-- | Make sure an added item is found.
prop_PeerMap_addFind :: PeerMap.PeerMap
                     -> PeerMap.Key -> PeerMap.Elem -> Property
prop_PeerMap_addFind pmap key em =
  PeerMap.find key (PeerMap.add key em puniq) ==? em
    where puniq = PeerMap.accumArray const pmap

-- | Manual check that maxElem returns the maximum indeed, or 0 for null.
prop_PeerMap_maxElem :: PeerMap.PeerMap -> Property
prop_PeerMap_maxElem pmap =
  PeerMap.maxElem puniq ==? if null puniq then 0
                              else (maximum . snd . unzip) puniq
    where puniq = PeerMap.accumArray const pmap

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
prop_Container_addTwo :: [Container.Key] -> Int -> Int -> Bool
prop_Container_addTwo cdata i1 i2 =
  fn i1 i2 cont == fn i2 i1 cont &&
  fn i1 i2 cont == fn i1 i2 (fn i1 i2 cont)
    where cont = foldl (\c x -> Container.add x x c) Container.empty cdata
          fn x1 x2 = Container.addTwo x1 x1 x2 x2

prop_Container_nameOf :: Node.Node -> Property
prop_Container_nameOf node =
  let nl = makeSmallCluster node 1
      fnode = head (Container.elems nl)
  in Container.nameOf nl (Node.idx fnode) ==? Node.name fnode

-- | We test that in a cluster, given a random node, we can find it by
-- its name and alias, as long as all names and aliases are unique,
-- and that we fail to find a non-existing name.
prop_Container_findByName :: Property
prop_Container_findByName =
  forAll (genNode (Just 1) Nothing) $ \node ->
  forAll (choose (1, 20)) $ \ cnt ->
  forAll (choose (0, cnt - 1)) $ \ fidx ->
  forAll (genUniquesList (cnt * 2)) $ \ allnames ->
  forAll (arbitrary `suchThat` (`notElem` allnames)) $ \ othername ->
  let names = zip (take cnt allnames) (drop cnt allnames)
      nl = makeSmallCluster node cnt
      nodes = Container.elems nl
      nodes' = map (\((name, alias), nn) -> (Node.idx nn,
                                             nn { Node.name = name,
                                                  Node.alias = alias }))
               $ zip names nodes
      nl' = Container.fromList nodes'
      target = snd (nodes' !! fidx)
  in Container.findByName nl' (Node.name target) ==? Just target .&&.
     Container.findByName nl' (Node.alias target) ==? Just target .&&.
     printTestCase "Found non-existing name"
       (isNothing (Container.findByName nl' othername))

testSuite "Container"
            [ 'prop_Container_addTwo
            , 'prop_Container_nameOf
            , 'prop_Container_findByName
            ]

-- ** Instance tests

-- Simple instance tests, we only have setter/getters

prop_Instance_creat :: Instance.Instance -> Property
prop_Instance_creat inst =
  Instance.name inst ==? Instance.alias inst

prop_Instance_setIdx :: Instance.Instance -> Types.Idx -> Property
prop_Instance_setIdx inst idx =
  Instance.idx (Instance.setIdx inst idx) ==? idx

prop_Instance_setName :: Instance.Instance -> String -> Bool
prop_Instance_setName inst name =
  Instance.name newinst == name &&
  Instance.alias newinst == name
    where newinst = Instance.setName inst name

prop_Instance_setAlias :: Instance.Instance -> String -> Bool
prop_Instance_setAlias inst name =
  Instance.name newinst == Instance.name inst &&
  Instance.alias newinst == name
    where newinst = Instance.setAlias inst name

prop_Instance_setPri :: Instance.Instance -> Types.Ndx -> Property
prop_Instance_setPri inst pdx =
  Instance.pNode (Instance.setPri inst pdx) ==? pdx

prop_Instance_setSec :: Instance.Instance -> Types.Ndx -> Property
prop_Instance_setSec inst sdx =
  Instance.sNode (Instance.setSec inst sdx) ==? sdx

prop_Instance_setBoth :: Instance.Instance -> Types.Ndx -> Types.Ndx -> Bool
prop_Instance_setBoth inst pdx sdx =
  Instance.pNode si == pdx && Instance.sNode si == sdx
    where si = Instance.setBoth inst pdx sdx

prop_Instance_shrinkMG :: Instance.Instance -> Property
prop_Instance_shrinkMG inst =
  Instance.mem inst >= 2 * Types.unitMem ==>
    case Instance.shrinkByType inst Types.FailMem of
      Types.Ok inst' -> Instance.mem inst' == Instance.mem inst - Types.unitMem
      _ -> False

prop_Instance_shrinkMF :: Instance.Instance -> Property
prop_Instance_shrinkMF inst =
  forAll (choose (0, 2 * Types.unitMem - 1)) $ \mem ->
    let inst' = inst { Instance.mem = mem}
    in Types.isBad $ Instance.shrinkByType inst' Types.FailMem

prop_Instance_shrinkCG :: Instance.Instance -> Property
prop_Instance_shrinkCG inst =
  Instance.vcpus inst >= 2 * Types.unitCpu ==>
    case Instance.shrinkByType inst Types.FailCPU of
      Types.Ok inst' ->
        Instance.vcpus inst' == Instance.vcpus inst - Types.unitCpu
      _ -> False

prop_Instance_shrinkCF :: Instance.Instance -> Property
prop_Instance_shrinkCF inst =
  forAll (choose (0, 2 * Types.unitCpu - 1)) $ \vcpus ->
    let inst' = inst { Instance.vcpus = vcpus }
    in Types.isBad $ Instance.shrinkByType inst' Types.FailCPU

prop_Instance_shrinkDG :: Instance.Instance -> Property
prop_Instance_shrinkDG inst =
  Instance.dsk inst >= 2 * Types.unitDsk ==>
    case Instance.shrinkByType inst Types.FailDisk of
      Types.Ok inst' ->
        Instance.dsk inst' == Instance.dsk inst - Types.unitDsk
      _ -> False

prop_Instance_shrinkDF :: Instance.Instance -> Property
prop_Instance_shrinkDF inst =
  forAll (choose (0, 2 * Types.unitDsk - 1)) $ \dsk ->
    let inst' = inst { Instance.dsk = dsk }
    in Types.isBad $ Instance.shrinkByType inst' Types.FailDisk

prop_Instance_setMovable :: Instance.Instance -> Bool -> Property
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

-- ** Backends

-- *** Text backend tests

-- Instance text loader tests

prop_Text_Load_Instance :: String -> Int -> Int -> Int -> Types.InstanceStatus
                        -> NonEmptyList Char -> [Char]
                        -> NonNegative Int -> NonNegative Int -> Bool
                        -> Types.DiskTemplate -> Int -> Property
prop_Text_Load_Instance name mem dsk vcpus status
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
      nl = Data.Map.fromList ndx
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

prop_Text_Load_InstanceFail :: [(String, Int)] -> [String] -> Property
prop_Text_Load_InstanceFail ktn fields =
  length fields /= 10 && length fields /= 11 ==>
    case Text.loadInst nl fields of
      Types.Ok _ -> failTest "Managed to load instance from invalid data"
      Types.Bad msg -> printTestCase ("Unrecognised error message: " ++ msg) $
                       "Invalid/incomplete instance data: '" `isPrefixOf` msg
    where nl = Data.Map.fromList ktn

prop_Text_Load_Node :: String -> Int -> Int -> Int -> Int -> Int
                    -> Int -> Bool -> Bool
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

prop_Text_Load_NodeFail :: [String] -> Property
prop_Text_Load_NodeFail fields =
  length fields /= 8 ==> isNothing $ Text.loadNode Data.Map.empty fields

prop_Text_NodeLSIdempotent :: Property
prop_Text_NodeLSIdempotent =
  forAll (genNode (Just 1) Nothing) $ \node ->
  -- override failN1 to what loadNode returns by default
  let n = Node.setPolicy Types.defIPolicy $
          node { Node.failN1 = True, Node.offline = False }
  in
    (Text.loadNode defGroupAssoc.
         Utils.sepSplit '|' . Text.serializeNode defGroupList) n ==?
    Just (Node.name n, n)

prop_Text_ISpecIdempotent :: Types.ISpec -> Property
prop_Text_ISpecIdempotent ispec =
  case Text.loadISpec "dummy" . Utils.sepSplit ',' .
       Text.serializeISpec $ ispec of
    Types.Bad msg -> failTest $ "Failed to load ispec: " ++ msg
    Types.Ok ispec' -> ispec ==? ispec'

prop_Text_IPolicyIdempotent :: Types.IPolicy -> Property
prop_Text_IPolicyIdempotent ipol =
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
prop_Text_CreateSerialise :: Property
prop_Text_CreateSerialise =
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

testSuite "Text"
            [ 'prop_Text_Load_Instance
            , 'prop_Text_Load_InstanceFail
            , 'prop_Text_Load_Node
            , 'prop_Text_Load_NodeFail
            , 'prop_Text_NodeLSIdempotent
            , 'prop_Text_ISpecIdempotent
            , 'prop_Text_IPolicyIdempotent
            , 'prop_Text_CreateSerialise
            ]

-- *** Simu backend

-- | Generates a tuple of specs for simulation.
genSimuSpec :: Gen (String, Int, Int, Int, Int)
genSimuSpec = do
  pol <- elements [C.allocPolicyPreferred,
                   C.allocPolicyLastResort, C.allocPolicyUnallocable,
                  "p", "a", "u"]
 -- should be reasonable (nodes/group), bigger values only complicate
 -- the display of failed tests, and we don't care (in this particular
 -- test) about big node groups
  nodes <- choose (0, 20)
  dsk <- choose (0, maxDsk)
  mem <- choose (0, maxMem)
  cpu <- choose (0, maxCpu)
  return (pol, nodes, dsk, mem, cpu)

-- | Checks that given a set of corrects specs, we can load them
-- successfully, and that at high-level the values look right.
prop_Simu_Load :: Property
prop_Simu_Load =
  forAll (choose (0, 10)) $ \ngroups ->
  forAll (replicateM ngroups genSimuSpec) $ \specs ->
  let strspecs = map (\(p, n, d, m, c) -> printf "%s,%d,%d,%d,%d"
                                          p n d m c::String) specs
      totnodes = sum $ map (\(_, n, _, _, _) -> n) specs
      mdc_in = concatMap (\(_, n, d, m, c) ->
                            replicate n (fromIntegral m, fromIntegral d,
                                         fromIntegral c,
                                         fromIntegral m, fromIntegral d))
               specs :: [(Double, Double, Double, Int, Int)]
  in case Simu.parseData strspecs of
       Types.Bad msg -> failTest $ "Failed to load specs: " ++ msg
       Types.Ok (Loader.ClusterData gl nl il tags ipol) ->
         let nodes = map snd $ IntMap.toAscList nl
             nidx = map Node.idx nodes
             mdc_out = map (\n -> (Node.tMem n, Node.tDsk n, Node.tCpu n,
                                   Node.fMem n, Node.fDsk n)) nodes
         in
         Container.size gl ==? ngroups .&&.
         Container.size nl ==? totnodes .&&.
         Container.size il ==? 0 .&&.
         length tags ==? 0 .&&.
         ipol ==? Types.defIPolicy .&&.
         nidx ==? [1..totnodes] .&&.
         mdc_in ==? mdc_out .&&.
         map Group.iPolicy (Container.elems gl) ==?
             replicate ngroups Types.defIPolicy

testSuite "Simu"
            [ 'prop_Simu_Load
            ]

-- ** Node tests

prop_Node_setAlias :: Node.Node -> String -> Bool
prop_Node_setAlias node name =
  Node.name newnode == Node.name node &&
  Node.alias newnode == name
    where newnode = Node.setAlias node name

prop_Node_setOffline :: Node.Node -> Bool -> Property
prop_Node_setOffline node status =
  Node.offline newnode ==? status
    where newnode = Node.setOffline node status

prop_Node_setXmem :: Node.Node -> Int -> Property
prop_Node_setXmem node xm =
  Node.xMem newnode ==? xm
    where newnode = Node.setXmem node xm

prop_Node_setMcpu :: Node.Node -> Double -> Property
prop_Node_setMcpu node mc =
  Types.iPolicyVcpuRatio (Node.iPolicy newnode) ==? mc
    where newnode = Node.setMcpu node mc

-- | Check that an instance add with too high memory or disk will be
-- rejected.
prop_Node_addPriFM :: Node.Node -> Instance.Instance -> Property
prop_Node_addPriFM node inst =
  Instance.mem inst >= Node.fMem node && not (Node.failN1 node) &&
  not (Instance.isOffline inst) ==>
  case Node.addPri node inst'' of
    Types.OpFail Types.FailMem -> True
    _ -> False
  where inst' = setInstanceSmallerThanNode node inst
        inst'' = inst' { Instance.mem = Instance.mem inst }

-- | Check that adding a primary instance with too much disk fails
-- with type FailDisk.
prop_Node_addPriFD :: Node.Node -> Instance.Instance -> Property
prop_Node_addPriFD node inst =
  forAll (elements Instance.localStorageTemplates) $ \dt ->
  Instance.dsk inst >= Node.fDsk node && not (Node.failN1 node) ==>
  let inst' = setInstanceSmallerThanNode node inst
      inst'' = inst' { Instance.dsk = Instance.dsk inst
                     , Instance.diskTemplate = dt }
  in case Node.addPri node inst'' of
       Types.OpFail Types.FailDisk -> True
       _ -> False

-- | Check that adding a primary instance with too many VCPUs fails
-- with type FailCPU.
prop_Node_addPriFC :: Property
prop_Node_addPriFC =
  forAll (choose (1, maxCpu)) $ \extra ->
  forAll genOnlineNode $ \node ->
  forAll (arbitrary `suchThat` Instance.notOffline) $ \inst ->
  let inst' = setInstanceSmallerThanNode node inst
      inst'' = inst' { Instance.vcpus = Node.availCpu node + extra }
  in case Node.addPri node inst'' of
       Types.OpFail Types.FailCPU -> property True
       v -> failTest $ "Expected OpFail FailCPU, but got " ++ show v

-- | Check that an instance add with too high memory or disk will be
-- rejected.
prop_Node_addSec :: Node.Node -> Instance.Instance -> Int -> Property
prop_Node_addSec node inst pdx =
  ((Instance.mem inst >= (Node.fMem node - Node.rMem node) &&
    not (Instance.isOffline inst)) ||
   Instance.dsk inst >= Node.fDsk node) &&
  not (Node.failN1 node) ==>
      isFailure (Node.addSec node inst pdx)

-- | Check that an offline instance with reasonable disk size but
-- extra mem/cpu can always be added.
prop_Node_addOfflinePri :: NonNegative Int -> NonNegative Int -> Property
prop_Node_addOfflinePri (NonNegative extra_mem) (NonNegative extra_cpu) =
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let inst' = inst { Instance.runSt = Types.AdminOffline
                   , Instance.mem = Node.availMem node + extra_mem
                   , Instance.vcpus = Node.availCpu node + extra_cpu }
  in case Node.addPri node inst' of
       Types.OpGood _ -> property True
       v -> failTest $ "Expected OpGood, but got: " ++ show v

-- | Check that an offline instance with reasonable disk size but
-- extra mem/cpu can always be added.
prop_Node_addOfflineSec :: NonNegative Int -> NonNegative Int
                        -> Types.Ndx -> Property
prop_Node_addOfflineSec (NonNegative extra_mem) (NonNegative extra_cpu) pdx =
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let inst' = inst { Instance.runSt = Types.AdminOffline
                   , Instance.mem = Node.availMem node + extra_mem
                   , Instance.vcpus = Node.availCpu node + extra_cpu
                   , Instance.diskTemplate = Types.DTDrbd8 }
  in case Node.addSec node inst' pdx of
       Types.OpGood _ -> property True
       v -> failTest $ "Expected OpGood/OpGood, but got: " ++ show v

-- | Checks for memory reservation changes.
prop_Node_rMem :: Instance.Instance -> Property
prop_Node_rMem inst =
  not (Instance.isOffline inst) ==>
  forAll (genOnlineNode `suchThat` ((> Types.unitMem) . Node.fMem)) $ \node ->
  -- ab = auto_balance, nb = non-auto_balance
  -- we use -1 as the primary node of the instance
  let inst' = inst { Instance.pNode = -1, Instance.autoBalance = True
                   , Instance.diskTemplate = Types.DTDrbd8 }
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
       x -> failTest $ "Failed to add/remove instances: " ++ show x

-- | Check mdsk setting.
prop_Node_setMdsk :: Node.Node -> SmallRatio -> Bool
prop_Node_setMdsk node mx =
  Node.loDsk node' >= 0 &&
  fromIntegral (Node.loDsk node') <= Node.tDsk node &&
  Node.availDisk node' >= 0 &&
  Node.availDisk node' <= Node.fDsk node' &&
  fromIntegral (Node.availDisk node') <= Node.tDsk node' &&
  Node.mDsk node' == mx'
    where node' = Node.setMdsk node mx'
          SmallRatio mx' = mx

-- Check tag maps
prop_Node_tagMaps_idempotent :: Property
prop_Node_tagMaps_idempotent =
  forAll genTags $ \tags ->
  Node.delTags (Node.addTags m tags) tags ==? m
    where m = Data.Map.empty

prop_Node_tagMaps_reject :: Property
prop_Node_tagMaps_reject =
  forAll (genTags `suchThat` (not . null)) $ \tags ->
  let m = Node.addTags Data.Map.empty tags
  in all (\t -> Node.rejectAddTags m [t]) tags

prop_Node_showField :: Node.Node -> Property
prop_Node_showField node =
  forAll (elements Node.defaultFields) $ \ field ->
  fst (Node.showHeader field) /= Types.unknownField &&
  Node.showField node field /= Types.unknownField

prop_Node_computeGroups :: [Node.Node] -> Bool
prop_Node_computeGroups nodes =
  let ng = Node.computeGroups nodes
      onlyuuid = map fst ng
  in length nodes == sum (map (length . snd) ng) &&
     all (\(guuid, ns) -> all ((== guuid) . Node.group) ns) ng &&
     length (nub onlyuuid) == length onlyuuid &&
     (null nodes || not (null ng))

-- Check idempotence of add/remove operations
prop_Node_addPri_idempotent :: Property
prop_Node_addPri_idempotent =
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  case Node.addPri node inst of
    Types.OpGood node' -> Node.removePri node' inst ==? node
    _ -> failTest "Can't add instance"

prop_Node_addSec_idempotent :: Property
prop_Node_addSec_idempotent =
  forAll genOnlineNode $ \node ->
  forAll (genInstanceSmallerThanNode node) $ \inst ->
  let pdx = Node.idx node + 1
      inst' = Instance.setPri inst pdx
      inst'' = inst' { Instance.diskTemplate = Types.DTDrbd8 }
  in case Node.addSec node inst'' pdx of
       Types.OpGood node' -> Node.removeSec node' inst'' ==? node
       _ -> failTest "Can't add instance"

testSuite "Node"
            [ 'prop_Node_setAlias
            , 'prop_Node_setOffline
            , 'prop_Node_setMcpu
            , 'prop_Node_setXmem
            , 'prop_Node_addPriFM
            , 'prop_Node_addPriFD
            , 'prop_Node_addPriFC
            , 'prop_Node_addSec
            , 'prop_Node_addOfflinePri
            , 'prop_Node_addOfflineSec
            , 'prop_Node_rMem
            , 'prop_Node_setMdsk
            , 'prop_Node_tagMaps_idempotent
            , 'prop_Node_tagMaps_reject
            , 'prop_Node_showField
            , 'prop_Node_computeGroups
            , 'prop_Node_addPri_idempotent
            , 'prop_Node_addSec_idempotent
            ]

-- ** Cluster tests

-- | Check that the cluster score is close to zero for a homogeneous
-- cluster.
prop_Cluster_Score_Zero :: Node.Node -> Property
prop_Cluster_Score_Zero node =
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
prop_Cluster_CStats_sane :: Property
prop_Cluster_CStats_sane =
  forAll (choose (1, 1024)) $ \count ->
  forAll genOnlineNode $ \node ->
  let fn = Node.buildPeers node Container.empty
      nlst = zip [1..] $ replicate count fn::[(Types.Ndx, Node.Node)]
      nl = Container.fromList nlst
      cstats = Cluster.totalResources nl
  in Cluster.csAdsk cstats >= 0 &&
     Cluster.csAdsk cstats <= Cluster.csFdsk cstats

-- | Check that one instance is allocated correctly, without
-- rebalances needed.
prop_Cluster_Alloc_sane :: Instance.Instance -> Property
prop_Cluster_Alloc_sane inst =
  forAll (choose (5, 20)) $ \count ->
  forAll genOnlineNode $ \node ->
  let (nl, il, inst') = makeSmallEmptyCluster node count inst
      reqnodes = Instance.requiredNodes $ Instance.diskTemplate inst
  in case Cluster.genAllocNodes defGroupList nl reqnodes True >>=
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
-- spec), on either one or two nodes. Furthermore, we test that
-- computed allocation statistics are correct.
prop_Cluster_CanTieredAlloc :: Instance.Instance -> Property
prop_Cluster_CanTieredAlloc inst =
  forAll (choose (2, 5)) $ \count ->
  forAll (genOnlineNode `suchThat` (isNodeBig 4)) $ \node ->
  let nl = makeSmallCluster node count
      il = Container.empty
      rqnodes = Instance.requiredNodes $ Instance.diskTemplate inst
      allocnodes = Cluster.genAllocNodes defGroupList nl rqnodes True
  in case allocnodes >>= \allocnodes' ->
    Cluster.tieredAlloc nl il (Just 1) inst allocnodes' [] [] of
       Types.Bad msg -> failTest $ "Failed to tiered alloc: " ++ msg
       Types.Ok (_, nl', il', ixes, cstats) ->
         let (ai_alloc, ai_pool, ai_unav) =
               Cluster.computeAllocationDelta
                (Cluster.totalResources nl)
                (Cluster.totalResources nl')
             all_nodes = Container.elems nl
         in property (not (null ixes)) .&&.
            IntMap.size il' ==? length ixes .&&.
            length ixes ==? length cstats .&&.
            sum (map Types.allocInfoVCpus [ai_alloc, ai_pool, ai_unav]) ==?
              sum (map Node.hiCpu all_nodes) .&&.
            sum (map Types.allocInfoNCpus [ai_alloc, ai_pool, ai_unav]) ==?
              sum (map Node.tCpu all_nodes) .&&.
            sum (map Types.allocInfoMem [ai_alloc, ai_pool, ai_unav]) ==?
              truncate (sum (map Node.tMem all_nodes)) .&&.
            sum (map Types.allocInfoDisk [ai_alloc, ai_pool, ai_unav]) ==?
              truncate (sum (map Node.tDsk all_nodes))

-- | Helper function to create a cluster with the given range of nodes
-- and allocate an instance on it.
genClusterAlloc :: Int -> Node.Node -> Instance.Instance
                -> Types.Result (Node.List, Instance.List, Instance.Instance)
genClusterAlloc count node inst =
  let nl = makeSmallCluster node count
      reqnodes = Instance.requiredNodes $ Instance.diskTemplate inst
  in case Cluster.genAllocNodes defGroupList nl reqnodes True >>=
     Cluster.tryAlloc nl Container.empty inst of
       Types.Bad _ -> Types.Bad "Can't allocate"
       Types.Ok as ->
         case Cluster.asSolution as of
           Nothing -> Types.Bad "Empty solution?"
           Just (xnl, xi, _, _) ->
             let xil = Container.add (Instance.idx xi) xi Container.empty
             in Types.Ok (xnl, xil, xi)

-- | Checks that on a 4-8 node cluster, once we allocate an instance,
-- we can also relocate it.
prop_Cluster_AllocRelocate :: Property
prop_Cluster_AllocRelocate =
  forAll (choose (4, 8)) $ \count ->
  forAll (genOnlineNode `suchThat` (isNodeBig 4)) $ \node ->
  forAll (genInstanceSmallerThanNode node `suchThat` isMirrored) $ \inst ->
  case genClusterAlloc count node inst of
    Types.Bad msg -> failTest msg
    Types.Ok (nl, il, inst') ->
      case IAlloc.processRelocate defGroupList nl il
             (Instance.idx inst) 1
             [(if Instance.diskTemplate inst' == Types.DTDrbd8
                 then Instance.sNode
                 else Instance.pNode) inst'] of
        Types.Ok _ -> property True
        Types.Bad msg -> failTest $ "Failed to relocate: " ++ msg

-- | Helper property checker for the result of a nodeEvac or
-- changeGroup operation.
check_EvacMode :: Group.Group -> Instance.Instance
               -> Types.Result (Node.List, Instance.List, Cluster.EvacSolution)
               -> Property
check_EvacMode grp inst result =
  case result of
    Types.Bad msg -> failTest $ "Couldn't evacuate/change group:" ++ msg
    Types.Ok (_, _, es) ->
      let moved = Cluster.esMoved es
          failed = Cluster.esFailed es
          opcodes = not . null $ Cluster.esOpCodes es
      in failmsg ("'failed' not empty: " ++ show failed) (null failed) .&&.
         failmsg "'opcodes' is null" opcodes .&&.
         case moved of
           [(idx', gdx, _)] -> failmsg "invalid instance moved" (idx == idx')
                               .&&.
                               failmsg "wrong target group"
                                         (gdx == Group.idx grp)
           v -> failmsg  ("invalid solution: " ++ show v) False
  where failmsg :: String -> Bool -> Property
        failmsg = \msg -> printTestCase ("Failed to evacuate: " ++ msg)
        idx = Instance.idx inst

-- | Checks that on a 4-8 node cluster, once we allocate an instance,
-- we can also node-evacuate it.
prop_Cluster_AllocEvacuate :: Property
prop_Cluster_AllocEvacuate =
  forAll (choose (4, 8)) $ \count ->
  forAll (genOnlineNode `suchThat` (isNodeBig 4)) $ \node ->
  forAll (genInstanceSmallerThanNode node `suchThat` isMirrored) $ \inst ->
  case genClusterAlloc count node inst of
    Types.Bad msg -> failTest msg
    Types.Ok (nl, il, inst') ->
      conjoin . map (\mode -> check_EvacMode defGroup inst' $
                              Cluster.tryNodeEvac defGroupList nl il mode
                                [Instance.idx inst']) .
                              evacModeOptions .
                              Instance.mirrorType $ inst'

-- | Checks that on a 4-8 node cluster with two node groups, once we
-- allocate an instance on the first node group, we can also change
-- its group.
prop_Cluster_AllocChangeGroup :: Property
prop_Cluster_AllocChangeGroup =
  forAll (choose (4, 8)) $ \count ->
  forAll (genOnlineNode `suchThat` (isNodeBig 4)) $ \node ->
  forAll (genInstanceSmallerThanNode node `suchThat` isMirrored) $ \inst ->
  case genClusterAlloc count node inst of
    Types.Bad msg -> failTest msg
    Types.Ok (nl, il, inst') ->
      -- we need to add a second node group and nodes to the cluster
      let nl2 = Container.elems $ makeSmallCluster node count
          grp2 = Group.setIdx defGroup (Group.idx defGroup + 1)
          maxndx = maximum . map Node.idx $ nl2
          nl3 = map (\n -> n { Node.group = Group.idx grp2
                             , Node.idx = Node.idx n + maxndx }) nl2
          nl4 = Container.fromList . map (\n -> (Node.idx n, n)) $ nl3
          gl' = Container.add (Group.idx grp2) grp2 defGroupList
          nl' = IntMap.union nl nl4
      in check_EvacMode grp2 inst' $
         Cluster.tryChangeGroup gl' nl' il [] [Instance.idx inst']

-- | Check that allocating multiple instances on a cluster, then
-- adding an empty node, results in a valid rebalance.
prop_Cluster_AllocBalance :: Property
prop_Cluster_AllocBalance =
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
       Types.Bad msg -> failTest $ "Failed to allocate: " ++ msg
       Types.Ok (_, _, _, [], _) -> failTest "Failed to allocate: no instances"
       Types.Ok (_, xnl, il', _, _) ->
         let ynl = Container.add (Node.idx hnode) hnode xnl
             cv = Cluster.compCV ynl
             tbl = Cluster.Table ynl il' cv []
         in printTestCase "Failed to rebalance" $
            canBalance tbl True True False

-- | Checks consistency.
prop_Cluster_CheckConsistency :: Node.Node -> Instance.Instance -> Bool
prop_Cluster_CheckConsistency node inst =
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
prop_Cluster_SplitCluster :: Node.Node -> Instance.Instance -> Property
prop_Cluster_SplitCluster node inst =
  forAll (choose (0, 100)) $ \icnt ->
  let nl = makeSmallCluster node 2
      (nl', il') = foldl (\(ns, is) _ -> assignInstance ns is inst 0 1)
                   (nl, Container.empty) [1..icnt]
      gni = Cluster.splitCluster nl' il'
  in sum (map (Container.size . snd . snd) gni) == icnt &&
     all (\(guuid, (nl'', _)) -> all ((== guuid) . Node.group)
                                 (Container.elems nl'')) gni

-- | Helper function to check if we can allocate an instance on a
-- given node list.
canAllocOn :: Node.List -> Int -> Instance.Instance -> Bool
canAllocOn nl reqnodes inst =
  case Cluster.genAllocNodes defGroupList nl reqnodes True >>=
       Cluster.tryAlloc nl (Container.empty) inst of
       Types.Bad _ -> False
       Types.Ok as ->
         case Cluster.asSolution as of
           Nothing -> False
           Just _ -> True

-- | Checks that allocation obeys minimum and maximum instance
-- policies. The unittest generates a random node, duplicates it /count/
-- times, and generates a random instance that can be allocated on
-- this mini-cluster; it then checks that after applying a policy that
-- the instance doesn't fits, the allocation fails.
prop_Cluster_AllocPolicy :: Node.Node -> Property
prop_Cluster_AllocPolicy node =
  -- rqn is the required nodes (1 or 2)
  forAll (choose (1, 2)) $ \rqn ->
  forAll (choose (5, 20)) $ \count ->
  forAll (arbitrary `suchThat` (canAllocOn (makeSmallCluster node count) rqn))
         $ \inst ->
  forAll (arbitrary `suchThat` (isFailure .
                                Instance.instMatchesPolicy inst)) $ \ipol ->
  let node' = Node.setPolicy ipol node
      nl = makeSmallCluster node' count
  in not $ canAllocOn nl rqn inst

testSuite "Cluster"
            [ 'prop_Cluster_Score_Zero
            , 'prop_Cluster_CStats_sane
            , 'prop_Cluster_Alloc_sane
            , 'prop_Cluster_CanTieredAlloc
            , 'prop_Cluster_AllocRelocate
            , 'prop_Cluster_AllocEvacuate
            , 'prop_Cluster_AllocChangeGroup
            , 'prop_Cluster_AllocBalance
            , 'prop_Cluster_CheckConsistency
            , 'prop_Cluster_SplitCluster
            , 'prop_Cluster_AllocPolicy
            ]

-- ** OpCodes tests

-- | Check that opcode serialization is idempotent.
prop_OpCodes_serialization :: OpCodes.OpCode -> Property
prop_OpCodes_serialization op =
  case J.readJSON (J.showJSON op) of
    J.Error e -> failTest $ "Cannot deserialise: " ++ e
    J.Ok op' -> op ==? op'

testSuite "OpCodes"
            [ 'prop_OpCodes_serialization ]

-- ** Jobs tests

-- | Check that (queued) job\/opcode status serialization is idempotent.
prop_Jobs_OpStatus_serialization :: Jobs.OpStatus -> Property
prop_Jobs_OpStatus_serialization os =
  case J.readJSON (J.showJSON os) of
    J.Error e -> failTest $ "Cannot deserialise: " ++ e
    J.Ok os' -> os ==? os'

prop_Jobs_JobStatus_serialization :: Jobs.JobStatus -> Property
prop_Jobs_JobStatus_serialization js =
  case J.readJSON (J.showJSON js) of
    J.Error e -> failTest $ "Cannot deserialise: " ++ e
    J.Ok js' -> js ==? js'

testSuite "Jobs"
            [ 'prop_Jobs_OpStatus_serialization
            , 'prop_Jobs_JobStatus_serialization
            ]

-- ** Loader tests

prop_Loader_lookupNode :: [(String, Int)] -> String -> String -> Property
prop_Loader_lookupNode ktn inst node =
  Loader.lookupNode nl inst node ==? Data.Map.lookup node nl
    where nl = Data.Map.fromList ktn

prop_Loader_lookupInstance :: [(String, Int)] -> String -> Property
prop_Loader_lookupInstance kti inst =
  Loader.lookupInstance il inst ==? Data.Map.lookup inst il
    where il = Data.Map.fromList kti

prop_Loader_assignIndices :: Property
prop_Loader_assignIndices =
  -- generate nodes with unique names
  forAll (arbitrary `suchThat`
          (\nodes ->
             let names = map Node.name nodes
             in length names == length (nub names))) $ \nodes ->
  let (nassoc, kt) =
        Loader.assignIndices (map (\n -> (Node.name n, n)) nodes)
  in Data.Map.size nassoc == length nodes &&
     Container.size kt == length nodes &&
     if not (null nodes)
       then maximum (IntMap.keys kt) == length nodes - 1
       else True

-- | Checks that the number of primary instances recorded on the nodes
-- is zero.
prop_Loader_mergeData :: [Node.Node] -> Bool
prop_Loader_mergeData ns =
  let na = Container.fromList $ map (\n -> (Node.idx n, n)) ns
  in case Loader.mergeData [] [] [] []
         (Loader.emptyCluster {Loader.cdNodes = na}) of
    Types.Bad _ -> False
    Types.Ok (Loader.ClusterData _ nl il _ _) ->
      let nodes = Container.elems nl
          instances = Container.elems il
      in (sum . map (length . Node.pList)) nodes == 0 &&
         null instances

-- | Check that compareNameComponent on equal strings works.
prop_Loader_compareNameComponent_equal :: String -> Bool
prop_Loader_compareNameComponent_equal s =
  BasicTypes.compareNameComponent s s ==
    BasicTypes.LookupResult BasicTypes.ExactMatch s

-- | Check that compareNameComponent on prefix strings works.
prop_Loader_compareNameComponent_prefix :: NonEmptyList Char -> String -> Bool
prop_Loader_compareNameComponent_prefix (NonEmpty s1) s2 =
  BasicTypes.compareNameComponent (s1 ++ "." ++ s2) s1 ==
    BasicTypes.LookupResult BasicTypes.PartialMatch s1

testSuite "Loader"
            [ 'prop_Loader_lookupNode
            , 'prop_Loader_lookupInstance
            , 'prop_Loader_assignIndices
            , 'prop_Loader_mergeData
            , 'prop_Loader_compareNameComponent_equal
            , 'prop_Loader_compareNameComponent_prefix
            ]

-- ** Types tests

prop_Types_AllocPolicy_serialisation :: Types.AllocPolicy -> Property
prop_Types_AllocPolicy_serialisation apol =
  case J.readJSON (J.showJSON apol) of
    J.Ok p -> p ==? apol
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_DiskTemplate_serialisation :: Types.DiskTemplate -> Property
prop_Types_DiskTemplate_serialisation dt =
  case J.readJSON (J.showJSON dt) of
    J.Ok p -> p ==? dt
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_ISpec_serialisation :: Types.ISpec -> Property
prop_Types_ISpec_serialisation ispec =
  case J.readJSON (J.showJSON ispec) of
    J.Ok p -> p ==? ispec
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_IPolicy_serialisation :: Types.IPolicy -> Property
prop_Types_IPolicy_serialisation ipol =
  case J.readJSON (J.showJSON ipol) of
    J.Ok p -> p ==? ipol
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_EvacMode_serialisation :: Types.EvacMode -> Property
prop_Types_EvacMode_serialisation em =
  case J.readJSON (J.showJSON em) of
    J.Ok p -> p ==? em
    J.Error s -> failTest $ "Failed to deserialise: " ++ s

prop_Types_opToResult :: Types.OpResult Int -> Bool
prop_Types_opToResult op =
  case op of
    Types.OpFail _ -> Types.isBad r
    Types.OpGood v -> case r of
                        Types.Bad _ -> False
                        Types.Ok v' -> v == v'
  where r = Types.opToResult op

prop_Types_eitherToResult :: Either String Int -> Bool
prop_Types_eitherToResult ei =
  case ei of
    Left _ -> Types.isBad r
    Right v -> case r of
                 Types.Bad _ -> False
                 Types.Ok v' -> v == v'
    where r = Types.eitherToResult ei

testSuite "Types"
            [ 'prop_Types_AllocPolicy_serialisation
            , 'prop_Types_DiskTemplate_serialisation
            , 'prop_Types_ISpec_serialisation
            , 'prop_Types_IPolicy_serialisation
            , 'prop_Types_EvacMode_serialisation
            , 'prop_Types_opToResult
            , 'prop_Types_eitherToResult
            ]

-- ** CLI tests

-- | Test correct parsing.
prop_CLI_parseISpec :: String -> Int -> Int -> Int -> Property
prop_CLI_parseISpec descr dsk mem cpu =
  let str = printf "%d,%d,%d" dsk mem cpu::String
  in CLI.parseISpecString descr str ==? Types.Ok (Types.RSpec cpu mem dsk)

-- | Test parsing failure due to wrong section count.
prop_CLI_parseISpecFail :: String -> Property
prop_CLI_parseISpecFail descr =
  forAll (choose (0,100) `suchThat` ((/=) 3)) $ \nelems ->
  forAll (replicateM nelems arbitrary) $ \values ->
  let str = intercalate "," $ map show (values::[Int])
  in case CLI.parseISpecString descr str of
       Types.Ok v -> failTest $ "Expected failure, got " ++ show v
       _ -> property True

-- | Test parseYesNo.
prop_CLI_parseYesNo :: Bool -> Bool -> [Char] -> Property
prop_CLI_parseYesNo def testval val =
  forAll (elements [val, "yes", "no"]) $ \actual_val ->
  if testval
    then CLI.parseYesNo def Nothing ==? Types.Ok def
    else let result = CLI.parseYesNo def (Just actual_val)
         in if actual_val `elem` ["yes", "no"]
              then result ==? Types.Ok (actual_val == "yes")
              else property $ Types.isBad result

-- | Helper to check for correct parsing of string arg.
checkStringArg :: [Char]
               -> (GetOpt.OptDescr (CLI.Options -> Types.Result CLI.Options),
                   CLI.Options -> Maybe [Char])
               -> Property
checkStringArg val (opt, fn) =
  let GetOpt.Option _ longs _ _ = opt
  in case longs of
       [] -> failTest "no long options?"
       cmdarg:_ ->
         case CLI.parseOptsInner ["--" ++ cmdarg ++ "=" ++ val] "prog" [opt] of
           Left e -> failTest $ "Failed to parse option: " ++ show e
           Right (options, _) -> fn options ==? Just val

-- | Test a few string arguments.
prop_CLI_StringArg :: [Char] -> Property
prop_CLI_StringArg argument =
  let args = [ (CLI.oDataFile,      CLI.optDataFile)
             , (CLI.oDynuFile,      CLI.optDynuFile)
             , (CLI.oSaveCluster,   CLI.optSaveCluster)
             , (CLI.oReplay,        CLI.optReplay)
             , (CLI.oPrintCommands, CLI.optShowCmds)
             , (CLI.oLuxiSocket,    CLI.optLuxi)
             ]
  in conjoin $ map (checkStringArg argument) args

-- | Helper to test that a given option is accepted OK with quick exit.
checkEarlyExit :: String -> [CLI.OptType] -> String -> Property
checkEarlyExit name options param =
  case CLI.parseOptsInner [param] name options of
    Left (code, _) -> if code == 0
                          then property True
                          else failTest $ "Program " ++ name ++
                                 " returns invalid code " ++ show code ++
                                 " for option " ++ param
    _ -> failTest $ "Program " ++ name ++ " doesn't consider option " ++
         param ++ " as early exit one"

-- | Test that all binaries support some common options. There is
-- nothing actually random about this test...
prop_CLI_stdopts :: Property
prop_CLI_stdopts =
  let params = ["-h", "--help", "-V", "--version"]
      opts = map (\(name, (_, o)) -> (name, o)) Program.personalities
      -- apply checkEarlyExit across the cartesian product of params and opts
  in conjoin [checkEarlyExit n o p | p <- params, (n, o) <- opts]

testSuite "CLI"
          [ 'prop_CLI_parseISpec
          , 'prop_CLI_parseISpecFail
          , 'prop_CLI_parseYesNo
          , 'prop_CLI_StringArg
          , 'prop_CLI_stdopts
          ]

-- * JSON tests

prop_JSON_toArray :: [Int] -> Property
prop_JSON_toArray intarr =
  let arr = map J.showJSON intarr in
  case JSON.toArray (J.JSArray arr) of
    Types.Ok arr' -> arr ==? arr'
    Types.Bad err -> failTest $ "Failed to parse array: " ++ err

prop_JSON_toArrayFail :: Int -> String -> Bool -> Property
prop_JSON_toArrayFail i s b =
  -- poor man's instance Arbitrary JSValue
  forAll (elements [J.showJSON i, J.showJSON s, J.showJSON b]) $ \item ->
  case JSON.toArray item of
    Types.Bad _ -> property True
    Types.Ok result -> failTest $ "Unexpected parse, got " ++ show result

testSuite "JSON"
          [ 'prop_JSON_toArray
          , 'prop_JSON_toArrayFail
          ]

-- * Luxi tests

instance Arbitrary Luxi.TagObject where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Luxi.LuxiReq where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Luxi.LuxiOp where
  arbitrary = do
    lreq <- arbitrary
    case lreq of
      Luxi.ReqQuery -> Luxi.Query <$> arbitrary <*> getFields <*> genFilter
      Luxi.ReqQueryNodes -> Luxi.QueryNodes <$> (listOf getFQDN) <*>
                            getFields <*> arbitrary
      Luxi.ReqQueryGroups -> Luxi.QueryGroups <$> arbitrary <*>
                             arbitrary <*> arbitrary
      Luxi.ReqQueryInstances -> Luxi.QueryInstances <$> (listOf getFQDN) <*>
                                getFields <*> arbitrary
      Luxi.ReqQueryJobs -> Luxi.QueryJobs <$> arbitrary <*> getFields
      Luxi.ReqQueryExports -> Luxi.QueryExports <$>
                              (listOf getFQDN) <*> arbitrary
      Luxi.ReqQueryConfigValues -> Luxi.QueryConfigValues <$> getFields
      Luxi.ReqQueryClusterInfo -> pure Luxi.QueryClusterInfo
      Luxi.ReqQueryTags -> Luxi.QueryTags <$> arbitrary <*> getFQDN
      Luxi.ReqSubmitJob -> Luxi.SubmitJob <$> (resize maxOpCodes arbitrary)
      Luxi.ReqSubmitManyJobs -> Luxi.SubmitManyJobs <$>
                                (resize maxOpCodes arbitrary)
      Luxi.ReqWaitForJobChange -> Luxi.WaitForJobChange <$> arbitrary <*>
                                  getFields <*> pure J.JSNull <*>
                                  pure J.JSNull <*> arbitrary
      Luxi.ReqArchiveJob -> Luxi.ArchiveJob <$> arbitrary
      Luxi.ReqAutoArchiveJobs -> Luxi.AutoArchiveJobs <$> arbitrary <*>
                                 arbitrary
      Luxi.ReqCancelJob -> Luxi.CancelJob <$> arbitrary
      Luxi.ReqSetDrainFlag -> Luxi.SetDrainFlag <$> arbitrary
      Luxi.ReqSetWatcherPause -> Luxi.SetWatcherPause <$> arbitrary

-- | Simple check that encoding/decoding of LuxiOp works.
prop_Luxi_CallEncoding :: Luxi.LuxiOp -> Property
prop_Luxi_CallEncoding op =
  (Luxi.validateCall (Luxi.buildCall op) >>= Luxi.decodeCall) ==? Types.Ok op

-- | Helper to a get a temporary file name.
getTempFileName :: IO FilePath
getTempFileName = do
  tempdir <- getTemporaryDirectory
  (fpath, handle) <- openTempFile tempdir "luxitest"
  _ <- hClose handle
  removeFile fpath
  return fpath

-- | Server ping-pong helper.
luxiServerPong :: Luxi.Client -> IO ()
luxiServerPong c = do
  msg <- Luxi.recvMsgExt c
  case msg of
    Luxi.RecvOk m -> Luxi.sendMsg c m >> luxiServerPong c
    _ -> return ()

-- | Client ping-pong helper.
luxiClientPong :: Luxi.Client -> [String] -> IO [String]
luxiClientPong c =
  mapM (\m -> Luxi.sendMsg c m >> Luxi.recvMsg c)

-- | Monadic check that, given a server socket, we can connect via a
-- client to it, and that we can send a list of arbitrary messages and
-- get back what we sent.
prop_Luxi_ClientServer :: [[DNSChar]] -> Property
prop_Luxi_ClientServer dnschars = monadicIO $ do
  let msgs = map (map dnsGetChar) dnschars
  fpath <- run $ getTempFileName
  -- we need to create the server first, otherwise (if we do it in the
  -- forked thread) the client could try to connect to it before it's
  -- ready
  server <- run $ Luxi.getServer fpath
  -- fork the server responder
  _ <- run . forkIO $
    bracket
      (Luxi.acceptClient server)
      (\c -> Luxi.closeClient c >> Luxi.closeServer fpath server)
      luxiServerPong
  replies <- run $
    bracket
      (Luxi.getClient fpath)
      Luxi.closeClient
      (\c -> luxiClientPong c msgs)
  assert $ replies == msgs

testSuite "Luxi"
          [ 'prop_Luxi_CallEncoding
          , 'prop_Luxi_ClientServer
          ]

-- * Ssconf tests

instance Arbitrary Ssconf.SSKey where
  arbitrary = elements [minBound..maxBound]

prop_Ssconf_filename :: Ssconf.SSKey -> Property
prop_Ssconf_filename key =
  printTestCase "Key doesn't start with correct prefix" $
    Ssconf.sSFilePrefix `isPrefixOf` Ssconf.keyToFilename (Just "") key

testSuite "Ssconf"
  [ 'prop_Ssconf_filename
  ]

-- * Rpc tests

-- | Monadic check that, for an offline node and a call that does not
-- offline nodes, we get a OfflineNodeError response.
-- FIXME: We need a way of generalizing this, running it for
-- every call manually will soon get problematic
prop_Rpc_noffl_request_allinstinfo :: Rpc.RpcCallAllInstancesInfo -> Property
prop_Rpc_noffl_request_allinstinfo call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left (Rpc.OfflineNodeError node))]

prop_Rpc_noffl_request_instlist :: Rpc.RpcCallInstanceList -> Property
prop_Rpc_noffl_request_instlist call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left (Rpc.OfflineNodeError node))]

prop_Rpc_noffl_request_nodeinfo :: Rpc.RpcCallNodeInfo -> Property
prop_Rpc_noffl_request_nodeinfo call =
  forAll (arbitrary `suchThat` Objects.nodeOffline) $ \node -> monadicIO $ do
      res <- run $ Rpc.executeRpcCall [node] call
      stop $ res ==? [(node, Left (Rpc.OfflineNodeError node))]

testSuite "Rpc"
  [ 'prop_Rpc_noffl_request_allinstinfo
  , 'prop_Rpc_noffl_request_instlist
  , 'prop_Rpc_noffl_request_nodeinfo
  ]

-- * Qlang tests

-- | Tests that serialisation/deserialisation of filters is
-- idempotent.
prop_Qlang_Serialisation :: Property
prop_Qlang_Serialisation =
  forAll genFilter $ \flt ->
  J.readJSON (J.showJSON flt) ==? J.Ok flt

testSuite "Qlang"
  [ 'prop_Qlang_Serialisation
  ]

module Ganeti.HTools.QC
    where

import Test.QuickCheck
import Data.Maybe
import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.IAlloc as IAlloc
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.PeerMap as PeerMap
import qualified Ganeti.HTools.Rapi as Rapi
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Utils as Utils

-- copied from the introduction to quickcheck
instance Arbitrary Char where
    arbitrary     = choose ('\32', '\128')

-- let's generate a random instance
instance Arbitrary Instance.Instance where
    arbitrary = do
      name <- arbitrary
      mem <- choose(0, 100)
      dsk <- choose(0, 100)
      run_st <- arbitrary
      pn <- arbitrary
      sn <- arbitrary
      return $ Instance.create name mem dsk run_st pn sn

-- and a random node
instance Arbitrary Node.Node where
    arbitrary = do
      name <- arbitrary
      mem_t <- arbitrary
      mem_f <- choose (0, mem_t)
      mem_n <- choose (0, mem_t - mem_f)
      dsk_t <- arbitrary
      dsk_f <- choose (0, dsk_t)
      offl <- arbitrary
      let n = Node.create name (fromIntegral mem_t) mem_n mem_f
              (fromIntegral dsk_t) dsk_f offl
          n' = Node.buildPeers n Container.empty
      return n'

-- | Make sure add is idempotent
prop_PeerMap_addIdempotent pmap key elem =
    fn puniq == fn (fn puniq)
    where fn = PeerMap.add key elem
          puniq = PeerMap.accumArray const pmap
          _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key, elem::PeerMap.Elem)

-- | Make sure remove is idempotent
prop_PeerMap_removeIdempotent pmap key =
    fn puniq == fn (fn puniq)
    where fn = PeerMap.remove key
          puniq = PeerMap.accumArray const pmap
          _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key)

-- | Make sure a missing item returns 0
prop_PeerMap_findMissing pmap key =
    PeerMap.find key (PeerMap.remove key puniq) == 0
    where fn = PeerMap.remove key
          puniq = PeerMap.accumArray const pmap
          _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key)

-- | Make sure an added item is found
prop_PeerMap_addFind pmap key elem =
    PeerMap.find key (PeerMap.add key elem puniq) == elem
    where puniq = PeerMap.accumArray const pmap
          _types = (pmap::PeerMap.PeerMap,
                    key::PeerMap.Key, elem::PeerMap.Elem)

-- | Manual check that maxElem returns the maximum indeed, or 0 for null
prop_PeerMap_maxElem pmap =
    PeerMap.maxElem puniq == if null puniq then 0
                             else (maximum . snd . unzip) puniq
    where
          puniq = PeerMap.accumArray const pmap
          _types = pmap::PeerMap.PeerMap

prop_Node_addPri node inst = (Instance.mem inst >= Node.f_mem node ||
                              Instance.dsk inst >= Node.f_dsk node) &&
                             (not $ Node.failN1 node)
                             ==>
                             isNothing(Node.addPri node inst)
    where _types = (node::Node.Node, inst::Instance.Instance)

prop_Node_addSec node inst pdx =
    (Instance.mem inst >= (Node.f_mem node - Node.r_mem node) ||
     Instance.dsk inst >= Node.f_dsk node) &&
    (not $ Node.failN1 node)
    ==> isNothing(Node.addSec node inst pdx)
        where _types = (node::Node.Node, inst::Instance.Instance, pdx::Int)

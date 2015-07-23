{-| Balancing task of the maintenance daemon.

This module carries out the automated balancing done by the
maintenance daemon. The actual balancing algorithm is imported
from htools.

-}
{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.MaintD.Balance
  ( balanceTask
  ) where

import Control.Exception.Lifted (bracket)
import Control.Monad (liftM)
import Control.Monad.IO.Class (liftIO)
import qualified Data.Set as Set
import qualified Data.Map as Map
import qualified Data.Traversable as Traversable
import System.IO.Error (tryIOError)
import Text.Printf (printf)

import Ganeti.BasicTypes ( ResultT, mkResultT, mkResultT'
                         , GenericResult(..), Result)
import Ganeti.Cpu.Types (emptyCPUavgload, CPUavgload(..))
import Ganeti.HTools.AlgorithmParams (AlgorithmOptions(..), defaultOptions)
import qualified Ganeti.HTools.Backend.MonD as MonD
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import qualified Ganeti.HTools.Cluster.Utils as ClusterUtils
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.JQueue (currentTimestamp)
import Ganeti.JQueue.Objects (Timestamp)
import Ganeti.Jobs (submitJobs)
import Ganeti.HTools.Types ( zeroUtil, DynUtil(cpuWeight), addUtil, subUtil
                           , MoveJob)
import Ganeti.Logging.Lifted (logDebug)
import Ganeti.MaintD.Utils (annotateOpCode)
import qualified Ganeti.Luxi as L
import Ganeti.OpCodes (MetaOpCode)
import qualified Ganeti.Path as Path
import qualified Ganeti.Query.Language as Qlang
import Ganeti.Types (JobId)
import Ganeti.Utils (logAndBad)

-- * Collection of dynamic load data

data AllReports = AllReports { rTotal :: MonD.Report
                             , rIndividual :: MonD.Report
                             }

-- | Empty report. It describes an idle node and can be used as
-- default value for nodes marked as offline.
emptyReports :: AllReports
emptyReports = AllReports (MonD.CPUavgloadReport emptyCPUavgload)
                          (MonD.InstanceCpuReport Map.empty)

-- | Query a node unless it is offline and return all
-- CPU reports. For offline nodes return the empty report.
queryNode :: Node.Node -> ResultT String IO AllReports
queryNode node = do
  let getReport dc = mkResultT
                     . liftM (maybe (Bad $ "Failed collecting "
                                           ++ MonD.dName dc
                                           ++ " from " ++ Node.name node) Ok
                              . MonD.mkReport dc)
                     $ MonD.fromCurl dc node
  if Node.offline node
    then return emptyReports
    else do
      total <- getReport MonD.totalCPUCollector
      xeninstances <- getReport MonD.xenCPUCollector
      return $ AllReports total xeninstances

-- | Get a map with the CPU live data for all nodes; for offline nodes
-- the empty report is guessed.
queryLoad :: Node.List -> ResultT String IO (Container.Container AllReports)
queryLoad = Traversable.mapM queryNode

-- | Ask luxid about the hypervisors used. As, at the moment, we only
-- have specialised CPU collectors for xen, we're only interested which
-- instances run under the Xen hypervisor.
getXenInstances :: ResultT String IO (Set.Set String)
getXenInstances = do
  let query = L.Query (Qlang.ItemTypeOpCode Qlang.QRInstance)
              ["name", "hypervisor"] Qlang.EmptyFilter
  luxiSocket <- liftIO Path.defaultQuerySocket
  raw <- bracket (mkResultT . liftM (either (Bad . show) Ok)
                   . tryIOError $ L.getLuxiClient luxiSocket)
                 (liftIO . L.closeClient)
                 $ mkResultT' . L.callMethod query
  answer <- L.extractArray raw >>= mapM (mapM L.fromJValWithStatus)
  let getXen [name, hv] | hv `elem` ["xen-pvm", "xen-hvm"] = [name]
      getXen _ = []
  return $ Set.fromList (answer >>= getXen)

-- | Update the CPU load of one instance based on the reports.
-- Fail if instance CPU load is not (yet) available.
updateCPUInstance :: Node.List
                  -> Container.Container AllReports
                  -> Set.Set String
                  -> Instance.Instance
                  -> Result Instance.Instance
updateCPUInstance nl reports xeninsts inst =
  let name = Instance.name inst
      nidx = Instance.pNode inst
  in if name `Set.member` xeninsts
    then let rep = rIndividual $ Container.find nidx reports
         in case rep of MonD.InstanceCpuReport m | Map.member name m ->
                          return $ inst { Instance.util = zeroUtil {
                                             cpuWeight = m Map.! name } }
                        _ | Node.offline $ Container.find nidx nl ->
                          return $ inst { Instance.util = zeroUtil }
                        _ -> fail $ "Xen CPU data unavailable for " ++ name
    else let rep = rTotal $ Container.find nidx reports
         in case rep of MonD.CPUavgloadReport (CPUavgload _ _ ndload) ->
                          let w = ndload * fromIntegral (Instance.vcpus inst)
                                  / (fromIntegral . Node.uCpu
                                       $ Container.find nidx nl)
                          in return $ inst { Instance.util =
                                                zeroUtil { cpuWeight = w }}
                        _ -> fail $ "CPU data unavailable for node of " ++ name

-- | Update CPU usage data based on the collected reports. That is, get the
-- CPU usage of all instances from the reports and also update the nodes
-- accordingly.
updateCPULoad :: (Node.List, Instance.List)
              -> Container.Container AllReports
              -> Set.Set String
              -> Result (Node.List, Instance.List)
updateCPULoad (nl, il) reports xeninsts = do
  il' <- Traversable.mapM (updateCPUInstance nl reports xeninsts) il
  let addNodeUtil n delta = n { Node.utilLoad = addUtil (Node.utilLoad n) delta
                              , Node.utilLoadForth =
                                  addUtil (Node.utilLoadForth n) delta
                              }
  let updateNodeUtil nnl inst_old inst_new =
        let delta = subUtil (Instance.util inst_new) $ Instance.util inst_old
            nidx = Instance.pNode inst_old
            n = Container.find nidx nnl
            n' = addNodeUtil n delta
        in Container.add nidx n' nnl
  let nl' = foldl (\nnl i -> updateNodeUtil nnl (Container.find i il)
                               $ Container.find i il') nl $ Container.keys il
  return (nl', il')

-- * Balancing

-- | Transform an instance move into a submittable job.
moveToJob :: Timestamp -> (Node.List, Instance.List) -> MoveJob -> [MetaOpCode]
moveToJob now (nl, il) (_, idx, move, _) =
  let opCodes = Cluster.iMoveToJob nl il idx move
  in map (annotateOpCode "auto-balancing the cluster" now) opCodes

-- | Iteratively improve a cluster by iterating over tryBalance.
iterateBalance :: AlgorithmOptions
               -> Cluster.Table -- ^ the starting table
               -> [MoveJob]     -- ^ current command list
               -> [MoveJob]     -- ^ resulting commands
iterateBalance opts ini_tbl cmds =
  let Cluster.Table ini_nl ini_il _ _ = ini_tbl
      m_next_tbl = Cluster.tryBalance opts ini_tbl
  in case m_next_tbl of
    Just next_tbl@(Cluster.Table _ _ _ plc@(curplc:_)) ->
      let (idx, _, _, move, _) = curplc
          plc_len = length plc
          (_, cs) = Cluster.printSolutionLine ini_nl ini_il 1 1 curplc plc_len
          afn = Cluster.involvedNodes ini_il curplc
          cmds' = (afn, idx, move, cs):cmds
      in iterateBalance opts next_tbl cmds'
    _ -> cmds

-- | Balance a single group, restricted to the allowed nodes and
-- minimal gain.
balanceGroup :: L.Client
             -> Set.Set Int
             -> Double
             -> (Int,  (Node.List, Instance.List))
             -> ResultT String IO [JobId]
balanceGroup client allowedNodes threshold (gidx, (nl, il)) = do
  logDebug $ printf "Balancing group %d, %d nodes, %d instances." gidx
               (Container.size nl) (Container.size il)
  let ini_cv = Metrics.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
      opts = defaultOptions { algAllowedNodes = Just allowedNodes
                            , algMinGain = threshold
                            , algMinGainLimit = 10 * threshold
                            }
      cmds = iterateBalance opts ini_tbl []
      tasks = take 1 $ Cluster.splitJobs cmds
  logDebug $ "First task group: " ++ show tasks
  now <- liftIO currentTimestamp
  let jobs = tasks >>= map (moveToJob now (nl, il))
  if null jobs
    then return []
    else do
      jids <- liftIO $ submitJobs jobs client
      case jids of
        Bad e -> mkResultT . logAndBad
                   $ "Failure submitting balancing jobs: " ++ e
        Ok jids' -> return jids'

-- * Interface function

-- | Carry out all the needed balancing, based on live CPU data, only touching
-- the available nodes. Only carry out balancing steps where the gain is above
-- the threshold.
balanceTask :: (Node.List, Instance.List) -- ^ current cluster configuration
            -> Set.Set Int -- ^ node indices on which actions may be taken
            -> Double -- ^ threshold for improvement
            -> ResultT String IO [JobId] -- ^ jobs submitted
balanceTask (nl, il) okNodes threshold = do
  logDebug "Collecting dynamic load values"
  reports <- queryLoad nl
  xenInstances <- getXenInstances
  (nl', il') <- mkResultT . return $ updateCPULoad (nl, il) reports xenInstances
  let ngroups = ClusterUtils.splitCluster nl' il'
  luxiSocket <- liftIO Path.defaultQuerySocket
  bracket (liftIO $ L.getLuxiClient luxiSocket) (liftIO . L.closeClient) $ \c ->
    liftM concat $ mapM (balanceGroup c okNodes threshold) ngroups

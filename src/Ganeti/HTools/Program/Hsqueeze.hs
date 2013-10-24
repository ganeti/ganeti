{-| Node freeing scheduler

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

module Ganeti.HTools.Program.Hsqueeze
  (main
  , options
  , arguments
  ) where

import Control.Applicative
import Control.Monad
import Data.Function
import Data.List
import Data.Maybe
import qualified Data.IntMap as IntMap

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.HTools.CLI
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import Ganeti.HTools.ExtLoader
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Loader
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types
import Ganeti.Utils

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ luxi
    , oDataFile
    , oTargetResources
    , oSaveCluster
    , oVerbose
    , oNoHeaders
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Within a cluster configuration, decide if the node hosts only
-- externally-mirrored instances.
onlyExternal ::  (Node.List, Instance.List) -> Node.Node -> Bool
onlyExternal (_, il) nd =
  not
  . any (Instance.usesLocalStorage . flip Container.find il)
  $ Node.pList nd

-- | Predicate whether, in a configuration, all running instances are on
-- online nodes.
allInstancesOnOnlineNodes :: (Node.List, Instance.List) -> Bool
allInstancesOnOnlineNodes (nl, il) =
 all (not . Node.offline . flip Container.find nl . Instance.pNode)
 . IntMap.elems
 $ il

-- | Predicate whether, in a configuration, each node has enough resources 
-- to additionally host the given instance.
allNodesCapacityFor :: Instance.Instance -> (Node.List, Instance.List) -> Bool
allNodesCapacityFor inst (nl, _) =
  all (isOk . flip Node.addPri inst) . IntMap.elems $ nl

-- | Balance a configuration, possible for 0 steps, till no further improvement
-- is possible.
balance :: (Node.List, Instance.List) -> (Node.List, Instance.List)
balance (nl, il) =
  let ini_cv = Cluster.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
      balanceStep tbl = Cluster.tryBalance tbl True True False 0.0 0.0
      (Cluster.Table nl' il' _ _) = fromJust . last . takeWhile isJust
                                    $ iterate (>>= balanceStep) (Just ini_tbl)
  in (nl', il')

-- | In a configuration, mark a node as offline.
offlineNode :: (Node.List, Instance.List) -> Ndx -> (Node.List, Instance.List)
offlineNode (nl, il) ndx =
  let nd = Container.find ndx nl
      nd' = Node.setOffline nd True
      nl' = Container.add ndx nd' nl
  in (nl', il)

-- | Offline a list node, and return the state after a balancing attempt.
offlineNodes :: [Ndx] -> (Node.List, Instance.List)
                -> (Node.List, Instance.List)
offlineNodes ndxs conf =
  let conf' = foldl offlineNode conf ndxs
  in balance conf'

-- | Predicate on whether a list of nodes can be offlined simultaneously in a
-- given configuration, while still leaving enough capacity on every node for
-- the given instance
canOffline :: Instance.Instance -> [Node.Node] -> (Node.List, Instance.List)
              -> Bool
canOffline inst nds conf = 
  let conf' = offlineNodes (map Node.idx nds) conf
  in allInstancesOnOnlineNodes conf' && allNodesCapacityFor inst conf'

-- | Greedily offline the nodes, starting from the last element, and return
-- the list of nodes that could simultaneously be offlined, while keeping
-- the resources specified by an instance.
greedyOfflineNodes :: Instance.Instance -> (Node.List, Instance.List) 
                      -> [Node.Node] -> [Node.Node]
greedyOfflineNodes _ _ [] = []
greedyOfflineNodes inst conf (nd:nds) =
  let nds' = greedyOfflineNodes inst conf nds
  in if canOffline inst (nd:nds') conf then nd:nds' else nds'

-- | From a specification, name, and factor create an instance that uses that
-- factor times the specification, rounded down.
instanceFromSpecAndFactor :: String -> Double -> ISpec -> Instance.Instance
instanceFromSpecAndFactor name f spec =
  Instance.create name
    (floor (f * fromIntegral (iSpecMemorySize spec)))
    0 []
    (floor (f * fromIntegral (iSpecCpuCount spec)))
    Running [] False Node.noSecondary Node.noSecondary DTExt
    (floor (f * fromIntegral (iSpecSpindleUse spec)))
    []

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ exitErr "This program doesn't take any arguments."

  let verbose = optVerbose opts
      targetf = optTargetResources opts

  ini_cdata@(ClusterData _ nlf ilf _ ipol) <- loadExternalData opts

  maybeSaveData (optSaveCluster opts) "original" "before hsqueeze run" ini_cdata

  let offlineCandidates = 
        sortBy (flip compare `on` length . Node.pList)
        . filter (foldl (liftA2 (&&)) (const True)
                  [ not . Node.offline
                  , not . Node.isMaster
                  , onlyExternal (nlf, ilf)
                  ])
        . IntMap.elems $ nlf
      conf = (nlf, ilf)
      std = iPolicyStdSpec ipol
      targetInstance = instanceFromSpecAndFactor "targetInstance" targetf std
      toOffline = greedyOfflineNodes targetInstance conf offlineCandidates
      (fin_nl, fin_il) = offlineNodes (map Node.idx toOffline) conf
      final_cdata = ini_cdata { cdNodes = fin_nl, cdInstances = fin_il }

  when (verbose > 1) . putStrLn 
    $ "Offline candidates: " ++ commaJoin (map Node.name offlineCandidates)

  unless (optNoHeaders opts) $
    putStrLn "'Nodes to offline'"

  mapM_ (putStrLn . Node.name) toOffline

  maybeSaveData (optSaveCluster opts)
    "squeezed" "after hsqueeze run" final_cdata

  

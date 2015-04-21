{-| Node freeing scheduler

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.HTools.Program.Hsqueeze
  (main
  , options
  , arguments
  ) where

import Control.Applicative
import Control.Lens (over)
import Control.Monad
import Data.Function
import Data.List
import Data.Maybe
import qualified Data.IntMap as IntMap
import Text.Printf (printf)

import Ganeti.BasicTypes
import Ganeti.Common
import qualified Ganeti.HTools.AlgorithmParams as Alg
import Ganeti.HTools.CLI
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Cluster.Metrics as Metrics
import Ganeti.HTools.ExtLoader
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Loader
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Tags (hasStandbyTag)
import Ganeti.HTools.Tags.Constants (standbyAuto)
import Ganeti.HTools.Types
import Ganeti.JQueue (currentTimestamp, reasonTrailTimestamp)
import Ganeti.JQueue.Objects (Timestamp)
import qualified Ganeti.Jobs as Jobs
import Ganeti.OpCodes
import Ganeti.OpCodes.Lens (metaParamsL, opReasonL)
import Ganeti.Utils

import Ganeti.Version (version)

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ luxi
    , oDataFile
    , oExecJobs
    , oMinResources
    , oTargetResources
    , oSaveCluster
    , oPrintCommands
    , oVerbose
    , oNoHeaders
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Wraps an 'OpCode' in a 'MetaOpCode' while also adding a comment
-- about what generated the opcode.
annotateOpCode :: Timestamp -> String -> Jobs.Annotator
annotateOpCode ts comment =
  over (metaParamsL . opReasonL)
      (++ [("hsqueeze"
           , "hsqueeze " ++ version ++ " called"
           , reasonTrailTimestamp ts
           )])
  . setOpComment (comment ++ " " ++ version)
  . wrapOpCode

-- | Within a cluster configuration, decide if the node hosts only
-- externally-mirrored instances.
onlyExternal ::  (Node.List, Instance.List) -> Node.Node -> Bool
onlyExternal (_, il) nd =
  not
  . any (Instance.usesLocalStorage . flip Container.find il)
  $ Node.pList nd

-- | Predicate of not being secondary node for any instance
noSecondaries :: Node.Node -> Bool
noSecondaries = null . Node.sList

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
balance :: (Node.List, Instance.List) 
           -> ((Node.List, Instance.List), [MoveJob])
balance (nl, il) =
  let ini_cv = Metrics.compCV nl
      ini_tbl = Cluster.Table nl il ini_cv []
      balanceStep = Cluster.tryBalance
                      (Alg.defaultOptions { Alg.algMinGain = 0.0
                                          , Alg.algMinGainLimit = 0.0})
      bTables = map fromJust . takeWhile isJust
                  $ iterate (>>= balanceStep) (Just ini_tbl)
      (Cluster.Table nl' il' _ _) = last bTables
      moves = zip bTables (drop 1 bTables) >>= Cluster.getMoves
  in ((nl', il'), reverse moves)

-- | In a configuration, mark a node as online or offline.
onlineOfflineNode :: Bool -> (Node.List, Instance.List) -> Ndx ->
                     (Node.List, Instance.List)
onlineOfflineNode offline (nl, il) ndx =
  let nd = Container.find ndx nl
      nd' = Node.setOffline nd offline
      nl' = Container.add ndx nd' nl
  in (nl', il)

-- | Offline or online a list nodes, and return the state after a balancing
-- attempt together with the sequence of moves that lead there.
onlineOfflineNodes :: Bool -> [Ndx] -> (Node.List, Instance.List)
                      -> ((Node.List, Instance.List), [MoveJob])
onlineOfflineNodes offline ndxs conf =
  let conf' = foldl (onlineOfflineNode offline) conf ndxs
  in balance conf'

-- | Offline a list of nodes, and return the state after balancing with
-- the sequence of moves that lead there.
offlineNodes :: [Ndx] -> (Node.List, Instance.List)
                -> ((Node.List, Instance.List), [MoveJob])
offlineNodes = onlineOfflineNodes True

-- | Online a list of nodes, and return the state after balancing with
-- the sequence of moves that lead there.
onlineNodes :: [Ndx] -> (Node.List, Instance.List)
               -> ((Node.List, Instance.List), [MoveJob])
onlineNodes = onlineOfflineNodes False

-- | Predicate on whether a list of nodes can be offlined or onlined
-- simultaneously in a given configuration, while still leaving enough
-- capacity on every node for the given instance.
canOnlineOffline :: Bool -> Instance.Instance -> (Node.List, Instance.List)
                    -> [Node.Node] ->Bool
canOnlineOffline offline inst conf nds = 
  let conf' = fst $ onlineOfflineNodes offline (map Node.idx nds) conf
  in allInstancesOnOnlineNodes conf' && allNodesCapacityFor inst conf'

-- | Predicate on whether a list of nodes can be offlined simultaneously.
canOffline :: Instance.Instance -> (Node.List, Instance.List) ->
              [Node.Node] -> Bool
canOffline = canOnlineOffline True

-- | Predicate on whether onlining a list of nodes suffices to get enough
-- free resources for given instance.
sufficesOnline :: Instance.Instance -> (Node.List, Instance.List)
                  -> [Node.Node] ->  Bool
sufficesOnline = canOnlineOffline False

-- | Greedily offline the nodes, starting from the last element, and return
-- the list of nodes that could simultaneously be offlined, while keeping
-- the resources specified by an instance.
greedyOfflineNodes :: Instance.Instance -> (Node.List, Instance.List) 
                      -> [Node.Node] -> [Node.Node]
greedyOfflineNodes _ _ [] = []
greedyOfflineNodes inst conf (nd:nds) =
  let nds' = greedyOfflineNodes inst conf nds
  in if canOffline inst conf (nd:nds') then nd:nds' else nds'

-- | Try to provide enough resources by onlining an initial segment of
-- a list of nodes. Return Nothing, if even onlining all of them is not
-- enough.
tryOnline :: Instance.Instance -> (Node.List, Instance.List) -> [Node.Node]
             -> Maybe [Node.Node]
tryOnline inst conf = listToMaybe . filter (sufficesOnline inst conf) . inits

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
    False

-- | Get opcodes for the given move job.
getMoveOpCodes :: Node.List
               -> Instance.List
               -> [JobSet]
               -> Result [([[OpCode]], String)]
getMoveOpCodes nl il js = return $ zip (map opcodes js) (map descr js)
  where opcodes = map (\(_, idx, move, _) ->
                      Cluster.iMoveToJob nl il idx move)
        descr job = "Moving instances " ++ commaJoin
                       (map (\(_, idx, _, _) -> Container.nameOf il idx) job)

-- | Get opcodes for tagging nodes with standby.
getTagOpCodes ::  [Node.Node] -> Result [([[OpCode]], String)]
getTagOpCodes nl = return $ zip (map opCode nl) (map descr nl)
  where
    opCode node = [[Node.genAddTagsOpCode node [standbyAuto]]]
    descr node = "Tagging node " ++ Node.name node ++ " with standby"

-- | Get opcodes for powering off nodes
getPowerOffOpCodes :: [Node.Node] -> Result [([[OpCode]], String)]
getPowerOffOpCodes nl = do
  opcodes <- Node.genPowerOffOpCodes nl
  return [([opcodes], "Powering off nodes")]

-- | Get opcodes for powering on nodes
getPowerOnOpCodes :: [Node.Node] -> Result [([[OpCode]], String)]
getPowerOnOpCodes nl = do
  opcodes <- Node.genPowerOnOpCodes nl
  return [([opcodes], "Powering on nodes")]

maybeExecJobs :: Options
              -> String
              -> Result [([[OpCode]], String)]
              -> IO (Result ())
maybeExecJobs opts comment opcodes =
  if optExecJobs opts
    then (case optLuxi opts of
            Nothing ->
              return $ Bad "Execution of commands possible only on LUXI"
            Just master -> do
              ts <- currentTimestamp
              let annotator = maybe id setOpPriority (optPriority opts) .
                              annotateOpCode ts comment
              case opcodes of
                Bad msg -> error msg
                Ok codes -> Jobs.execWithCancel annotator master codes)
    else return $ Ok ()

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ exitErr "This program doesn't take any arguments."

  let verbose = optVerbose opts
      targetf = optTargetResources opts
      minf = optMinResources opts

  ini_cdata@(ClusterData _ nlf ilf _ ipol) <- loadExternalData opts

  maybeSaveData (optSaveCluster opts) "original" "before hsqueeze run" ini_cdata

  let nodelist = IntMap.elems nlf
      offlineCandidates = 
        sortBy (flip compare `on` length . Node.pList)
        . filter (foldl (liftA2 (&&)) (const True)
                  [ not . Node.offline
                  , not . Node.isMaster
                  , noSecondaries
                  , onlyExternal (nlf, ilf)
                  ])
        $ nodelist
      onlineCandidates =
        filter (liftA2 (&&) Node.offline hasStandbyTag) nodelist
      conf = (nlf, ilf)
      std = iPolicyStdSpec ipol
      targetInstance = instanceFromSpecAndFactor "targetInstance" targetf std
      minInstance = instanceFromSpecAndFactor "targetInstance" minf std
      toOffline = greedyOfflineNodes targetInstance conf offlineCandidates
      ((fin_off_nl, fin_off_il), off_mvs) =
        offlineNodes (map Node.idx toOffline) conf
      final_off_cdata =
        ini_cdata { cdNodes = fin_off_nl, cdInstances = fin_off_il }
      off_jobs = Cluster.splitJobs off_mvs
      off_opcodes = liftM concat $ sequence
                    [ getMoveOpCodes nlf ilf off_jobs
                    , getTagOpCodes toOffline
                    , getPowerOffOpCodes toOffline
                    ]
      off_cmd =
        Cluster.formatCmds off_jobs
        ++ "\necho Tagging Commands\n"
        ++ (toOffline >>= (printf "  gnt-node add-tags %s %s\n"
                             `flip` standbyAuto)
                          . Node.alias)
        ++ "\necho Power Commands\n"
        ++ (toOffline >>= printf "  gnt-node power -f off %s\n" . Node.alias)
      toOnline = tryOnline minInstance conf onlineCandidates
      nodesToOnline = fromMaybe onlineCandidates toOnline
      ((fin_on_nl, fin_on_il), on_mvs) =
        onlineNodes (map Node.idx nodesToOnline) conf
      final_on_cdata =
        ini_cdata { cdNodes = fin_on_nl, cdInstances = fin_on_il }
      on_jobs = Cluster.splitJobs on_mvs
      on_opcodes = liftM2 (++) (getPowerOnOpCodes nodesToOnline)
                               (getMoveOpCodes nlf ilf on_jobs)
      on_cmd =
        "echo Power Commands\n"
        ++ (nodesToOnline >>= printf "  gnt-node power -f on %s\n" . Node.alias)
        ++ Cluster.formatCmds on_jobs

  when (verbose > 1) . putStrLn 
    $ "Offline candidates: " ++ commaJoin (map Node.name offlineCandidates)

  when (verbose > 1) . putStrLn
    $ "Online candidates: " ++ commaJoin (map Node.name onlineCandidates)

  if not (allNodesCapacityFor minInstance conf)
    then do
      unless (optNoHeaders opts) $
        putStrLn "'Nodes to online'"
      mapM_ (putStrLn . Node.name) nodesToOnline
      when (verbose > 1 && isNothing toOnline) . putStrLn $
        "Onlining all nodes will not yield enough capacity"
      maybeSaveCommands "Commands to run:" opts on_cmd
      let comment = printf "expanding by %d nodes" (length nodesToOnline)
      exitIfBad "hsqueeze" =<< maybeExecJobs opts comment on_opcodes
      maybeSaveData (optSaveCluster opts)
         "squeezed" "after hsqueeze expansion" final_on_cdata
    else
      if null toOffline
        then do      
          unless (optNoHeaders opts) $
            putStrLn "'No action'"
          maybeSaveCommands "Commands to run:" opts "echo Nothing to do"
          maybeSaveData (optSaveCluster opts)
            "squeezed" "after hsqueeze doing nothing" ini_cdata
        else do
          unless (optNoHeaders opts) $
            putStrLn "'Nodes to offline'"
          mapM_ (putStrLn . Node.name) toOffline
          maybeSaveCommands "Commands to run:" opts off_cmd
          let comment = printf "condensing by %d nodes" (length toOffline)
          exitIfBad "hsqueeze" =<< maybeExecJobs opts comment off_opcodes
          maybeSaveData (optSaveCluster opts)
            "squeezed" "after hsqueeze run" final_off_cdata

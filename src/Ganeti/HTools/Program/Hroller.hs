{-| Cluster rolling maintenance helper.

-}

{-

Copyright (C) 2012 Google Inc.
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

module Ganeti.HTools.Program.Hroller
  ( main
  , options
  , arguments
  ) where

import Control.Applicative
import Control.Arrow
import Control.Monad
import Data.Function
import Data.List
import Data.Ord
import Text.Printf

import qualified Data.IntMap as IntMap

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Group as Group

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.HTools.CLI
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Graph
import Ganeti.HTools.Loader
import Ganeti.HTools.Types
import Ganeti.Utils

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ luxi
    , oRapiMaster
    , oDataFile
    , oIAllocSrc
    , oOfflineNode
    , oOfflineMaintenance
    , oVerbose
    , oQuiet
    , oNoHeaders
    , oNodeTags
    , oSaveCluster
    , oGroup
    , oPrintMoves
    , oFullEvacuation
    , oSkipNonRedundant
    , oIgnoreNonRedundant
    , oForce
    , oOneStepOnly
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Compute the result of moving an instance to a different node.
move :: Idx -> Ndx -> (Node.List, Instance.List)
        -> OpResult (Node.List, Instance.List)
move idx new_ndx (nl, il) = do
  let new_node = Container.find new_ndx nl
      inst = Container.find idx il
      old_ndx = Instance.pNode inst
      old_node = Container.find old_ndx nl
  new_node' <- Node.addPriEx True new_node inst
  let old_node' = Node.removePri old_node inst
      inst' = Instance.setPri inst new_ndx
      nl' = Container.addTwo old_ndx old_node' new_ndx new_node' nl
      il' = Container.add idx inst' il
  return (nl', il')

-- | Move a non-redundant instance to one of the candidate nodes mentioned.
locateInstance :: Idx -> [Ndx] -> (Node.List, Instance.List)
                  -> Result (Node.List, Instance.List)
locateInstance idx ndxs conf =
  msum $ map (opToResult . flip (move idx) conf) ndxs

-- | Move a list of non-redundant instances to some of the nodes mentioned.
locateInstances :: [Idx] -> [Ndx] -> (Node.List, Instance.List)
                   -> Result (Node.List, Instance.List)
locateInstances idxs ndxs conf =
  foldM (\ cf idx -> locateInstance idx ndxs cf) conf idxs


-- | Greedily clear a node of a kind of instances by a given relocation method.
-- The arguments are a function providing the list of instances to be cleared,
-- the relocation function, the list of nodes to be cleared, a list of nodes
-- that can be relocated to, and the initial configuration. Returned is a list
-- of nodes that can be cleared simultaneously and the configuration after
-- clearing these nodes.
greedyClearNodes :: ((Node.List, Instance.List) -> Ndx -> [Idx])
                    -> ([Idx] -> [Ndx] -> (Node.List, Instance.List)
                        -> Result (Node.List, Instance.List))
                    -> [Ndx] -> [Ndx] -> (Node.List, Instance.List)
                    -> Result ([Ndx], (Node.List, Instance.List))
greedyClearNodes  _ _ [] _ conf = return ([], conf)
greedyClearNodes getInstances relocate (ndx:ndxs) targets conf@(nl, _) =
  withFirst `mplus` withoutFirst where
  withFirst = do
     let othernodes = delete ndx targets
         grp = Node.group $ Container.find ndx nl
         othernodesSameGroup =
           filter ((==) grp . Node.group . flip Container.find nl) othernodes
     conf' <- relocate (getInstances conf ndx) othernodesSameGroup conf
     (ndxs', conf'') <- greedyClearNodes getInstances relocate
                        ndxs othernodes conf'
     return (ndx:ndxs', conf'')
  withoutFirst = greedyClearNodes getInstances relocate ndxs targets conf
                    
-- | Greedily move the non-redundant instances away from a list of nodes.
-- Returns a list of ndoes that can be cleared simultaneously and the
-- configuration after clearing these nodes.
clearNodes :: [Ndx] -> [Ndx] -> (Node.List, Instance.List)
              -> Result ([Ndx], (Node.List, Instance.List))
clearNodes = greedyClearNodes nonRedundant locateInstances

-- | Partition nodes according to some clearing strategy.
-- Arguments are the clearing strategy, the list of nodes to be cleared,
-- the list of nodes that instances can be moved to, and the initial
-- configuration. Returned is a partion of the nodes to be cleared with the
-- configuration in that clearing situation.
partitionNodes :: ([Ndx] -> [Ndx] -> (Node.List, Instance.List)
                   -> Result ([Ndx], (Node.List, Instance.List)))
                  -> [Ndx] -> [Ndx] -> (Node.List, Instance.List)
                  -> Result [([Ndx], (Node.List, Instance.List))]
partitionNodes _ [] _  _ = return []
partitionNodes clear ndxs targets conf = do
  (grp, conf') <- clear ndxs targets conf
  guard . not . null $ grp
  let remaining = ndxs \\ grp
  part <- partitionNodes clear remaining targets conf
  return $ (grp, conf') : part

-- | Parition a list of nodes into chunks according cluster capacity.
partitionNonRedundant :: [Ndx] -> [Ndx] -> (Node.List, Instance.List)
                         -> Result [([Ndx], (Node.List, Instance.List))]
partitionNonRedundant = partitionNodes clearNodes

-- | Compute the result of migrating an instance.
migrate :: Idx -> (Node.List, Instance.List)
           -> OpResult (Node.List, Instance.List)
migrate idx (nl, il) = do
  let inst = Container.find idx il
      pdx = Instance.pNode inst
      sdx = Instance.sNode inst
      pNode = Container.find pdx nl
      sNode = Container.find sdx nl
      pNode' = Node.removePri pNode inst
      sNode' = Node.removeSec sNode inst
  sNode'' <- Node.addPriEx True sNode' inst
  pNode'' <- Node.addSecEx True pNode' inst sdx
  let inst' = Instance.setBoth inst sdx pdx
      nl' = Container.addTwo pdx pNode'' sdx sNode'' nl
      il' = Container.add idx inst' il
  return (nl', il')

-- | Obtain the list of primaries for a given node.
-- This restricts to those instances that have a secondary node.
primaries :: (Node.List, Instance.List) -> Ndx -> [Idx]
primaries (nl, il) = 
  filter (Instance.hasSecondary . flip Container.find  il) 
  . Node.pList . flip Container.find nl

-- | Migrate all instances of a given list of nodes.
-- The list of nodes is repeated as first argument in the result.
migrateOffNodes :: ([Ndx], (Node.List, Instance.List))
                   -> OpResult ([Ndx], (Node.List, Instance.List))
migrateOffNodes (ndxs, conf) = do
  let instances = ndxs >>= primaries conf
  conf' <- foldM (flip migrate) conf instances
  return (ndxs, conf')

-- | Compute the result of replacing the secondary node of an instance.
replaceSecondary :: Idx -> Ndx -> (Node.List, Instance.List)
        -> OpResult (Node.List, Instance.List)
replaceSecondary idx new_ndx (nl, il) = do
  let  new_secondary = Container.find new_ndx nl
       inst = Container.find idx il
       old_ndx = Instance.sNode inst
       pdx = Instance.pNode inst
       old_secondary = Container.find pdx nl
  if pdx == new_ndx then Bad FailInternal else Ok ()
  new_secondary' <- Node.addSecEx True new_secondary inst pdx
  let old_secondary' = Node.removeSec old_secondary inst
      inst' = Instance.setSec inst new_ndx
      nl' = Container.addTwo old_ndx old_secondary' new_ndx new_secondary' nl
      il' = Container.add idx inst' il
  return (nl', il')

-- | Find a suitable secondary node for the given instance from a list of nodes.
findSecondary :: Idx -> [Ndx] -> (Node.List, Instance.List)
                 -> Result (Node.List, Instance.List)
findSecondary idx ndxs conf =
  msum $ map (opToResult . flip (replaceSecondary idx) conf) ndxs

-- | Find suitable secondary nodes from the given nodes for a list of instances.
findSecondaries :: [Idx] -> [Ndx] -> (Node.List, Instance.List) 
                   -> Result (Node.List, Instance.List)
findSecondaries idxs ndxs conf =
  foldM (\ cf idx -> findSecondary idx ndxs cf) conf idxs

-- | Obtain the list of secondaries for a given node.
secondaries :: (Node.List, Instance.List) -> Ndx -> [Idx]
secondaries (nl, _) = Node.sList . flip Container.find nl

-- | Greedily move secondaries away from a list of nodes.
-- Returns a list of nodes that can be cleared simultaneously, 
-- and the configuration after these nodes are cleared.
clearSecondaries :: [Ndx] -> [Ndx] -> (Node.List, Instance.List)
                    -> Result ([Ndx], (Node.List, Instance.List))
clearSecondaries = greedyClearNodes secondaries findSecondaries

-- | Partition a list of nodes into chunks according to the ability to find
-- suitable replacement secondary nodes.
partitionSecondaries :: [Ndx] -> [Ndx] -> (Node.List, Instance.List)
                        -> Result [([Ndx], (Node.List, Instance.List))]
partitionSecondaries = partitionNodes clearSecondaries

-- | Gather statistics for the coloring algorithms.
-- Returns a string with a summary on how each algorithm has performed,
-- in order of non-decreasing effectiveness, and whether it tied or lost
-- with the previous one.
getStats :: [(String, ColorVertMap)] -> String
getStats colorings = snd . foldr helper (0,"") $ algBySize colorings
    where algostat (algo, cmap) = algo ++ ": " ++ size cmap ++ grpsizes cmap
          size cmap = show (IntMap.size cmap) ++ " "
          grpsizes cmap =
            "(" ++ commaJoin (map (show.length) (IntMap.elems cmap)) ++ ")"
          algBySize = sortBy (flip (comparing (IntMap.size.snd)))
          helper :: (String, ColorVertMap) -> (Int, String) -> (Int, String)
          helper el (0, _) = ((IntMap.size.snd) el, algostat el)
          helper el (old, str)
            | old == elsize = (elsize, str ++ " TIE " ++ algostat el)
            | otherwise = (elsize, str ++ " LOOSE " ++ algostat el)
              where elsize = (IntMap.size.snd) el

-- | Predicate of belonging to a given group restriction.
hasGroup :: Maybe Group.Group -> Node.Node -> Bool
hasGroup Nothing _ = True
hasGroup (Just grp) node = Node.group node == Group.idx grp

-- | Predicate of having at least one tag in a given set.
hasTag :: Maybe [String] -> Node.Node -> Bool
hasTag Nothing _ = True
hasTag (Just tags) node = not . null $ Node.nTags node `intersect` tags

-- | From a cluster configuration, get the list of non-redundant instances
-- of a node.
nonRedundant :: (Node.List, Instance.List) -> Ndx -> [Idx]
nonRedundant (nl, il) ndx =
  filter (not . Instance.hasSecondary . flip Container.find  il) $
  Node.pList (Container.find ndx nl)

-- | Within a cluster configuration, decide if the node hosts non-redundant
-- Instances.
noNonRedundant :: (Node.List, Instance.List) -> Node.Node -> Bool
noNonRedundant conf = null . nonRedundant conf . Node.idx

-- | Put the master node last.
-- Reorder a list groups of nodes (with additional information) such that the
-- master node (if present) is the last node of the last group.
masterLast :: [([Node.Node], a)] -> [([Node.Node], a)]
masterLast rebootgroups =
  map (first $ uncurry (++)) . uncurry (++) . partition (null . snd . fst) $
  map (first $ partition (not . Node.isMaster)) rebootgroups

-- | From two configurations compute the list of moved instances.
-- Do not show instances where only primary and secondary switched their
-- role, as here the instance is not moved in a proper sense.
getMoves :: (Node.List, Instance.List) -> (Node.List, Instance.List)
            -> [(Instance.Instance, (Node.Node, Maybe Node.Node))]
getMoves (_, il) (nl', il') = do
  ix <- Container.keys il
  let inst = Container.find ix il
      inst' = Container.find ix il'
      hasSec = Instance.hasSecondary inst
  guard $ Instance.pNode inst /= Instance.pNode inst'
          || (hasSec && Instance.sNode inst /= Instance.sNode inst')
  guard . not $ Instance.pNode inst' == Instance.sNode inst
                && Instance.sNode inst' == Instance.pNode inst
  return (inst', (Container.find (Instance.pNode inst') nl', 
                  if hasSec
                     then Just $ Container.find (Instance.sNode inst') nl'
                     else Nothing))

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $ exitErr "This program doesn't take any arguments."

  let verbose = optVerbose opts
      maybeExit = if optForce opts then warn else exitErr

  -- Load cluster data. The last two arguments, cluster tags and ipolicy, are
  -- currently not used by this tool.
  ini_cdata@(ClusterData gl fixed_nl ilf _ _) <- loadExternalData opts

  let master_names = map Node.name . filter Node.isMaster . IntMap.elems $
                     fixed_nl
  case master_names of
    [] -> maybeExit "No master node found (maybe not supported by backend)."
    [ _ ] -> return ()
    _ -> exitErr $ "Found more than one master node: " ++  show master_names

  nlf <- setNodeStatus opts fixed_nl

  maybeSaveData (optSaveCluster opts) "original" "before hroller run" ini_cdata

  -- Find the wanted node group, if any.
  wantedGroup <- case optGroup opts of
    Nothing -> return Nothing
    Just name -> case Container.findByName gl name of
      Nothing -> exitErr "Cannot find target group."
      Just grp -> return (Just grp)

  let nodes = IntMap.filter (foldl (liftA2 (&&)) (const True)
                             [ not . Node.offline
                             , if optSkipNonRedundant opts
                                  then noNonRedundant (nlf, ilf)
                                  else const True
                             , hasTag $ optNodeTags opts
                             , hasGroup wantedGroup ])
              nlf
      mkGraph = if optOfflineMaintenance opts
                   then Node.mkNodeGraph
                   else Node.mkRebootNodeGraph nlf

  nodeGraph <- case mkGraph nodes ilf of
                     Nothing -> exitErr "Cannot create node graph"
                     Just g -> return g

  when (verbose > 2) . putStrLn $ "Node Graph: " ++ show nodeGraph

  let colorAlgorithms = [ ("LF", colorLF)
                        , ("Dsatur", colorDsatur)
                        , ("Dcolor", colorDcolor)
                        ]
      colorings = map (\(v,a) -> (v,(colorVertMap.a) nodeGraph)) colorAlgorithms
      smallestColoring = IntMap.elems $
        (snd . minimumBy (comparing (IntMap.size . snd))) colorings
      allNdx = map Node.idx . filter (not . Node.offline) . Container.elems
               $ nlf
      splitted = mapM (\ grp -> partitionNonRedundant grp allNdx (nlf,ilf))
                 smallestColoring
  rebootGroups <- if optIgnoreNonRedundant opts
                     then return $ zip smallestColoring (repeat (nlf, ilf))
                     else case splitted of
                            Ok splitgroups -> return $ concat splitgroups
                            Bad _ -> exitErr "Not enough capacity to move\ 
                                             \ non-redundant instances"
  
  let migrated = mapM migrateOffNodes rebootGroups
  rebootGroups' <- if not . optFullEvacuation $ opts
                      then return rebootGroups
                      else case migrated of
                             Ok migratedGroup -> return migratedGroup
                             Bad _ -> exitErr "Failed to migrate instances\ 
                                              \ off nodes"
  let splitted' = mapM (\(grp, conf) -> partitionSecondaries grp allNdx conf)
                  rebootGroups'
  rebootGroups'' <- if optFullEvacuation opts
                      then case splitted' of
                             Ok splitgroups -> return $ concat splitgroups
                             Bad _ -> exitErr "Not enough capacity to move\
                                              \ secondaries"
                      else return rebootGroups'
  let idToNode = (`Container.find` nodes)
      nodesRebootGroups = map (first $ map idToNode
                                       . filter (`IntMap.member` nodes))
                          rebootGroups''
      outputRebootGroups = masterLast .
                           sortBy (flip compare `on` length . fst) $
                           nodesRebootGroups
      confToMoveNames =
        map (Instance.name *** (Node.name *** (=<<) (return . Node.name)))
        . getMoves (nlf, ilf)
      namesAndMoves = map (map Node.name *** confToMoveNames) outputRebootGroups

  when (verbose > 1) . putStrLn $ getStats colorings

  let showGroup = if optOneStepOnly opts
                    then mapM_ putStrLn
                    else putStrLn . commaJoin
      showMoves :: [(String, (String, Maybe String))] -> IO ()
      showMoves = if optPrintMoves opts
                    then mapM_ $ putStrLn . \(a,(b,c)) ->
                                                maybe (printf "  %s %s" a b)
                                                      (printf "  %s %s %s" a b)
                                                      c
                    else const $ return ()
      showBoth = liftM2 (>>) (showGroup . fst) (showMoves . snd)


  if optOneStepOnly opts
     then do
       unless (optNoHeaders opts) $
              putStrLn "'First Reboot Group'"
       case namesAndMoves of
         [] -> return ()
         y : _ -> showBoth y
     else do
       unless (optNoHeaders opts) $
              putStrLn "'Node Reboot Groups'"
       mapM_ showBoth namesAndMoves

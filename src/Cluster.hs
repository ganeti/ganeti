{-| Implementation of cluster-wide logic.

This module holds all pure cluster-logic; I\/O related functionality
goes into the "Main" module.

-}

module Cluster
    (
     -- * Types
     NodeList
    , InstanceList
    , Placement
    , Solution(..)
    , Table(..)
    , Removal
    -- * Generic functions
    , totalResources
    -- * First phase functions
    , computeBadItems
    -- * Second phase functions
    , computeSolution
    , applySolution
    , printSolution
    , printNodes
    -- * Balacing functions
    , checkMove
    , compCV
    , printStats
    -- * Loading functions
    , loadData
    ) where

import Data.List
import Data.Maybe (isNothing, fromJust)
import Text.Printf (printf)
import Data.Function

import qualified Container
import qualified Instance
import qualified Node
import Utils

type NodeList = Container.Container Node.Node
type InstanceList = Container.Container Instance.Instance
type Score = Double

-- | The description of an instance placement.
type Placement = (Int, Int, Int)

{- | A cluster solution described as the solution delta and the list
of placements.

-}
data Solution = Solution Int [Placement]
                deriving (Eq, Ord, Show)

-- | Returns the delta of a solution or -1 for Nothing
solutionDelta :: Maybe Solution -> Int
solutionDelta sol = case sol of
                      Just (Solution d _) -> d
                      _ -> -1

-- | A removal set.
data Removal = Removal NodeList [Instance.Instance]

-- | An instance move definition
data IMove = Failover
           | ReplacePrimary Int
           | ReplaceSecondary Int
             deriving (Show)

-- | The complete state for the balancing solution
data Table = Table NodeList InstanceList Score [Placement]
             deriving (Show)

-- General functions

-- | Cap the removal list if needed.
capRemovals :: [a] -> Int -> [a]
capRemovals removals max_removals =
    if max_removals > 0 then
        take max_removals removals
    else
        removals

-- | Check if the given node list fails the N+1 check.
verifyN1Check :: [Node.Node] -> Bool
verifyN1Check nl = any Node.failN1 nl

-- | Verifies the N+1 status and return the affected nodes.
verifyN1 :: [Node.Node] -> [Node.Node]
verifyN1 nl = filter Node.failN1 nl

{-| Add an instance and return the new node and instance maps. -}
addInstance :: NodeList -> Instance.Instance ->
               Node.Node -> Node.Node -> Maybe NodeList
addInstance nl idata pri sec =
  let pdx = Node.idx pri
      sdx = Node.idx sec
  in do
      pnode <- Node.addPri pri idata
      snode <- Node.addSec sec idata pdx
      new_nl <- return $ Container.addTwo sdx snode
                         pdx pnode nl
      return new_nl

-- | Remove an instance and return the new node and instance maps.
removeInstance :: NodeList -> Instance.Instance -> NodeList
removeInstance nl idata =
  let pnode = Instance.pnode idata
      snode = Instance.snode idata
      pn = Container.find pnode nl
      sn = Container.find snode nl
      new_nl = Container.addTwo
               pnode (Node.removePri pn idata)
               snode (Node.removeSec sn idata) nl in
  new_nl

-- | Remove an instance and return the new node map.
removeInstances :: NodeList -> [Instance.Instance] -> NodeList
removeInstances = foldl' removeInstance

-- | Compute the total free disk and memory in the cluster.
totalResources :: Container.Container Node.Node -> (Int, Int)
totalResources nl =
    foldl'
    (\ (mem, disk) node -> (mem + (Node.f_mem node),
                            disk + (Node.f_disk node)))
    (0, 0) (Container.elems nl)

{- | Compute a new version of a cluster given a solution.

This is not used for computing the solutions, but for applying a
(known-good) solution to the original cluster for final display.

It first removes the relocated instances after which it places them on
their new nodes.

 -}
applySolution :: NodeList -> InstanceList -> [Placement] -> NodeList
applySolution nl il sol =
    let odxes = map (\ (a, b, c) -> (Container.find a il,
                                     Node.idx (Container.find b nl),
                                     Node.idx (Container.find c nl))
                    ) sol
        idxes = (\ (x, _, _) -> x) (unzip3 odxes)
        nc = removeInstances nl idxes
    in
      foldl' (\ nz (a, b, c) ->
                 let new_p = Container.find b nz
                     new_s = Container.find c nz in
                 fromJust (addInstance nz a new_p new_s)
           ) nc odxes


-- First phase functions

{- | Given a list 1,2,3..n build a list of pairs [(1, [2..n]), (2,
    [3..n]), ...]

-}
genParts :: [a] -> Int -> [(a, [a])]
genParts l count =
    case l of
      [] -> []
      x:xs ->
          if length l < count then
              []
          else
              (x, xs) : (genParts xs count)

-- | Generates combinations of count items from the names list.
genNames :: Int -> [b] -> [[b]]
genNames count1 names1 =
  let aux_fn count names current =
          case count of
            0 -> [current]
            _ ->
                concatMap
                (\ (x, xs) -> aux_fn (count - 1) xs (x:current))
                (genParts names count)
  in
    aux_fn count1 names1 []

{- | Computes the pair of bad nodes and instances.

The bad node list is computed via a simple 'verifyN1' check, and the
bad instance list is the list of primary and secondary instances of
those nodes.

-}
computeBadItems :: NodeList -> InstanceList ->
                   ([Node.Node], [Instance.Instance])
computeBadItems nl il =
  let bad_nodes = verifyN1 $ Container.elems nl
      bad_instances = map (\idx -> Container.find idx il) $
                      sort $ nub $ concat $
                      map (\ n -> (Node.slist n) ++ (Node.plist n)) bad_nodes
  in
    (bad_nodes, bad_instances)


{- | Checks if removal of instances results in N+1 pass.

Note: the check removal cannot optimize by scanning only the affected
nodes, since the cluster is known to be not healthy; only the check
placement can make this shortcut.

-}
checkRemoval :: NodeList -> [Instance.Instance] -> Maybe Removal
checkRemoval nl victims =
  let nx = removeInstances nl victims
      failN1 = verifyN1Check (Container.elems nx)
  in
    if failN1 then
      Nothing
    else
      Just $ Removal nx victims


-- | Computes the removals list for a given depth
computeRemovals :: Cluster.NodeList
                 -> [Instance.Instance]
                 -> Int
                 -> [Maybe Cluster.Removal]
computeRemovals nl bad_instances depth =
    map (checkRemoval nl) $ genNames depth bad_instances

-- Second phase functions

-- | Single-node relocation cost
nodeDelta :: Int -> Int -> Int -> Int
nodeDelta i p s =
    if i == p || i == s then
        0
    else
        1

{-| Compute best solution.

    This function compares two solutions, choosing the minimum valid
    solution.
-}
compareSolutions :: Maybe Solution -> Maybe Solution -> Maybe Solution
compareSolutions a b = case (a, b) of
  (Nothing, x) -> x
  (x, Nothing) -> x
  (x, y) -> min x y

-- | Compute best table. Note that the ordering of the arguments is important.
compareTables :: Table -> Table -> Table
compareTables a@(Table _ _ a_cv _) b@(Table _ _ b_cv _ ) =
    if a_cv > b_cv then b else a

-- | Check if a given delta is worse then an existing solution.
tooHighDelta :: Maybe Solution -> Int -> Int -> Bool
tooHighDelta sol new_delta max_delta =
    if new_delta > max_delta && max_delta >=0 then
        True
    else
        case sol of
          Nothing -> False
          Just (Solution old_delta _) -> old_delta <= new_delta

{-| Check if placement of instances still keeps the cluster N+1 compliant.

    This is the workhorse of the allocation algorithm: given the
    current node and instance maps, the list of instances to be
    placed, and the current solution, this will return all possible
    solution by recursing until all target instances are placed.

-}
checkPlacement :: NodeList            -- ^ The current node list
               -> [Instance.Instance] -- ^ List of instances still to place
               -> [Placement]         -- ^ Partial solution until now
               -> Int                 -- ^ The delta of the partial solution
               -> Maybe Solution      -- ^ The previous solution
               -> Int                 -- ^ Abort if the we go above this delta
               -> Maybe Solution      -- ^ The new solution
checkPlacement nl victims current current_delta prev_sol max_delta =
  let target = head victims
      opdx = Instance.pnode target
      osdx = Instance.snode target
      vtail = tail victims
      have_tail = (length vtail) > 0
      nodes = Container.elems nl
  in
    foldl'
    (\ accu_p pri ->
         let
             pri_idx = Node.idx pri
             upri_delta = current_delta + nodeDelta pri_idx opdx osdx
             new_pri = Node.addPri pri target
             fail_delta1 = tooHighDelta accu_p upri_delta max_delta
         in
           if fail_delta1 || isNothing(new_pri) then accu_p
           else let pri_nl = Container.add pri_idx (fromJust new_pri) nl in
                foldl'
                (\ accu sec ->
                     let
                         sec_idx = Node.idx sec
                         upd_delta = upri_delta +
                                     nodeDelta sec_idx opdx osdx
                         fail_delta2 = tooHighDelta accu upd_delta max_delta
                         new_sec = Node.addSec sec target pri_idx
                     in
                       if sec_idx == pri_idx || fail_delta2 ||
                          isNothing new_sec then accu
                       else let
                           nx = Container.add sec_idx (fromJust new_sec) pri_nl
                           plc = (Instance.idx target, pri_idx, sec_idx)
                           c2 = plc:current
                           result =
                               if have_tail then
                                   checkPlacement nx vtail c2 upd_delta
                                                  accu max_delta
                               else
                                   Just (Solution upd_delta c2)
                      in compareSolutions accu result
                ) accu_p nodes
    ) prev_sol nodes

-- | Apply a move
applyMove :: NodeList -> Instance.Instance
          -> IMove -> (Maybe NodeList, Instance.Instance, Int, Int)
applyMove nl inst Failover =
    let old_pdx = Instance.pnode inst
        old_sdx = Instance.snode inst
        old_p = Container.find old_pdx nl
        old_s = Container.find old_sdx nl
        int_p = Node.removePri old_p inst
        int_s = Node.removeSec old_s inst
        new_p = Node.addPri int_s inst
        new_s = Node.addSec int_p inst old_sdx
        new_nl = if isNothing(new_p) || isNothing(new_s) then Nothing
                 else Just $ Container.addTwo old_pdx (fromJust new_s)
                      old_sdx (fromJust new_p) nl
    in (new_nl, Instance.setBoth inst old_sdx old_pdx, old_sdx, old_pdx)

applyMove nl inst (ReplacePrimary new_pdx) =
    let old_pdx = Instance.pnode inst
        old_sdx = Instance.snode inst
        old_p = Container.find old_pdx nl
        old_s = Container.find old_sdx nl
        tgt_n = Container.find new_pdx nl
        int_p = Node.removePri old_p inst
        int_s = Node.removeSec old_s inst
        new_p = Node.addPri tgt_n inst
        new_s = Node.addSec int_s inst new_pdx
        new_nl = if isNothing(new_p) || isNothing(new_s) then Nothing
                 else Just $ Container.add new_pdx (fromJust new_p) $
                      Container.addTwo old_pdx int_p
                               old_sdx (fromJust new_s) nl
    in (new_nl, Instance.setPri inst new_pdx, new_pdx, old_sdx)

applyMove nl inst (ReplaceSecondary new_sdx) =
    let old_pdx = Instance.pnode inst
        old_sdx = Instance.snode inst
        old_s = Container.find old_sdx nl
        tgt_n = Container.find new_sdx nl
        int_s = Node.removeSec old_s inst
        new_s = Node.addSec tgt_n inst old_pdx
        new_nl = if isNothing(new_s) then Nothing
                 else Just $ Container.addTwo new_sdx (fromJust new_s)
                      old_sdx int_s nl
    in (new_nl, Instance.setSec inst new_sdx, old_pdx, new_sdx)

checkSingleStep :: Table -- ^ The original table
                -> Instance.Instance -- ^ The instance to move
                -> Table -- ^ The current best table
                -> IMove -- ^ The move to apply
                -> Table -- ^ The final best table
checkSingleStep ini_tbl target cur_tbl move =
    let
        Table ini_nl ini_il _ ini_plc = ini_tbl
        (tmp_nl, new_inst, pri_idx, sec_idx) =
            applyMove ini_nl target move
    in
      if isNothing tmp_nl then cur_tbl
      else
          let tgt_idx = Instance.idx target
              upd_nl = fromJust tmp_nl
              upd_cvar = compCV upd_nl
              upd_il = Container.add tgt_idx new_inst ini_il
              tmp_plc = filter (\ (t, _, _) -> t /= tgt_idx) ini_plc
              upd_plc = (tgt_idx, pri_idx, sec_idx):tmp_plc
              upd_tbl = Table upd_nl upd_il upd_cvar upd_plc
          in
            compareTables cur_tbl upd_tbl

checkInstanceMove :: Table             -- original Table
                  -> Instance.Instance -- instance to move
                  -> Table             -- best new table for this instance
checkInstanceMove ini_tbl target =
    let
        Table ini_nl _ _ _ = ini_tbl
        opdx = Instance.pnode target
        osdx = Instance.snode target
        nodes = filter (\node -> let idx = Node.idx node
                                 in idx /= opdx && idx /= osdx)
                $ Container.elems ini_nl
        aft_failover = checkSingleStep ini_tbl target ini_tbl Failover
    in
      -- iterate over the possible nodes for this instance
      foldl'
      (\ accu_p new_node ->
           let
               new_idx = Node.idx new_node
               pmoves = [ReplacePrimary new_idx,
                         ReplaceSecondary new_idx]
           in
             foldl' -- while doing both possible moves
             (checkSingleStep ini_tbl target) accu_p pmoves
      ) aft_failover nodes

-- | Compute the best next move.
checkMove :: Table            -- ^ The current solution
          -> [Instance.Instance] -- ^ List of instances still to move
          -> Table            -- ^ The new solution
checkMove ini_tbl victims =
    let Table _ _ _ ini_plc = ini_tbl
        -- iterate over all instances, computing the best move
        best_tbl = foldl'
                   (\ step_tbl elem -> compareTables step_tbl $
                                       checkInstanceMove ini_tbl elem)
                   ini_tbl victims
    in let
        Table _ _ _ best_plc = best_tbl
        (target, _, _) = head best_plc
        -- remove the last placed instance from the victims list, it will
        -- get another chance the next round
        vtail = filter (\inst -> Instance.idx inst /= target) victims
       in
         if length best_plc == length ini_plc then -- no advancement
             ini_tbl
         else
             if null vtail then best_tbl
             else checkMove best_tbl vtail


{- | Auxiliary function for solution computation.

We write this in an explicit recursive fashion in order to control
early-abort in case we have met the min delta. We can't use foldr
instead of explicit recursion since we need the accumulator for the
abort decision.

-}
advanceSolution :: [Maybe Removal] -- ^ The removal to process
                -> Int             -- ^ Minimum delta parameter
                -> Int             -- ^ Maximum delta parameter
                -> Maybe Solution  -- ^ Current best solution
                -> Maybe Solution  -- ^ New best solution
advanceSolution [] _ _ sol = sol
advanceSolution (Nothing:xs) m n sol = advanceSolution xs m n sol
advanceSolution ((Just (Removal nx removed)):xs) min_d max_d prev_sol =
    let new_sol = checkPlacement nx removed [] 0 prev_sol max_d
        new_delta = solutionDelta $! new_sol
    in
      if new_delta >= 0 && new_delta <= min_d then
          new_sol
      else
          advanceSolution xs min_d max_d new_sol

-- | Computes the placement solution.
solutionFromRemovals :: [Maybe Removal] -- ^ The list of (possible) removals
                     -> Int             -- ^ Minimum delta parameter
                     -> Int             -- ^ Maximum delta parameter
                     -> Maybe Solution  -- ^ The best solution found
solutionFromRemovals removals min_delta max_delta =
    advanceSolution removals min_delta max_delta Nothing

{- | Computes the solution at the given depth.

This is a wrapper over both computeRemovals and
solutionFromRemovals. In case we have no solution, we return Nothing.

-}
computeSolution :: NodeList        -- ^ The original node data
                -> [Instance.Instance] -- ^ The list of /bad/ instances
                -> Int             -- ^ The /depth/ of removals
                -> Int             -- ^ Maximum number of removals to process
                -> Int             -- ^ Minimum delta parameter
                -> Int             -- ^ Maximum delta parameter
                -> Maybe Solution  -- ^ The best solution found (or Nothing)
computeSolution nl bad_instances depth max_removals min_delta max_delta =
  let
      removals = computeRemovals nl bad_instances depth
      removals' = capRemovals removals max_removals
  in
    solutionFromRemovals removals' min_delta max_delta

-- Solution display functions (pure)

-- | Given the original and final nodes, computes the relocation description.
computeMoves :: String -- ^ The instance name
             -> String -- ^ Original primary
             -> String -- ^ Original secondary
             -> String -- ^ New primary
             -> String -- ^ New secondary
             -> (String, [String])
                -- ^ Tuple of moves and commands list; moves is containing
                -- either @/f/@ for failover or @/r:name/@ for replace
                -- secondary, while the command list holds gnt-instance
                -- commands (without that prefix), e.g \"@failover instance1@\"
computeMoves i a b c d =
    if c == a then {- Same primary -}
        if d == b then {- Same sec??! -}
            ("-", [])
        else {- Change of secondary -}
            (printf "r:%s" d,
             [printf "replace-disks -n %s %s" d i])
    else
        if c == b then {- Failover and ... -}
            if d == a then {- that's all -}
                ("f", [printf "failover %s" i])
            else
                (printf "f r:%s" d,
                 [printf "failover %s" i,
                  printf "replace-disks -n %s %s" d i])
        else
            if d == a then {- ... and keep primary as secondary -}
                (printf "r:%s f" c,
                 [printf "replace-disks -n %s %s" c i,
                  printf "failover %s" i])
            else
                if d == b then {- ... keep same secondary -}
                    (printf "f r:%s f" c,
                     [printf "failover %s" i,
                      printf "replace-disks -n %s %s" c i,
                      printf "failover %s" i])

                else {- Nothing in common -}
                    (printf "r:%s f r:%s" c d,
                     [printf "replace-disks -n %s %s" c i,
                      printf "failover %s" i,
                      printf "replace-disks -n %s %s" d i])

{-| Converts a solution to string format -}
printSolution :: InstanceList
              -> [(Int, String)]
              -> [(Int, String)]
              -> [Placement]
              -> ([String], [[String]])
printSolution il ktn kti sol =
  unzip $ map
    (\ (i, p, s) ->
       let inst = Container.find i il
           inam = fromJust $ lookup (Instance.idx inst) kti
           npri = fromJust $ lookup p ktn
           nsec = fromJust $ lookup s ktn
           opri = fromJust $ lookup (Instance.pnode inst) ktn
           osec = fromJust $ lookup (Instance.snode inst) ktn
           (moves, cmds) =  computeMoves inam opri osec npri nsec

       in
         (printf "  I: %s\to: %s+>%s\tn: %s+>%s\ta: %s"
                 inam opri osec npri nsec moves,
          cmds)
    ) sol

-- | Print the node list.
printNodes :: [(Int, String)] -> NodeList -> String
printNodes ktn nl =
    let snl = sortBy (compare `on` Node.idx) (Container.elems nl)
        snl' = map (\ n -> ((fromJust $ lookup (Node.idx n) ktn), n)) snl
    in unlines $ map (uncurry Node.list) snl'

-- | Compute the mem and disk covariance.
compDetailedCV :: NodeList -> (Double, Double)
compDetailedCV nl =
    let nstats = map Node.normUsed $ Container.elems nl
        (mem_l, dsk_l) = unzip nstats
        mem_cv = varianceCoeff mem_l
        dsk_cv = varianceCoeff dsk_l
    in (mem_cv, dsk_cv)

-- | Compute the 'total' variance.
compCV :: NodeList -> Double
compCV nl =
    let (mem_cv, dsk_cv) = compDetailedCV nl
    in mem_cv + dsk_cv

printStats :: NodeList -> String
printStats nl =
    let (mem_cv, dsk_cv) = compDetailedCV nl
    in printf "mem=%.8f, dsk=%.8f" mem_cv dsk_cv

-- Balancing functions

-- Loading functions

{- | Convert newline and delimiter-separated text.

This function converts a text in tabular format as generated by
@gnt-instance list@ and @gnt-node list@ to a list of objects using a
supplied conversion function.

-}
loadTabular :: String -> ([String] -> (String, a))
            -> (a -> Int -> a) -> ([(String, Int)], [(Int, a)])
loadTabular text_data convert_fn set_fn =
    let lines_data = lines text_data
        rows = map (sepSplit '|') lines_data
        kerows = (map convert_fn rows)
        idxrows = map (\ (idx, (k, v)) -> ((k, idx), (idx, set_fn v idx)))
                  (zip [0..] kerows)
    in unzip idxrows

-- | For each instance, add its index to its primary and secondary nodes
fixNodes :: [(Int, Node.Node)]
         -> [(Int, Instance.Instance)]
         -> [(Int, Node.Node)]
fixNodes nl il =
    foldl' (\accu (idx, inst) ->
                let
                    assocEqual = (\ (i, _) (j, _) -> i == j)
                    pdx = Instance.pnode inst
                    sdx = Instance.snode inst
                    pold = fromJust $ lookup pdx accu
                    sold = fromJust $ lookup sdx accu
                    pnew = Node.setPri pold idx
                    snew = Node.setSec sold idx
                    ac1 = deleteBy assocEqual (pdx, pold) accu
                    ac2 = deleteBy assocEqual (sdx, sold) ac1
                    ac3 = (pdx, pnew):(sdx, snew):ac2
                in ac3) nl il


{-| Initializer function that loads the data from a node and list file
    and massages it into the correct format. -}
loadData :: String -- ^ Node data in text format
         -> String -- ^ Instance data in text format
         -> (Container.Container Node.Node,
             Container.Container Instance.Instance,
             [(Int, String)], [(Int, String)])
loadData ndata idata =
    let
    {- node file: name mem disk -}
        (ktn, nl) = loadTabular ndata
                    (\ (i:jt:jf:kt:kf:[]) -> (i, Node.create jt jf kt kf))
                    Node.setIdx
    {- instance file: name mem disk -}
        (kti, il) = loadTabular idata
                    (\ (i:j:k:l:m:[]) -> (i,
                                           Instance.create j k
                                               (fromJust $ lookup l ktn)
                                               (fromJust $ lookup m ktn)))
                    Instance.setIdx
        nl2 = fixNodes nl il
        il3 = Container.fromAssocList il
        nl3 = Container.fromAssocList
             (map (\ (k, v) -> (k, Node.buildPeers v il3 (length nl2))) nl2)
    in
      (nl3, il3, swapPairs ktn, swapPairs kti)

{-| Implementation of cluster-wide logic.

This module holds all pure cluster-logic; I\/O related functionality
goes into the "Main" module.

-}

module Ganeti.HTools.Cluster
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
    , printSolutionLine
    , formatCmds
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

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Utils

type NodeList = Container.Container Node.Node
type InstanceList = Container.Container Instance.Instance
type Score = Double

-- | The description of an instance placement.
type Placement = (Int, Int, Int, Score)

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
data IMove = Failover                -- ^ Failover the instance (f)
           | ReplacePrimary Int      -- ^ Replace primary (f, r:np, f)
           | ReplaceSecondary Int    -- ^ Replace secondary (r:ns)
           | ReplaceAndFailover Int  -- ^ Replace secondary, failover (r:np, f)
           | FailoverAndReplace Int  -- ^ Failover, replace secondary (f, r:ns)
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
    (\ (mem, dsk) node -> (mem + (Node.f_mem node),
                           dsk + (Node.f_dsk node)))
    (0, 0) (Container.elems nl)

{- | Compute a new version of a cluster given a solution.

This is not used for computing the solutions, but for applying a
(known-good) solution to the original cluster for final display.

It first removes the relocated instances after which it places them on
their new nodes.

 -}
applySolution :: NodeList -> InstanceList -> [Placement] -> NodeList
applySolution nl il sol =
    let odxes = map (\ (a, b, c, _) -> (Container.find a il,
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
computeRemovals :: NodeList
                 -> [Instance.Instance]
                 -> Int
                 -> [Maybe Removal]
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
      iidx = Instance.idx target
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
                           upd_cv = compCV nx
                           plc = (iidx, pri_idx, sec_idx, upd_cv)
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
-- Failover (f)
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

-- Replace the primary (f:, r:np, f)
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

-- Replace the secondary (r:ns)
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

-- Replace the secondary and failover (r:np, f)
applyMove nl inst (ReplaceAndFailover new_pdx) =
    let old_pdx = Instance.pnode inst
        old_sdx = Instance.snode inst
        old_p = Container.find old_pdx nl
        old_s = Container.find old_sdx nl
        tgt_n = Container.find new_pdx nl
        int_p = Node.removePri old_p inst
        int_s = Node.removeSec old_s inst
        new_p = Node.addPri tgt_n inst
        new_s = Node.addSec int_p inst new_pdx
        new_nl = if isNothing(new_p) || isNothing(new_s) then Nothing
                 else Just $ Container.add new_pdx (fromJust new_p) $
                      Container.addTwo old_pdx (fromJust new_s)
                               old_sdx int_s nl
    in (new_nl, Instance.setBoth inst new_pdx old_pdx, new_pdx, old_pdx)

-- Failver and replace the secondary (f, r:ns)
applyMove nl inst (FailoverAndReplace new_sdx) =
    let old_pdx = Instance.pnode inst
        old_sdx = Instance.snode inst
        old_p = Container.find old_pdx nl
        old_s = Container.find old_sdx nl
        tgt_n = Container.find new_sdx nl
        int_p = Node.removePri old_p inst
        int_s = Node.removeSec old_s inst
        new_p = Node.addPri int_s inst
        new_s = Node.addSec tgt_n inst old_sdx
        new_nl = if isNothing(new_p) || isNothing(new_s) then Nothing
                 else Just $ Container.add new_sdx (fromJust new_s) $
                      Container.addTwo old_sdx (fromJust new_p)
                               old_pdx int_p nl
    in (new_nl, Instance.setBoth inst old_sdx new_sdx, old_sdx, new_sdx)

checkSingleStep :: Table -- ^ The original table
                -> Instance.Instance -- ^ The instance to move
                -> Table -- ^ The current best table
                -> IMove -- ^ The move to apply
                -> Table -- ^ The final best table
checkSingleStep ini_tbl target cur_tbl move =
    let
        Table ini_nl ini_il _ ini_plc = ini_tbl
        (tmp_nl, new_inst, pri_idx, sec_idx) = applyMove ini_nl target move
    in
      if isNothing tmp_nl then cur_tbl
      else
          let tgt_idx = Instance.idx target
              upd_nl = fromJust tmp_nl
              upd_cvar = compCV upd_nl
              upd_il = Container.add tgt_idx new_inst ini_il
              upd_plc = (tgt_idx, pri_idx, sec_idx, upd_cvar):ini_plc
              upd_tbl = Table upd_nl upd_il upd_cvar upd_plc
          in
            compareTables cur_tbl upd_tbl

checkInstanceMove :: [Int]             -- Allowed target node indices
                  -> Table             -- Original table
                  -> Instance.Instance -- Instance to move
                  -> Table             -- Best new table for this instance
checkInstanceMove nodes_idx ini_tbl target =
    let
        opdx = Instance.pnode target
        osdx = Instance.snode target
        nodes = filter (\idx -> idx /= opdx && idx /= osdx) nodes_idx
        aft_failover = checkSingleStep ini_tbl target ini_tbl Failover
        all_moves = concatMap (\idx -> [ReplacePrimary idx,
                                        ReplaceSecondary idx,
                                        ReplaceAndFailover idx,
                                        FailoverAndReplace idx]) nodes
    in
      -- iterate over the possible nodes for this instance
      foldl' (checkSingleStep ini_tbl target) aft_failover all_moves

-- | Compute the best next move.
checkMove :: [Int]               -- ^ Allowed target node indices
          -> Table               -- ^ The current solution
          -> [Instance.Instance] -- ^ List of instances still to move
          -> Table               -- ^ The new solution
checkMove nodes_idx ini_tbl victims =
    let Table _ _ _ ini_plc = ini_tbl
        -- iterate over all instances, computing the best move
        best_tbl =
            foldl'
            (\ step_tbl elem -> compareTables step_tbl $
                                checkInstanceMove nodes_idx ini_tbl elem)
            ini_tbl victims
        Table _ _ _ best_plc = best_tbl
    in
      if length best_plc == length ini_plc then -- no advancement
          ini_tbl
      else
          best_tbl

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
                ("f", [printf "migrate %s" i])
            else
                (printf "f r:%s" d,
                 [printf "migrate %s" i,
                  printf "replace-disks -n %s %s" d i])
        else
            if d == a then {- ... and keep primary as secondary -}
                (printf "r:%s f" c,
                 [printf "replace-disks -n %s %s" c i,
                  printf "migrate %s" i])
            else
                if d == b then {- ... keep same secondary -}
                    (printf "f r:%s f" c,
                     [printf "migrate %s" i,
                      printf "replace-disks -n %s %s" c i,
                      printf "migrate %s" i])

                else {- Nothing in common -}
                    (printf "r:%s f r:%s" c d,
                     [printf "replace-disks -n %s %s" c i,
                      printf "migrate %s" i,
                      printf "replace-disks -n %s %s" d i])

{-| Converts a placement to string format -}
printSolutionLine :: InstanceList
              -> [(Int, String)]
              -> [(Int, String)]
              -> Int
              -> Int
              -> Placement
              -> Int
              -> (String, [String])
printSolutionLine il ktn kti nmlen imlen plc pos =
    let
        pmlen = (2*nmlen + 1)
        (i, p, s, c) = plc
        inst = Container.find i il
        inam = fromJust $ lookup (Instance.idx inst) kti
        npri = fromJust $ lookup p ktn
        nsec = fromJust $ lookup s ktn
        opri = fromJust $ lookup (Instance.pnode inst) ktn
        osec = fromJust $ lookup (Instance.snode inst) ktn
        (moves, cmds) =  computeMoves inam opri osec npri nsec
        ostr = (printf "%s:%s" opri osec)::String
        nstr = (printf "%s:%s" npri nsec)::String
    in
      (printf "  %3d. %-*s %-*s => %-*s %.8f a=%s"
       pos imlen inam pmlen ostr
       pmlen nstr c moves,
       cmds)

formatCmds :: [[String]] -> String
formatCmds cmd_strs =
    unlines $ map ("  echo " ++) $
    concat $ map (\(a, b) ->
        (printf "step %d" (a::Int)):(map ("gnt-instance " ++) b)) $
        zip [1..] cmd_strs

{-| Converts a solution to string format -}
printSolution :: InstanceList
              -> [(Int, String)]
              -> [(Int, String)]
              -> [Placement]
              -> ([String], [[String]])
printSolution il ktn kti sol =
    let
        mlen_fn = maximum . (map length) . snd . unzip
        imlen = mlen_fn kti
        nmlen = mlen_fn ktn
    in
      unzip $ map (uncurry $ printSolutionLine il ktn kti nmlen imlen) $
            zip sol [1..]

-- | Print the node list.
printNodes :: [(Int, String)] -> NodeList -> String
printNodes ktn nl =
    let snl = sortBy (compare `on` Node.idx) (Container.elems nl)
        snl' = map (\ n -> ((fromJust $ lookup (Node.idx n) ktn), n)) snl
        m_name = maximum . (map length) . fst . unzip $ snl'
        helper = Node.list m_name
        header = printf "%2s %-*s %5s %5s %5s %5s %5s %3s %3s %7s %7s"
                 "N1" m_name "Name" "t_mem" "f_mem" "r_mem"
                 "t_dsk" "f_dsk"
                 "pri" "sec" "p_fmem" "p_fdsk"
    in unlines $ (header:map (uncurry helper) snl')

-- | Compute the mem and disk covariance.
compDetailedCV :: NodeList -> (Double, Double, Double, Double)
compDetailedCV nl =
    let
        nodes = Container.elems nl
        mem_l = map Node.p_mem nodes
        dsk_l = map Node.p_dsk nodes
        mem_cv = varianceCoeff mem_l
        dsk_cv = varianceCoeff dsk_l
        n1_l = length $ filter Node.failN1 nodes
        n1_score = (fromIntegral n1_l) / (fromIntegral $ length nodes)
        res_l = map Node.p_rem nodes
        res_cv = varianceCoeff res_l
    in (mem_cv, dsk_cv, n1_score, res_cv)

-- | Compute the 'total' variance.
compCV :: NodeList -> Double
compCV nl =
    let (mem_cv, dsk_cv, n1_score, res_cv) = compDetailedCV nl
    in mem_cv + dsk_cv + n1_score + res_cv

printStats :: NodeList -> String
printStats nl =
    let (mem_cv, dsk_cv, n1_score, res_cv) = compDetailedCV nl
    in printf "f_mem=%.8f, r_mem=%.8f, f_dsk=%.8f, n1=%.3f"
       mem_cv res_cv dsk_cv n1_score

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

-- | Compute the longest common suffix of a [(Int, String)] list that
-- | starts with a dot
longestDomain :: [(Int, String)] -> String
longestDomain [] = ""
longestDomain ((_,x):xs) =
    let
        onlyStrings = snd $ unzip xs
    in
      foldr (\ suffix accu -> if all (isSuffixOf suffix) onlyStrings
                              then suffix
                              else accu)
      "" $ filter (isPrefixOf ".") (tails x)

-- | Remove tails from the (Int, String) lists
stripSuffix :: String -> [(Int, String)] -> [(Int, String)]
stripSuffix suffix lst =
    let sflen = length suffix in
    map (\ (key, name) -> (key, take ((length name) - sflen) name)) lst

{-| Initializer function that loads the data from a node and list file
    and massages it into the correct format. -}
loadData :: String -- ^ Node data in text format
         -> String -- ^ Instance data in text format
         -> (Container.Container Node.Node,
             Container.Container Instance.Instance,
             String, [(Int, String)], [(Int, String)])
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
        xtn = swapPairs ktn
        xti = swapPairs kti
        common_suffix = longestDomain (xti ++ xtn)
        stn = stripSuffix common_suffix xtn
        sti = stripSuffix common_suffix xti
    in
      (nl3, il3, common_suffix, stn, sti)

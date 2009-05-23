{-| Loading data from external sources

This module holds the common code for loading the cluster state from external sources.

-}

module Ganeti.HTools.Loader
    ( mergeData
    , checkData
    , assignIndices
    , lookupNode
    ) where

import Data.List
import Data.Maybe (fromJust)
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node

import Ganeti.HTools.Types


-- | Swap a list of @(a, b)@ into @(b, a)@
swapPairs :: [(a, b)] -> [(b, a)]
swapPairs = map (\ (a, b) -> (b, a))

-- | Lookups a node into an assoc list
lookupNode :: (Monad m) => NameAssoc -> String -> String -> m Int
lookupNode ktn inst node =
    case lookup node ktn of
      Nothing -> fail $ "Unknown node '" ++ node ++ "' for instance " ++ inst
      Just idx -> return idx

assignIndices :: (Element a) =>
                 [(String, a)]
              -> (NameAssoc, [(Int, a)])
assignIndices =
    unzip . map (\ (idx, (k, v)) -> ((k, idx), (idx, setIdx v idx)))
          . zip [0..]

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
                    pnew = Node.setPri pold idx
                    ac1 = deleteBy assocEqual (pdx, pold) accu
                    ac2 = (pdx, pnew):ac1
                in
                  if sdx /= Node.noSecondary then
                      let
                          sold = fromJust $ lookup sdx accu
                          snew = Node.setSec sold idx
                          ac3 = deleteBy assocEqual (sdx, sold) ac2
                          ac4 = (sdx, snew):ac3
                      in ac4
                  else
                      ac2
           ) nl il

-- | Compute the longest common suffix of a NameList list that
-- | starts with a dot
longestDomain :: NameList -> String
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
stripSuffix :: String -> NameList -> NameList
stripSuffix suffix lst =
    let sflen = length suffix in
    map (\ (key, name) -> (key, take ((length name) - sflen) name)) lst

{-| Initializer function that loads the data from a node and list file
    and massages it into the correct format. -}
mergeData :: ([(String, Int)], Node.AssocList,
              [(String, Int)], Instance.AssocList) -- ^ Data from either
                                                   -- Text.loadData
                                                   -- or Rapi.loadData
          -> Result (NodeList, InstanceList, String, NameList, NameList)
mergeData (ktn, nl, kti, il) = do
  let
      nl2 = fixNodes nl il
      il3 = Container.fromAssocList il
      nl3 = Container.fromAssocList
            (map (\ (k, v) -> (k, Node.buildPeers v il3 (length nl2))) nl2)
      xtn = swapPairs ktn
      xti = swapPairs kti
      common_suffix = longestDomain (xti ++ xtn)
      stn = stripSuffix common_suffix xtn
      sti = stripSuffix common_suffix xti
  return (nl3, il3, common_suffix, stn, sti)

-- | Check cluster data for consistency
checkData :: NodeList -> InstanceList -> NameList -> NameList
          -> ([String], NodeList)
checkData nl il ktn _ =
    Container.mapAccum
        (\ msgs node ->
             let nname = fromJust $ lookup (Node.idx node) ktn
                 nilst = map (flip Container.find $ il) (Node.plist node)
                 dilst = filter (not . Instance.running) nilst
                 adj_mem = sum . map Instance.mem $ dilst
                 delta_mem = (truncate $ Node.t_mem node)
                             - (Node.n_mem node)
                             - (Node.f_mem node)
                             - (nodeImem node il)
                             + adj_mem
                 delta_dsk = (truncate $ Node.t_dsk node)
                             - (Node.f_dsk node)
                             - (nodeIdsk node il)
                 newn = Node.setFmem (Node.setXmem node delta_mem)
                        (Node.f_mem node - adj_mem)
                 umsg1 = if delta_mem > 512 || delta_dsk > 1024
                         then [printf "node %s is missing %d MB ram \
                                     \and %d GB disk"
                                     nname delta_mem (delta_dsk `div` 1024)]
                         else []
             in (msgs ++ umsg1, newn)
        ) [] nl

-- | Compute the amount of memory used by primary instances on a node.
nodeImem :: Node.Node -> InstanceList -> Int
nodeImem node il =
    let rfind = flip Container.find $ il
    in sum . map Instance.mem .
       map rfind $ Node.plist node

-- | Compute the amount of disk used by instances on a node (either primary
-- or secondary).
nodeIdsk :: Node.Node -> InstanceList -> Int
nodeIdsk node il =
    let rfind = flip Container.find $ il
    in sum . map Instance.dsk .
       map rfind $ (Node.plist node) ++ (Node.slist node)

{-| Loading data from external sources

This module holds the common code for loading the cluster state from external sources.

-}

module Ganeti.HTools.Loader
    where

import Data.List
import Data.Maybe (isNothing, fromJust)

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

assignIndices :: (a -> Int -> a)
              -> [(String, a)]
              -> (NameAssoc, [(Int, a)])
assignIndices set_fn =
    unzip . map (\ (idx, (k, v)) -> ((k, idx), (idx, set_fn v idx)))
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

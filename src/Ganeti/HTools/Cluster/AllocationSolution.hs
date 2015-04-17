{-| Implementation of handling of Allocation Solutions

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013, 2015 Google Inc.
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

module Ganeti.HTools.Cluster.AllocationSolution
  ( GenericAllocElement
  , AllocElement
  , GenericAllocSolution(..)
  , AllocSolution
  , emptyAllocSolution
  , sumAllocs
  , concatAllocs
  , updateIl
  , extractNl
  , collapseFailures
  , genericAnnotateSolution
  , annotateSolution
  , solutionDescription
  , AllocSolutionCollection
  , emptyAllocCollection
  , concatAllocCollections
  , collectionToSolution
  ) where

import Data.Ord (comparing)
import Data.List (intercalate, foldl', sortBy)
import Data.Maybe (listToMaybe)
import Text.Printf (printf)

import Ganeti.BasicTypes (GenericResult(..), Result)
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Types as T

-- | A simple name for an allocation element (here just for logistic
-- reasons), generic in the type of the metric.
type GenericAllocElement a = (Node.List, Instance.Instance, [Node.Node], a)

-- | Obtain the metric of a GenericAllocElement.
allocMetric :: GenericAllocElement a -> a
allocMetric (_, _, _, a) = a

-- | A simple name for an allocation element (here just for logistic
-- reasons).
type AllocElement = GenericAllocElement T.Score

-- | Allocation\/relocation solution.
data GenericAllocSolution a = AllocSolution
  { asFailures :: [T.FailMode]            -- ^ Failure counts
  , asAllocs   :: Int                     -- ^ Good allocation count
  , asSolution :: Maybe (GenericAllocElement a) -- ^ The actual allocation
                                          -- result
  , asLog      :: [String]                -- ^ Informational messages
  }
type AllocSolution = GenericAllocSolution T.Score

-- | The empty solution we start with when computing allocations.
emptyAllocSolution :: GenericAllocSolution a
emptyAllocSolution = AllocSolution { asFailures = [], asAllocs = 0
                                   , asSolution = Nothing, asLog = [] }


-- | Calculate the new instance list after allocation solution.
updateIl :: Instance.List           -- ^ The original instance list
         -> Maybe (GenericAllocElement a) -- ^ The result of
                                          -- the allocation attempt
         -> Instance.List           -- ^ The updated instance list
updateIl il Nothing = il
updateIl il (Just (_, xi, _, _)) = Container.add (Container.size il) xi il

-- | Extract the the new node list from the allocation solution.
extractNl :: Node.List               -- ^ The original node list
          -> Instance.List           -- ^ The original instance list
          -> Maybe (GenericAllocElement a) -- ^ The result of the
                                           -- allocation attempt
          -> Node.List               -- ^ The new node list
extractNl nl _ Nothing = nl
extractNl _ il (Just (xnl, _, ns, _)) =
  let newIndex = Container.size il
      fixIndex = map (\i -> if i < 0 then newIndex else i)
      fixIndices nodes node =
        let nidx = Node.idx node
            n = Container.find nidx nodes
            n' = n { Node.pList = fixIndex $ Node.pList n
                   , Node.sList = fixIndex $ Node.sList n
                   }
        in Container.add nidx n' nodes
  in foldl fixIndices xnl ns

-- | Compares two Maybe AllocElement and chooses the best score.
bestAllocElement :: Ord a
                 => Maybe (GenericAllocElement a)
                 -> Maybe (GenericAllocElement a)
                 -> Maybe (GenericAllocElement a)
bestAllocElement a Nothing = a
bestAllocElement Nothing b = b
bestAllocElement a@(Just (_, _, _, ascore)) b@(Just (_, _, _, bscore)) =
  if ascore < bscore then a else b

-- | Update current Allocation solution and failure stats with new
-- elements.
concatAllocs :: Ord a
             => GenericAllocSolution a
             -> T.OpResult (GenericAllocElement a)
             -> GenericAllocSolution a
concatAllocs as (Bad reason) = as { asFailures = reason : asFailures as }

concatAllocs as (Ok ns) =
  let -- Choose the old or new solution, based on the cluster score
    cntok = asAllocs as
    osols = asSolution as
    nsols = bestAllocElement osols (Just ns)
    nsuc = cntok + 1
    -- Note: we force evaluation of nsols here in order to keep the
    -- memory profile low - we know that we will need nsols for sure
    -- in the next cycle, so we force evaluation of nsols, since the
    -- foldl' in the caller will only evaluate the tuple, but not the
    -- elements of the tuple
  in nsols `seq` nsuc `seq` as { asAllocs = nsuc, asSolution = nsols }

-- | Sums two 'AllocSolution' structures.
sumAllocs :: Ord a
          => GenericAllocSolution a
          -> GenericAllocSolution a
          -> GenericAllocSolution a
sumAllocs (AllocSolution aFails aAllocs aSols aLog)
          (AllocSolution bFails bAllocs bSols bLog) =
  -- note: we add b first, since usually it will be smaller; when
  -- fold'ing, a will grow and grow whereas b is the per-group
  -- result, hence smaller
  let nFails  = bFails ++ aFails
      nAllocs = aAllocs + bAllocs
      nSols   = bestAllocElement aSols bSols
      nLog    = bLog ++ aLog
  in AllocSolution nFails nAllocs nSols nLog

-- | Build failure stats out of a list of failures.
collapseFailures :: [T.FailMode] -> T.FailStats
collapseFailures flst =
    map (\k -> (k, foldl' (\a e -> if e == k then a + 1 else a) 0 flst))
            [minBound..maxBound]


-- | Given a solution, generates a reasonable description for it.
genericDescribeSolution :: (a -> String) -> GenericAllocSolution a -> String
genericDescribeSolution formatMetrics as =
  let fcnt = asFailures as
      sols = asSolution as
      freasons =
        intercalate ", " . map (\(a, b) -> printf "%s: %d" (show a) b) .
        filter ((> 0) . snd) . collapseFailures $ fcnt
  in case sols of
     Nothing -> "No valid allocation solutions, failure reasons: " ++
                (if null fcnt then "unknown reasons" else freasons)
     Just (_, _, nodes, cv) ->
         printf ("score: %s, successes %d, failures %d (%s)" ++
                 " for node(s) %s") (formatMetrics cv) (asAllocs as)
               (length fcnt) freasons
               (intercalate "/" . map Node.name $ nodes)

-- | Annotates a solution with the appropriate string.
genericAnnotateSolution :: (a -> String)
                        ->GenericAllocSolution a -> GenericAllocSolution a
genericAnnotateSolution formatMetrics as =
  as { asLog = genericDescribeSolution formatMetrics as : asLog as }

-- | Annotate a solution based on the standard metrics
annotateSolution :: AllocSolution -> AllocSolution
annotateSolution = genericAnnotateSolution (printf "%.8f")


-- | Given a group/result, describe it as a nice (list of) messages.
solutionDescription :: (Group.Group, Result (GenericAllocSolution a))
                    -> [String]
solutionDescription (grp, result) =
  case result of
    Ok solution -> map (printf "Group %s (%s): %s" gname pol) (asLog solution)
    Bad message -> [printf "Group %s: error %s" gname message]
  where gname = Group.name grp
        pol = T.allocPolicyToRaw (Group.allocPolicy grp)

-- * Collection of Allocation Solutions for later filtering

-- | Collection of Allocation Solution
data AllocSolutionCollection a = AllocSolutionCollection
  { ascFailures  :: [T.FailMode]            -- ^ Failure counts
  , ascAllocs    :: Int                     -- ^ Good allocation count
  , ascSolutions :: [GenericAllocElement a] -- ^ The actual allocation results
  , ascLog       :: [String]                -- ^ Informational messages
  }

-- | Empty collection of allocation solutions.
emptyAllocCollection :: AllocSolutionCollection a
emptyAllocCollection = AllocSolutionCollection
                         { ascFailures = []
                         , ascAllocs = 0
                         , ascSolutions = []
                         , ascLog = []
                         }

-- | Update current collection of solution and failure stats with new
-- elements.
concatAllocCollections :: Ord a
                       => AllocSolutionCollection a
                       -> T.OpResult (GenericAllocElement a)
                       -> AllocSolutionCollection a
concatAllocCollections asc (Bad reason) =
  asc { ascFailures = reason : ascFailures asc }

concatAllocCollections asc (Ok ns) =
  asc { ascAllocs = ascAllocs asc + 1, ascSolutions = ns : ascSolutions asc }

-- | From a collection of solutions collapse to a single one by chosing the best
-- that fulfills a given predicate.
collectionToSolution :: Ord a
                     => T.FailMode -- ^ Failure mode to assign to solutions
                                   -- filtered out in this step
                     -> (GenericAllocElement a -> Bool) -- ^ predicate
                                                        -- to restrict to
                     -> AllocSolutionCollection a
                     -> GenericAllocSolution a
collectionToSolution failmode isgood asc =
  let sols = sortBy (comparing allocMetric) $ ascSolutions asc
      (dropped, good) = break isgood sols
      dropcount = length dropped
      nsols = ascAllocs asc - dropcount
      failures = replicate dropcount failmode ++ ascFailures asc
      sol = listToMaybe good
  in AllocSolution { asFailures = failures
                   , asAllocs = nsols
                   , asSolution = sol
                   , asLog = ascLog asc
                   }

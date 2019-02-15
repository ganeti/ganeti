{-# LANGUAGE BangPatterns #-}


{-| Utility functions for statistical accumulation. -}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.Utils.Statistics
  ( Statistics
  , TagTagMap
  , AggregateComponent(..)
  , getSumStatistics
  , getStdDevStatistics
  , getMapStatistics
  , getStatisticValue
  , updateStatistics
  ) where

import qualified Data.Foldable as Foldable
import Data.List (foldl')
import qualified Data.Map as Map

-- | Type to store the number of instances for each exclusion and location
-- pair. This is necessary to calculate second component of location score.
type TagTagMap = Map.Map (String, String) Int

-- | Abstract type of statistical accumulations. They behave as if the given
-- statistics were computed on the list of values, but they allow a potentially
-- more efficient update of a given value.
data Statistics = SumStatistics Double
                | StdDevStatistics Double Double Double
                  -- count, sum, and not the sum of squares---instead the
                  -- computed variance for better precission.
                | MapStatistics TagTagMap deriving Show

-- | Abstract type of per-node statistics measures. The SimpleNumber is used
-- to construct SumStatistics and StdDevStatistics while SpreadValues is used
-- to construct MapStatistics.
data AggregateComponent = SimpleNumber Double
                        | SpreadValues TagTagMap
-- Each function below depends on the contents of AggregateComponent but it's
-- necessary to define each function as a function processing both
-- SimpleNumber and SpreadValues instances (see Metrics.hs). That's why
-- pattern matches for invalid type defined as functions which change nothing.

-- | Get a statistics that sums up the values.
getSumStatistics :: [AggregateComponent] -> Statistics
getSumStatistics xs =
  let addComponent s (SimpleNumber x) =
        let !s' = s + x
        in s'
      addComponent s _ = s
      st = foldl' addComponent 0 xs
  in SumStatistics st

-- | Get a statistics for the standard deviation.
getStdDevStatistics :: [AggregateComponent] -> Statistics
getStdDevStatistics xs =
  let addComponent (n, s) (SimpleNumber x) =
        let !n' = n + 1
            !s' = s + x
        in (n', s')
      addComponent (n, s) _ = (n, s)
      (nt, st) = foldl' addComponent (0, 0) xs
      mean = st / nt
      center (SimpleNumber x) = x - mean
      center _ = 0
      nvar = foldl' (\v x -> let d = center x in v + d * d) 0 xs
  in StdDevStatistics nt st (nvar / nt)

-- | Get a statistics for the standard deviation.
getMapStatistics :: [AggregateComponent] -> Statistics
getMapStatistics xs =
  let addComponent m (SpreadValues x) =
        let !m' = Map.unionWith (+) m x
        in m'
      addComponent m _ = m
      mt = foldl' addComponent Map.empty xs
  in MapStatistics mt

-- | Obtain the value of a statistics.
getStatisticValue :: Statistics -> Double
getStatisticValue (SumStatistics s) = s
getStatisticValue (StdDevStatistics _ _ var) = sqrt var
getStatisticValue (MapStatistics m) = fromIntegral $ Foldable.sum m - Map.size m
-- Function above calculates sum (N_i - 1) over each map entry.

-- | In a given statistics replace on value by another. This
-- will only give meaningful results, if the original value
-- was actually part of the statistics.
updateStatistics :: Statistics -> (AggregateComponent, AggregateComponent) ->
                    Statistics
updateStatistics (SumStatistics s) (SimpleNumber x, SimpleNumber y) =
  SumStatistics $ s + (y - x)
updateStatistics (StdDevStatistics n s var) (SimpleNumber x, SimpleNumber y) =
  let !ds = y - x
      !dss = y * y - x * x
      !dnnvar = (n * dss - 2 * s * ds) - ds * ds
      !s' = s + ds
      !var' = max 0 $ var + dnnvar / (n * n)
  in StdDevStatistics n s' var'
updateStatistics (MapStatistics m) (SpreadValues x, SpreadValues y) =
  let nm = Map.unionWith (+) (Map.unionWith (-) m x) y
  in MapStatistics nm
updateStatistics s _ = s

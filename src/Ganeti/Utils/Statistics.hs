{-# LANGUAGE BangPatterns, MultiParamTypeClasses, FunctionalDependencies#-}

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
  ( Stat
  , SumStat(..)
  , StdDevStat(..)
  , TagTagMap
  , MapData(..)
  , MapStat(..)
  , update
  , calculate
  , getValue
  , toDouble
  ) where

import qualified Data.Foldable as Foldable
import Data.List (foldl')
import qualified Data.Map as Map

import Ganeti.Utils (balancedSum)

-- | Typeclass describing necessary statistical accumulations functions. Types
-- defining an instance of Stat behave as if the given statistics were computed
-- on the list of values, but they allow a potentially more efficient update of
-- a given value. c is the statistical accumulation data type itself while s is
-- a type of spread values used to calculate a statistics. s defined as a
-- type dependent from c in order to pretend ambiguity.
class (Show c) => Stat s c | c -> s where
  -- | Calculate a statistics from the spread values list.
  calculate :: [s] -> c
  -- | In a given statistics replace on value by another. This will only give
  -- meaningful results, if the original value was actually part of
  -- the statistics.
  update :: c -> s -> s -> c
  -- | Obtain the value of a statistics.
  getValue :: c -> Double

-- | Type of statistical accumulations representing simple sum of values
data SumStat = SumStat Double deriving Show
-- | Type of statistical accumulations representing values standard deviation
data StdDevStat = StdDevStat Double Double Double deriving Show
                  -- count, sum, and not the sum of squares---instead the
                  -- computed variance for better precission.
-- | Type of statistical accumulations representing the amount of instances per
-- each tags pair. See Also TagTagMap documentation.
data MapStat = MapStat TagTagMap deriving Show

instance Stat Double SumStat where
  calculate xs =
    let !sx = balancedSum xs
    in SumStat sx
  update (SumStat s) x x' =
    let !sx' = s + (x' -x)
    in SumStat sx'
  getValue (SumStat s) = s

instance Stat Double StdDevStat where
  calculate xs =
    let !n = fromIntegral $ length xs
        !sx = balancedSum xs
        !mean = sx / n
        sqDist x = let d = x - mean in d * d
        !var = balancedSum (map sqDist xs) / n
    in StdDevStat n sx var
  update (StdDevStat n s var) x x' =
    let !ds = x' - x
        !dss = x' * x' - x * x
        !dnnvar = (n * dss - 2 * s * ds) - ds * ds
        !s' = s + ds
        !var' = max 0 $ var + dnnvar / (n * n)
    in StdDevStat n s' var'
  getValue (StdDevStat _ _ var) = sqrt var

-- | Type to store the number of instances for each exclusion and location
-- pair. This is necessary to calculate second component of location score.
type TagTagMap = Map.Map (String, String) Int

-- | Data type used to store spread values of type TagTagMap. This data type
-- is introduced only to defin an instance of Stat for TagTagMap.
data MapData = MapData TagTagMap

-- | Helper function unpacking [MapData] spread values list.
mapTmpToMap :: [MapData] -> [TagTagMap]
mapTmpToMap (MapData m : xs) = m : mapTmpToMap xs
mapTmpToMap _ = []

instance Stat MapData MapStat where
  calculate xs =
    let addComponent m x =
          let !m' = Map.unionWith (+) m x
          in m'
        mt = foldl' addComponent Map.empty (mapTmpToMap xs)
    in MapStat mt
  update (MapStat m) (MapData x) (MapData x') =
    let nm = Map.unionWith (+) (Map.unionWith (-) m x) x'
    in MapStat nm
  getValue (MapStat m) = fromIntegral $ Foldable.sum m - Map.size m

-- | Converts Integral types to Double. It's usefull than it's not enough type
-- information in the expression to call fromIntegral directly.
toDouble :: (Integral a) => a -> Double
toDouble = fromIntegral

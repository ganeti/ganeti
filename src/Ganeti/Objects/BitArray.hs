{-# LANGUAGE BangPatterns, RankNTypes #-}

{-| Space efficient bit arrays

The module is meant to be imported qualified
(as it is common with collection libraries).

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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

module Ganeti.Objects.BitArray
  ( BitArray
  , size
  , empty
  , zeroes
  , count0
  , count1
  , foldr
  , (!)
  , setAt
  , (-&-)
  , (-|-)
  , subset
  , asString
  , fromList
  , toList
  ) where

import Prelude hiding (foldr)
import qualified Prelude as P

import Control.Monad
import Control.Monad.Error
import qualified Data.IntSet as IS
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.JSON

-- | A fixed-size, space-efficient array of bits.
data BitArray = BitArray
  { size :: !Int
  , _bitArrayBits :: !IS.IntSet
    -- ^ Must not contain elements outside [0..size-1].
  }
  deriving (Eq, Ord)

instance Show BitArray where
  show = asString '0' '1'

empty :: BitArray
empty = BitArray 0 IS.empty

zeroes :: Int -> BitArray
zeroes s = BitArray s IS.empty

-- | Right fold over the set, including indexes of each value.
foldr :: (Bool -> Int -> a -> a) -> a -> BitArray -> a
foldr f z (BitArray s bits) = let (j, x) = IS.foldr loop (s, z) bits
                               in feed0 (-1) j x
  where
    loop i (!l, x) = (i, f True i (feed0 i l x))
    feed0 !i !j x | i >= j'   = x
                  | otherwise = feed0 i j' (f False j' x)
      where j' = j - 1

-- | Converts a bit array into a string, given characters
-- for @0@ and @1@/
asString :: Char -> Char -> BitArray -> String
asString c0 c1 = foldr f []
  where f b _ = ((if b then c1 else c0) :)

-- | Computes the number of zeroes in the array.
count0 :: BitArray -> Int
count0 ba@(BitArray s _) = s - count1 ba

-- | Computes the number of ones in the array.
count1 :: BitArray -> Int
count1 (BitArray _ bits) = IS.size bits

infixl 9 !
-- | Test a given bit in an array.
-- If it's outside its scope, it's always @False@.
(!) :: BitArray -> Int -> Bool
(!) (BitArray s bits) i | (i >= 0) && (i < s) = IS.member i bits
                        | otherwise           = False

-- | Sets or removes an element from a bit array.

-- | Sets a given bit in an array. Fails if the index is out of bounds.
setAt :: (MonadError e m, Error e) => Int -> Bool -> BitArray -> m BitArray
setAt i False (BitArray s bits) =
  return $ BitArray s (IS.delete i bits)
setAt i True (BitArray s bits) | (i >= 0) && (i < s) =
  return $ BitArray s (IS.insert i bits)
setAt i True _ = failError $ "Index out of bounds: " ++ show i

infixl 7 -&-
-- | An intersection of two bit arrays.
-- The length of the result is the minimum length of the two.
(-&-) :: BitArray -> BitArray -> BitArray
BitArray xs xb -&- BitArray ys yb = BitArray (min xs ys)
                                             (xb `IS.intersection` yb)

infixl 5 -|-
-- | A union of two bit arrays.
-- The length of the result is the maximum length of the two.
(-|-) :: BitArray -> BitArray -> BitArray
BitArray xs xb -|- BitArray ys yb = BitArray (max xs ys) (xb `IS.union` yb)

-- | Checks if the first array is a subset of the other.
subset :: BitArray -> BitArray -> Bool
subset (BitArray _ xs) (BitArray _ ys) = IS.isSubsetOf xs ys

-- | Converts a bit array into a list of booleans.
toList :: BitArray -> [Bool]
toList = foldr (\b _ -> (b :)) []

-- | Converts a list of booleans to a 'BitArray'.
fromList :: [Bool] -> BitArray
fromList xs =
  -- Note: This traverses the list twice. It'd be better to compute everything
  -- in one pass.
  BitArray (length xs) (IS.fromList . map fst . filter snd . zip [0..] $ xs)

instance J.JSON BitArray where
  showJSON = J.JSString . J.toJSString . show
  readJSON j = do
    let parseBit '0' = return False
        parseBit '1' = return True
        parseBit c   = fail $ "Neither '0' nor '1': '" ++ [c] ++ "'"
    str <- readEitherString j
    fromList `liftM` mapM parseBit str

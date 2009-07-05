{-| Some common types.

-}

{-

Copyright (C) 2009 Google Inc.

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

module Ganeti.HTools.Types
    ( Idx
    , Ndx
    , NameAssoc
    , Result(..)
    , Element(..)
    , FailMode(..)
    , OpResult(..)
    ) where

-- | The instance index type.
type Idx = Int

-- | The node index type.
type Ndx = Int

-- | The type used to hold name-to-idx mappings.
type NameAssoc = [(String, Int)]

{-|

This is similar to the JSON library Result type - *very* similar, but
we want to use it in multiple places, so we abstract it into a
mini-library here

-}
data Result a
    = Bad String
    | Ok a
    deriving (Show)

instance Monad Result where
    (>>=) (Bad x) _ = Bad x
    (>>=) (Ok x) fn = fn x
    return = Ok
    fail = Bad

-- | Reason for an operation's falure
data FailMode = FailMem  -- ^ Failed due to not enough RAM
              | FailDisk -- ^ Failed due to not enough disk
              | FailCPU  -- ^ Failed due to not enough CPU capacity
              | FailN1   -- ^ Failed due to not passing N1 checks
                deriving (Eq, Show)

-- | Either-like data-type customized for our failure modes
data OpResult a = OpFail FailMode -- ^ Failed operation
                | OpGood a        -- ^ Success operation

instance Monad OpResult where
    (OpGood x) >>= fn = fn x
    (OpFail y) >>= _ = OpFail y
    return = OpGood

-- | A generic class for items that have updateable names and indices.
class Element a where
    -- | Returns the name of the element
    nameOf  :: a -> String
    -- | Returns the index of the element
    idxOf   :: a -> Int
    -- | Updates the name of the element
    setName :: a -> String -> a
    -- | Updates the index of the element
    setIdx  :: a -> Int -> a

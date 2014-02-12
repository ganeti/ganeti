{-| Implementation of lock allocation.

-}

{-

Copyright (C) 2014 Google Inc.

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

module Ganeti.Locking.Allocation
  ( LockAllocation
  , emptyAllocation
  , OwnerState(..)
  , listLocks
  ) where

import qualified Data.Map as M
import Data.Maybe (fromMaybe)
import qualified Data.Set as S

{-

This module is parametric in the type of locks and lock owners.
While we only state minimal requirements for the types, we will
consistently use the type variable 'a' for the type of locks and
the variable 'b' for the type of the lock owners throughout this
module.

-}

-- | The state of a lock that is taken.
data AllocationState a = Exclusive a | Shared (S.Set a) deriving (Eq, Show)

-- | Data type describing the way a lock can be owned.
data OwnerState = OwnShared | OwnExclusive deriving (Ord, Eq, Show)

{-| Representation of a Lock allocation

To keep queries for locks efficient, we keep two
associations, with the invariant that they fit
together: the association from locks to their
allocation state, and the association from an
owner to the set of locks owned. As we do not
export the constructor, the problem of keeping
this invariant reduces to only exporting functions
that keep the invariant.

-}

data LockAllocation a b =
  LockAllocation { laLocks :: M.Map a (AllocationState b)
                 , laOwned :: M.Map b (M.Map a OwnerState)
                 }
  deriving (Eq, Show)

-- | A state with all locks being free.
emptyAllocation :: (Ord a, Ord b) => LockAllocation a b
emptyAllocation =
  LockAllocation { laLocks = M.empty
                 , laOwned = M.empty
                 }

-- | Obtain the set of locks held by a given owner.
listLocks :: Ord b => b -> LockAllocation a b -> M.Map a OwnerState
listLocks owner = fromMaybe M.empty . M.lookup owner . laOwned

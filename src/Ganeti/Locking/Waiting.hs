{-| Implementation of a priority waiting structure for locks.

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

module Ganeti.Locking.Waiting
 ( LockWaiting
 , emptyWaiting
 ) where

import qualified Data.Map as M
import qualified Data.Set as S

import qualified Ganeti.Locking.Allocation as L

{-

This module is parametric in the type of locks, lock owners, and priorities of
the request. While we state only minimal requirements for the types, we will
consistently use the type variable 'a' for the type of locks, the variable 'b'
for the type of the lock owners, and 'c' for the type of priorities throughout
this module. The type 'c' will have to instance Ord, and the smallest value
indicate the most important priority.

-}

{-| Representation of the waiting structure

For any request we cannot fullfill immediately, we have a set of lock
owners it is blocked on. We can pick one of the owners, the smallest say;
then we know that this request cannot possibly be fulfilled until this
owner does something. So we can index the pending requests by such a chosen
owner and only revisit them once the owner acts. For the requests to revisit
we need to do so in order of increasing priority; this order can be maintained
by the Set data structure, where we make use of the fact that tuples are ordered
lexicographically.

Additionally, we keep track of which owners have pending requests, to disallow
them any other lock tasks till their request is fulfilled. To allow canceling
of pending requests, we also keep track on which owner their request is pending
on and what the request was.

-}

data LockWaiting a b c =
  LockWaiting { lwAllocation :: L.LockAllocation a b
              , lwPending :: M.Map b (S.Set (c, b, [L.LockRequest a]))
              , lwPendingOwners :: M.Map b (b, (c, b, [L.LockRequest a]))
              } deriving Show

-- | A state without locks and pending requests.
emptyWaiting :: (Ord a, Ord b, Ord c) => LockWaiting a b c
emptyWaiting =
  LockWaiting { lwAllocation = L.emptyAllocation
              , lwPending = M.empty
              , lwPendingOwners = M.empty
              }

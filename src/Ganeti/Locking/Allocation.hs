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
  , LockRequest(..)
  , requestExclusive
  , requestShared
  , requestRelease
  , updateLocks
  ) where

import Control.Arrow (second, (***))
import Control.Monad
import Data.Foldable (for_)
import qualified Data.Map as M
import Data.Maybe (fromMaybe)
import qualified Data.Set as S

import Ganeti.BasicTypes

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

-- | Obtain the locks held by a given owner. The locks are reported
-- as a map from the owned locks to the form of ownership (OwnShared
-- or OwnExclusive).
listLocks :: Ord b => b -> LockAllocation a b -> M.Map a OwnerState
listLocks owner = fromMaybe M.empty . M.lookup owner . laOwned

-- | Data Type describing a change request on a single lock.
data LockRequest a = LockRequest { lockAffected :: a
                                 , lockRequestType :: Maybe OwnerState
                                 }
                     deriving (Eq, Show)

-- | Lock request for an exclusive lock.
requestExclusive :: a -> LockRequest a
requestExclusive lock = LockRequest { lockAffected = lock
                                    , lockRequestType = Just OwnExclusive }

-- | Lock request for a shared lock.
requestShared :: a -> LockRequest a
requestShared lock = LockRequest { lockAffected = lock
                                 , lockRequestType = Just OwnShared }

-- | Request to release a lock.
requestRelease :: a -> LockRequest a
requestRelease lock = LockRequest { lockAffected = lock
                                  , lockRequestType = Nothing }

-- | Internal function to update the state according to a single
-- lock request, assuming all prerequisites are met.
updateLock :: (Ord a, Ord b)
           => b
           -> LockAllocation a b -> LockRequest a -> LockAllocation a b
updateLock owner state (LockRequest lock (Just OwnExclusive)) =
  let locks' = M.insert lock (Exclusive owner) $ laLocks state
      ownersLocks' = M.insert lock OwnExclusive $ listLocks owner state
      owned' = M.insert owner ownersLocks' $ laOwned state
  in state { laLocks = locks', laOwned = owned' }
updateLock owner state (LockRequest lock (Just OwnShared)) =
  let ownersLocks' = M.insert lock OwnShared $ listLocks owner state
      owned' = M.insert owner ownersLocks' $ laOwned state
      locks = laLocks state
      lockState' = case M.lookup lock locks of
        Just (Shared s) -> Shared (S.insert owner s)
        _ -> Shared $ S.singleton owner
      locks' = M.insert lock lockState' locks
  in state { laLocks = locks', laOwned = owned' }
updateLock owner state (LockRequest lock Nothing) =
  let ownersLocks' = M.delete lock $ listLocks owner state
      owned = laOwned state
      owned' = if M.null ownersLocks'
                 then M.delete owner owned
                 else M.insert owner ownersLocks' owned
      locks = laLocks state
      lockRemoved = M.delete lock locks
      locks' = case M.lookup lock locks of
                 Nothing -> locks
                 Just (Exclusive x) ->
                   if x == owner then lockRemoved else locks
                 Just (Shared s)
                   -> let s' = S.delete owner s
                      in if S.null s'
                        then lockRemoved
                        else M.insert lock (Shared s') locks
  in state { laLocks = locks', laOwned = owned' }

-- | Update the locks of an owner according to the given request. Return
-- the pair of the new state and the result of the operation, which is the
-- the set of owners on which the operation was blocked on. so an empty set is
-- success, and the state is updated if, and only if, the returned set is emtpy.
-- In that way, it can be used in atomicModifyIORef.
updateLocks :: (Ord a, Show a, Ord b)
               => b
               -> [LockRequest a]
               -> LockAllocation a b -> (LockAllocation a b, Result (S.Set b))
updateLocks owner reqs state = genericResult ((,) state . Bad) (second Ok) $ do
  runListHead (return ())
              (fail . (++) "Inconsitent requests for lock " . show) $ do
      r <- reqs
      r' <- reqs
      guard $ r /= r'
      guard $ lockAffected r == lockAffected r'
      return $ lockAffected r
  let current = listLocks owner state
  unless (M.null current) $ do
    let (highest, _) = M.findMax current
        notHolding = not
                     . any (uncurry (==) . ((M.lookup `flip` current) *** Just))
        orderViolation l = fail $ "Order violation: requesting " ++ show l
                                   ++ " while holding " ++ show highest
    for_ reqs $ \req -> case req of
      LockRequest lock (Just OwnExclusive)
        | lock < highest && notHolding [ (lock, OwnExclusive) ]
        -> orderViolation lock
      LockRequest lock (Just OwnShared)
        | lock < highest && notHolding [ (lock, OwnExclusive)
                                       , (lock, OwnExclusive)]
        -> orderViolation lock
      _ -> Ok ()
  let blockedOn (LockRequest  _ Nothing) = S.empty
      blockedOn (LockRequest lock (Just OwnExclusive)) =
        case M.lookup lock (laLocks state) of
          Just (Exclusive x) -> S.singleton x
          Just (Shared xs) -> xs
          _ -> S.empty
      blockedOn (LockRequest lock (Just OwnShared)) =
        case M.lookup lock (laLocks state) of
          Just (Exclusive x) -> S.singleton x
          _ -> S.empty
  let blocked = S.delete owner . S.unions $ map blockedOn reqs
  let state' = foldl (updateLock owner) state reqs
  return (if S.null blocked then state' else state, blocked)

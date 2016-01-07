{-# LANGUAGE BangPatterns #-}
{-| Implementation of a priority waiting structure for locks.

-}

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

module Ganeti.Locking.Waiting
 ( LockWaiting
 , ExtWaiting
 , emptyWaiting
 , updateLocks
 , updateLocksWaiting
 , safeUpdateLocksWaiting
 , getAllocation
 , getPendingOwners
 , hasPendingRequest
 , removePendingRequest
 , releaseResources
 , getPendingRequests
 , extRepr
 , fromExtRepr
 , freeLocksPredicate
 , downGradeLocksPredicate
 , intersectLocks
 , opportunisticLockUnion
 , guardedOpportunisticLockUnion
 ) where

import Control.Arrow ((&&&), (***), second)
import Control.Monad (liftM)
import Data.List (sort, foldl')
import qualified Data.Map as M
import Data.Maybe (fromMaybe)
import qualified Data.Set as S
import qualified Text.JSON as J

import Ganeti.BasicTypes
import qualified Ganeti.Locking.Allocation as L
import Ganeti.Locking.Types (Lock)

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

-- | Get the set of owners with pending lock requests.
getPendingOwners :: LockWaiting a b c -> S.Set b
getPendingOwners = M.keysSet . lwPendingOwners

-- | Predicate on whether an owner has a pending lock request.
hasPendingRequest :: Ord b => b -> LockWaiting a b c -> Bool
hasPendingRequest owner = M.member owner . lwPendingOwners

-- | Get the allocation state from the waiting state
getAllocation :: LockWaiting a b c -> L.LockAllocation a b
getAllocation = lwAllocation

-- | Get the list of all pending requests.
getPendingRequests :: (Ord a, Ord b, Ord c)
                   => LockWaiting a b c -> S.Set (c, b, [L.LockRequest a])
getPendingRequests = S.unions . M.elems . lwPending

-- | Type of the extensional representation of a LockWaiting.
type ExtWaiting a b c = (L.LockAllocation a b, S.Set (c, b, [L.LockRequest a]))

-- | Get a representation, comparable by (==), that captures the extensional
-- behaviour. In other words, @(==) `on` extRepr@ is a bisumlation.
extRepr :: (Ord a, Ord b, Ord c)
        => LockWaiting a b c -> ExtWaiting a b c
extRepr = getAllocation &&& getPendingRequests

-- | Internal function to fulfill one request if possible, and keep track of
-- the owners to be notified. The type is chosen to be suitable as fold
-- operation.
--
-- This function calls the later defined updateLocksWaiting', as they are
-- mutually recursive.
tryFulfillRequest :: (Lock a, Ord b, Ord c)
                  => (LockWaiting a b c, S.Set b)
                  -> (c, b, [L.LockRequest a])
                  -> (LockWaiting a b c, S.Set b)
tryFulfillRequest (waiting, toNotify) (prio, owner, req) =
  let (waiting', (_, newNotify)) = updateLocksWaiting' prio owner req waiting
  in (waiting', toNotify `S.union` newNotify)

-- | Internal function to recursively follow the consequences of a change.
revisitRequests :: (Lock a, Ord b, Ord c)
                => S.Set b -- ^ the owners where the requests keyed by them
                           -- already have been revisited
                -> S.Set b -- ^ the owners where requests keyed by them need
                           -- to be revisited
                -> LockWaiting a b c -- ^ state before revisiting
                -> (S.Set b, LockWaiting a b c) -- ^ owners visited and state
                                                -- after revisiting
revisitRequests notify todo state =
  let getRequests (pending, reqs) owner =
        (M.delete owner pending
        , fromMaybe S.empty (M.lookup owner pending) `S.union` reqs)
      (pending', requests) = S.foldl' getRequests (lwPending state, S.empty)
                               todo
      revisitedOwners = S.map (\(_, o, _) -> o) requests
      pendingOwners' = S.foldl' (flip M.delete) (lwPendingOwners state)
                               revisitedOwners
      state' = state { lwPending = pending', lwPendingOwners = pendingOwners' }
      (!state'', !notify') = S.foldl' tryFulfillRequest (state', notify)
                               requests
      done = notify `S.union` todo
      !newTodo = notify' S.\\ done
  in if S.null todo
       then (notify, state)
       else revisitRequests done newTodo state''

-- | Update the locks on an onwer according to the given request, if possible.
-- Additionally (if the request succeeds) fulfill any pending requests that
-- became possible through this request. Return the new state of the waiting
-- structure, the result of the operation, and a list of owner whose requests
-- have been fulfilled. The result is, as for lock allocation, the set of owners
-- the request is blocked on. Again, the type is chosen to be suitable for use
-- in atomicModifyIORef.
updateLocks' :: (Lock a, Ord b, Ord c)
             => b
             -> [L.LockRequest a]
             -> LockWaiting a b c
             -> (LockWaiting a b c, (Result (S.Set b), S.Set b))
updateLocks' owner reqs state =
  let (!allocation', !result) = L.updateLocks owner reqs (lwAllocation state)
      state' = state { lwAllocation = allocation' }
      (!notify, !state'') = revisitRequests S.empty (S.singleton owner) state'
  in if M.member owner $ lwPendingOwners state
       then ( state
            , (Bad "cannot update locks while having pending requests", S.empty)
            )
       else if result /= Ok S.empty -- skip computation if request could not
                                    -- be handled anyway
              then (state, (result, S.empty))
              else let pendingOwners' = lwPendingOwners state''
                       toNotify = S.filter (not . flip M.member pendingOwners')
                                           notify
                   in (state'', (result, toNotify))

-- | Update locks as soon as possible. If the request cannot be fulfilled
-- immediately add the request to the waiting queue. The first argument is
-- the priority at which the owner is waiting, the remaining are as for
-- updateLocks', and so is the output.
updateLocksWaiting' :: (Lock a, Ord b, Ord c)
                    => c
                    -> b
                    -> [L.LockRequest a]
                    -> LockWaiting a b c
                    -> (LockWaiting a b c, (Result (S.Set b), S.Set b))
updateLocksWaiting' prio owner reqs state =
  let (state', (result, notify)) = updateLocks' owner reqs state
      !state'' = case result of
        Bad _ -> state' -- bad requests cannot be queued
        Ok empty | S.null empty -> state'
        Ok blocked -> let blocker = S.findMin blocked
                          owners = M.insert owner (blocker, (prio, owner, reqs))
                                     $ lwPendingOwners state
                          pendingEntry = S.insert (prio, owner, reqs)
                                           . fromMaybe S.empty
                                           . M.lookup blocker
                                           $ lwPending state
                          pending = M.insert blocker pendingEntry
                                      $ lwPending state
                      in state' { lwPendingOwners = owners
                                , lwPending = pending
                                }
  in (state'', (result, notify))

-- | Predicate whether a request is already fulfilled in a given state
-- and no requests for that owner are pending.
requestFulfilled :: (Ord a, Ord b)
                 => b -> [L.LockRequest a] -> LockWaiting a b c -> Bool
requestFulfilled owner req state =
  let locks = L.listLocks owner $ lwAllocation state
      isFulfilled r = M.lookup (L.lockAffected r) locks
                        == L.lockRequestType r
  in not (hasPendingRequest owner state) && all isFulfilled req

-- | Update the locks on an onwer according to the given request, if possible.
-- Additionally (if the request succeeds) fulfill any pending requests that
-- became possible through this request. Return the new state of the waiting
-- structure, the result of the operation, and a list of owners to be notified.
-- The result is, as for lock allocation, the set of owners the request is
-- blocked on. Again, the type is chosen to be suitable for use in
-- atomicModifyIORef.
-- For convenience, fulfilled requests are always accepted.
updateLocks :: (Lock a, Ord b, Ord c)
            => b
            -> [L.LockRequest a]
            -> LockWaiting a b c
            -> (LockWaiting a b c, (Result (S.Set b), S.Set b))
updateLocks owner req state =
  if requestFulfilled owner req state
    then (state, (Ok S.empty, S.empty))
    else second (second $ S.delete owner) $ updateLocks' owner req state

-- | Update locks as soon as possible. If the request cannot be fulfilled
-- immediately add the request to the waiting queue. The first argument is
-- the priority at which the owner is waiting, the remaining are as for
-- updateLocks, and so is the output.
-- For convenience, fulfilled requests are always accepted.
updateLocksWaiting :: (Lock a, Ord b, Ord c)
                   => c
                   -> b
                   -> [L.LockRequest a]
                   -> LockWaiting a b c
                   -> (LockWaiting a b c, (Result (S.Set b), S.Set b))
updateLocksWaiting prio owner req state =
  if requestFulfilled owner req state
    then (state, (Ok S.empty, S.empty))
     else second (second $ S.delete owner)
            $ updateLocksWaiting' prio owner req state


-- | Compute the state of a waiting after an owner gives up
-- on his pending request.
removePendingRequest :: (Lock a, Ord b, Ord c)
                     => b -> LockWaiting a b c -> LockWaiting a b c
removePendingRequest owner state =
  let pendingOwners = lwPendingOwners state
      pending = lwPending state
  in case M.lookup owner pendingOwners of
    Nothing -> state
    Just (blocker, entry) ->
      let byBlocker = fromMaybe S.empty . M.lookup blocker $ pending
          byBlocker' = S.delete entry byBlocker
          pending' = if S.null byBlocker'
                       then M.delete blocker pending
                       else M.insert blocker byBlocker' pending
      in state { lwPendingOwners = M.delete owner pendingOwners
               , lwPending = pending'
               }

-- | A repeatable version of `updateLocksWaiting`. If the owner has a pending
-- request and the pending request is equal to the current one, do nothing;
-- otherwise call updateLocksWaiting.
safeUpdateLocksWaiting :: (Lock a, Ord b, Ord c)
                       => c
                       -> b
                       -> [L.LockRequest a]
                       -> LockWaiting a b c
                       -> (LockWaiting a b c, (Result (S.Set b), S.Set b))
safeUpdateLocksWaiting prio owner req state =
  if hasPendingRequest owner state
       && S.singleton req
          == (S.map (\(_, _, r) -> r)
              . S.filter (\(_, b, _) -> b == owner) $ getPendingRequests state)
    then let (_, answer) = updateLocksWaiting prio owner req
                           $ removePendingRequest owner state
         in (state, answer)
    else updateLocksWaiting prio owner req state

-- | Convenience function to release all pending requests and locks
-- of a given owner. Return the new configuration and the owners to
-- notify.
releaseResources :: (Lock a, Ord b, Ord c)
                 => b -> LockWaiting a b c -> (LockWaiting a b c, S.Set b)
releaseResources owner state =
  let state' = removePendingRequest owner state
      request = map L.requestRelease
                  . M.keys . L.listLocks owner $ getAllocation state'
      (state'', (_, notify)) = updateLocks owner request state'
  in (state'', notify)

-- | Obtain a LockWaiting from its extensional representation.
fromExtRepr :: (Lock a, Ord b, Ord c)
            => ExtWaiting a b c -> LockWaiting a b c
fromExtRepr (alloc, pending) =
  S.foldl' (\s (prio, owner, req) ->
              fst $ updateLocksWaiting prio owner req s)
    (emptyWaiting { lwAllocation = alloc })
    pending

instance (Lock a, J.JSON a, Ord b, J.JSON b, Show b, Ord c, J.JSON c)
         => J.JSON (LockWaiting a b c) where
  showJSON = J.showJSON . extRepr
  readJSON = liftM fromExtRepr . J.readJSON

-- | Manipulate a all locks of an owner that have a given property. Also
-- drop all pending requests.
manipulateLocksPredicate :: (Lock a, Ord b, Ord c)
                         => (a -> L.LockRequest a)
                         -> (a -> Bool)
                         -> b
                         -> LockWaiting a b c -> (LockWaiting a b c, S.Set b)
manipulateLocksPredicate req prop owner state =
  second snd . flip (updateLocks owner) (removePendingRequest owner state)
    . map req . filter prop . M.keys
    . L.listLocks owner $ getAllocation state

-- | Free all Locks of a given owner satisfying a given predicate. As this
-- operation is supposed to unconditionally suceed, all pending requests
-- are dropped as well.
freeLocksPredicate :: (Lock a, Ord b, Ord c)
                   => (a -> Bool)
                   -> b
                   -> LockWaiting a b c -> (LockWaiting a b c, S.Set b)
freeLocksPredicate = manipulateLocksPredicate L.requestRelease

-- | Downgrade all locks of  a given owner that satisfy a given predicate. As
-- this operation is supposed to unconditionally suceed, all pending requests
-- are dropped as well.
downGradeLocksPredicate :: (Lock a, Ord b, Ord c)
                        => (a -> Bool)
                        -> b
                        -> LockWaiting a b c -> (LockWaiting a b c, S.Set b)
downGradeLocksPredicate = manipulateLocksPredicate L.requestShared

-- | Intersect locks to a given set.
intersectLocks :: (Lock a, Ord b, Ord c)
               => [a]
               -> b
               -> LockWaiting a b c -> (LockWaiting a b c, S.Set b)
intersectLocks locks = freeLocksPredicate (not . flip elem locks)

-- | Opprotunistically allocate locks for a given owner; return the set
-- of newly actually acquired locks (i.e., locks already held before are
-- not mentioned).
opportunisticLockUnion :: (Lock a, Ord b, Ord c)
                       => b
                       -> [(a, L.OwnerState)]
                       -> LockWaiting a b c
                       -> (LockWaiting a b c, ([a], S.Set b))
opportunisticLockUnion owner reqs state =
  let locks = L.listLocks owner $ getAllocation state
      reqs' = sort $ filter (uncurry (<) . (flip M.lookup locks *** Just)) reqs
      maybeAllocate (s, success) (lock, ownstate) =
        let (s',  (result, _)) =
              updateLocks owner
                          [(if ownstate == L.OwnShared
                              then L.requestShared
                              else L.requestExclusive) lock]
                          s
        in (s', if result == Ok S.empty then lock:success else success)
  in second (flip (,) S.empty) $ foldl' maybeAllocate (state, []) reqs'

-- | A guarded version of opportunisticLockUnion; if the number of fulfilled
-- requests is not at least the given amount, then do not change anything.
guardedOpportunisticLockUnion :: (Lock a, Ord b, Ord c)
                                 => Int
                                 -> b
                                 -> [(a, L.OwnerState)]
                                 -> LockWaiting a b c
                                 -> (LockWaiting a b c, ([a], S.Set b))
guardedOpportunisticLockUnion count owner reqs state =
  let (state', (acquired, toNotify)) = opportunisticLockUnion owner reqs state
  in if length acquired < count
        then (state, ([], S.empty))
        else (state', (acquired, toNotify))

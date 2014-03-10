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
  , lockOwners
  , listLocks
  , LockRequest(..)
  , requestExclusive
  , requestShared
  , requestRelease
  , updateLocks
  , freeLocks
  , intersectLocks
  , opportunisticLockUnion
  ) where

import Control.Applicative (liftA2)
import Control.Arrow (second, (***))
import Control.Monad
import Data.Foldable (for_, find)
import Data.List (sort)
import qualified Data.Map as M
import Data.Maybe (fromMaybe)
import qualified Data.Set as S
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.JSON (toArray)
import Ganeti.Locking.Types

{-

This module is parametric in the type of locks and lock owners.
While we only state minimal requirements for the types, we will
consistently use the type variable 'a' for the type of locks and
the variable 'b' for the type of the lock owners throughout this
module.

-}

-- | Data type describing the way a lock can be owned.
data OwnerState = OwnShared | OwnExclusive deriving (Ord, Eq, Show)

-- | Type describing indirect ownership on a lock. We keep the set
-- of all (lock, owner)-pairs for locks that are implied in the given
-- lock, annotated with the type of ownership (shared or exclusive).
type IndirectOwners a b = M.Map (a, b) OwnerState

-- | The state of a lock that is taken. Besides the state of the lock
-- itself, we also keep track of all other lock allocation that affect
-- the given lock by means of implication.
data AllocationState a b = Exclusive b (IndirectOwners a b)
                         | Shared (S.Set b) (IndirectOwners a b)
                         deriving (Eq, Show)

-- | Compute the set of indirect owners from the information about
-- indirect ownership.
indirectOwners :: (Ord a, Ord b) => M.Map (a, b) OwnerState -> S.Set b
indirectOwners = S.map snd . M.keysSet

-- | Compute the (zero or one-elment) set of exclusive indirect owners.
indirectExclusives :: (Ord a, Ord b) => M.Map (a, b) OwnerState -> S.Set b
indirectExclusives = indirectOwners . M.filter (== OwnExclusive)

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
  LockAllocation { laLocks :: M.Map a (AllocationState a b)
                 , laOwned :: M.Map b (M.Map a OwnerState)
                 }
  deriving (Eq, Show)

-- | A state with all locks being free.
emptyAllocation :: (Ord a, Ord b) => LockAllocation a b
emptyAllocation =
  LockAllocation { laLocks = M.empty
                 , laOwned = M.empty
                 }

-- | Obtain the list of all owners holding at least a single lock.
lockOwners :: Ord b => LockAllocation a b -> [b]
lockOwners = M.keys . laOwned

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

-- | Update the Allocation state of a lock according to a given
-- function.
updateAllocState :: (Ord a, Ord b)
                  => (Maybe (AllocationState a b) -> AllocationState a b)
                  -> LockAllocation a b -> a -> LockAllocation a b
updateAllocState f state lock =
  let locks' = M.alter (find (/= Shared S.empty M.empty) . Just . f)
                        lock (laLocks state)
  in state { laLocks = locks' }

-- | Internal function to update the state according to a single
-- lock request, assuming all prerequisites are met.
updateLock :: (Ord a, Ord b)
           => b
           -> LockAllocation a b -> LockRequest a -> LockAllocation a b
updateLock owner state (LockRequest lock (Just OwnExclusive)) =
  let locks = laLocks state
      lockstate' = case M.lookup lock locks of
        Just (Exclusive _ i) -> Exclusive owner i
        Just (Shared _ i) -> Exclusive owner i
        Nothing -> Exclusive owner M.empty
      locks' = M.insert lock lockstate' locks
      ownersLocks' = M.insert lock OwnExclusive $ listLocks owner state
      owned' = M.insert owner ownersLocks' $ laOwned state
  in state { laLocks = locks', laOwned = owned' }
updateLock owner state (LockRequest lock (Just OwnShared)) =
  let ownersLocks' = M.insert lock OwnShared $ listLocks owner state
      owned' = M.insert owner ownersLocks' $ laOwned state
      locks = laLocks state
      lockState' = case M.lookup lock locks of
        Just (Exclusive _ i) -> Shared (S.singleton owner) i
        Just (Shared s i) -> Shared (S.insert owner s) i
        _ -> Shared (S.singleton owner) M.empty
      locks' = M.insert lock lockState' locks
  in state { laLocks = locks', laOwned = owned' }
updateLock owner state (LockRequest lock Nothing) =
  let ownersLocks' = M.delete lock $ listLocks owner state
      owned = laOwned state
      owned' = if M.null ownersLocks'
                 then M.delete owner owned
                 else M.insert owner ownersLocks' owned
      update (Just (Exclusive x i)) = if x == owner
                                        then Shared S.empty i
                                        else Exclusive x i
      update (Just (Shared s i)) = Shared (S.delete owner s) i
      update Nothing = Shared S.empty M.empty
  in updateAllocState update (state { laOwned = owned' }) lock

-- | Update the set of indirect ownerships of a lock by the given function.
updateIndirectSet :: (Ord a, Ord b)
                  => (IndirectOwners a b -> IndirectOwners a b)
                  -> LockAllocation a b -> a -> LockAllocation a b
updateIndirectSet f =
  let update (Just (Exclusive x i)) = Exclusive x (f i)
      update (Just (Shared s i)) = Shared s (f i)
      update Nothing = Shared S.empty (f M.empty)
  in updateAllocState update

-- | Update all indirect onwerships of a given lock.
updateIndirects :: (Lock a, Ord b)
                => b
                -> LockAllocation a b -> LockRequest a -> LockAllocation a b
updateIndirects owner state req =
  let lock = lockAffected req
      fn = case lockRequestType req of
             Nothing -> M.delete (lock, owner)
             Just tp -> M.insert (lock, owner) tp
  in foldl (updateIndirectSet fn) state $ lockImplications lock

-- | Update the locks of an owner according to the given request. Return
-- the pair of the new state and the result of the operation, which is the
-- the set of owners on which the operation was blocked on. so an empty set is
-- success, and the state is updated if, and only if, the returned set is emtpy.
-- In that way, it can be used in atomicModifyIORef.
updateLocks :: (Lock a, Ord b)
            => b
            -> [LockRequest a]
            -> LockAllocation a b -> (LockAllocation a b, Result (S.Set b))
updateLocks owner reqs state = genericResult ((,) state . Bad) (second Ok) $ do
  unless ((==) (length reqs) . S.size . S.fromList $ map lockAffected reqs)
    . runListHead (return ())
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
        | lock < highest && notHolding [ (lock, OwnShared)
                                       , (lock, OwnExclusive)]
        -> orderViolation lock
      _ -> Ok ()
  let sharedsHeld = M.keysSet $ M.filter (== OwnShared) current
      exclusivesRequested = map lockAffected
                            . filter ((== Just OwnExclusive) . lockRequestType)
                            $ reqs
  runListHead (return ()) fail $ do
    x <- exclusivesRequested
    i <- lockImplications x
    guard $ S.member i sharedsHeld
    return $ "Order violation: requesting exclusively " ++ show x
              ++ " while holding a shared lock on the group lock " ++ show i
              ++ " it belongs to."
  let blockedOn (LockRequest  _ Nothing) = S.empty
      blockedOn (LockRequest lock (Just OwnExclusive)) =
        case M.lookup lock (laLocks state) of
          Just (Exclusive x i) ->
            S.singleton x `S.union` indirectOwners i
          Just (Shared xs i) ->
            xs `S.union` indirectOwners i
          _ -> S.empty
      blockedOn (LockRequest lock (Just OwnShared)) =
        case M.lookup lock (laLocks state) of
          Just (Exclusive x i) ->
            S.singleton x `S.union` indirectExclusives i
          Just (Shared _ i) -> indirectExclusives i
          _ -> S.empty
  let indirectBlocked Nothing _ = S.empty
      indirectBlocked (Just OwnShared) lock =
        case M.lookup lock (laLocks state) of
          Just (Exclusive x _) -> S.singleton x
          _ -> S.empty
      indirectBlocked (Just OwnExclusive) lock =
        case M.lookup lock (laLocks state) of
          Just (Exclusive x _) -> S.singleton x
          Just (Shared xs _) -> xs
          _ -> S.empty
  let direct = S.unions $ map blockedOn reqs
      indirect = reqs >>= \req ->
        map (indirectBlocked (lockRequestType req))
          . lockImplications $ lockAffected req
  let blocked = S.delete owner . S.unions $ direct:indirect
  let state' = foldl (updateLock owner) state reqs
      state'' = foldl (updateIndirects owner) state' reqs
  return (if S.null blocked then state'' else state, blocked)

-- | Compute the state after an onwer releases all its locks.
freeLocks :: (Lock a, Ord b) => LockAllocation a b -> b -> LockAllocation a b
freeLocks state owner =
  fst . flip (updateLocks owner) state . map requestRelease . M.keys
    $ listLocks owner state

-- | Restrict the locks of a user to a given set.
intersectLocks :: (Lock a, Ord b) => b -> [a]
               -> LockAllocation a b -> LockAllocation a b
intersectLocks owner locks state =
  let lockset = S.fromList locks
      toFree = filter (not . flip S.member lockset)
                 . M.keys $ listLocks owner state
  in fst $ updateLocks owner (map requestRelease toFree) state

-- | Opportunistically allocate locks for a given user; return the set
-- of actually acquired. The signature is chosen to be suitable for
-- atomicModifyIORef.
opportunisticLockUnion :: (Lock a, Ord b)
                       => b -> [(a, OwnerState)]
                       -> LockAllocation a b -> (LockAllocation a b, S.Set a)
opportunisticLockUnion owner reqs state =
  let locks = listLocks owner state
      reqs' = sort $ filter (uncurry (<) . (flip M.lookup locks *** Just)) reqs
      maybeAllocate (s, success) (lock, ownstate) =
        let (s', result) = updateLocks owner
                                       [(if ownstate == OwnShared
                                           then requestShared
                                           else requestExclusive) lock]
                                       s
        in (s', if result == Ok S.empty then lock:success else success)
  in second S.fromList $ foldl maybeAllocate (state, []) reqs'

{-| Serializaiton of Lock Allocations

To serialize a lock allocation, we only remember which owner holds
which locks at which level (shared or exclusive). From this information,
everything else can be reconstructed, simply using updateLocks.
-}

instance J.JSON OwnerState where
  showJSON OwnShared = J.showJSON "shared"
  showJSON OwnExclusive = J.showJSON "exclusive"
  readJSON (J.JSString x) = let s = J.fromJSString x
                            in case s of
                              "shared" -> J.Ok OwnShared
                              "exclusive" -> J.Ok OwnExclusive
                              _ -> J.Error $ "Unknown owner type " ++ s
  readJSON _ = J.Error "Owner type not encoded as a string"

-- | Read a lock-ownerstate pair from JSON.
readLockOwnerstate :: (J.JSON a) => J.JSValue -> J.Result (a, OwnerState)
readLockOwnerstate (J.JSArray [x, y]) = liftA2 (,) (J.readJSON x) (J.readJSON y)
readLockOwnerstate x = fail $ "lock-ownerstate pairs are encoded as arrays"
                              ++ " of length 2, but found " ++ show x

-- | Read an owner-lock pair from JSON.
readOwnerLock :: (J.JSON a, J.JSON b)
              => J.JSValue -> J.Result (b, [(a, OwnerState)])
readOwnerLock (J.JSArray [x, J.JSArray ys]) =
  liftA2 (,) (J.readJSON x) (mapM readLockOwnerstate ys)
readOwnerLock x = fail $ "Expected pair of owner and list of owned locks,"
                         ++ " but found " ++ show x

-- | Transform a lock-ownerstate pair into a LockRequest.
toRequest :: (a, OwnerState) -> LockRequest a
toRequest (a, OwnExclusive) = requestExclusive a
toRequest (a, OwnShared) = requestShared a

-- | Obtain a LockAllocation from a given owner-locks list.
-- The obtained allocation is the one obtained if the respective owners
-- requested their locks sequentially.
allocationFromOwners :: (Lock a, Ord b, Show b)
                     => [(b, [(a, OwnerState)])]
                     -> J.Result (LockAllocation a b)
allocationFromOwners =
  let allocateOneOwner s (o, req) = do
        let (s', result) = updateLocks o (map toRequest req) s
        when (result /= Ok S.empty) . fail
          . (++) ("Inconsistent lock status for " ++ show o ++ ": ")
          $ case result of
            Bad err -> err
            Ok blocked -> "blocked on " ++ show (S.toList blocked)
        return s'
  in foldM allocateOneOwner emptyAllocation

instance (Lock a, J.JSON a, Ord b, J.JSON b, Show b)
           => J.JSON (LockAllocation a b) where
  showJSON = J.showJSON . M.toList . M.map M.toList . laOwned
  readJSON x = do
    xs <- toArray x
    owned <- mapM readOwnerLock xs
    allocationFromOwners owned

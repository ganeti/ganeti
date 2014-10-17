{-# LANGUAGE FlexibleContexts #-}

{-| Provides a general functionality for workers that run on the background
and perform some task when triggered.

Each task can process multiple triggers, if they're coming faster than the
tasks are being processed.

Properties:

- If a worked is triggered, it will perform its action eventually.
  (i.e. it won't miss a trigger).

- If the worker is busy, the new action will start immediately when it finishes
  the current one.

- If the worker is idle, it'll start the action immediately.

- If the caller uses 'triggerAndWait', the call will return just after the
  earliest action following the trigger is finished.

- If the caller uses 'triggerWithResult', it will recive an 'Async' value that
  can be used to wait for the result (which will be available once the earliest
  action following the trigger finishes).

- If the worker finishes an action and there are no pending triggers since the
  start of the last action, it becomes idle and waits for a new trigger.

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

module Ganeti.Utils.AsyncWorker
  ( AsyncWorker
  , mkAsyncWorker
  , mkAsyncWorker_
  , trigger
  , trigger_
  , triggerWithResult
  , triggerWithResult_
  , triggerWithResultMany
  , triggerWithResultMany_
  , triggerAndWait
  , triggerAndWait_
  , triggerAndWaitMany
  , triggerAndWaitMany_
  , Async
  , wait
  , waitMany
  ) where

import Control.Monad
import Control.Monad.Base
import Control.Monad.Trans.Control
import Control.Concurrent (ThreadId)
import Control.Concurrent.Lifted (fork, yield)
import Control.Concurrent.MVar.Lifted
import Data.Monoid
import qualified Data.Traversable as T
import Data.IORef.Lifted

-- * The definition and construction of asynchronous workers

-- Represents the state of the requests to the worker. The worker is either
-- 'Idle', or has 'Pending' triggers to process. After the corresponding
-- action is run, all the 'MVar's in the list are notified with the result.
-- Note that the action needs to be run even if the list is empty, as it
-- means that there are pending requests, only nobody needs to be notified of
-- their results.
data TriggerState i a
  = Idle
  | Pending i [MVar a]


-- | Adds a new trigger to the current state (therefore the result is always
-- 'Pending'), optionally adding a 'MVar' that will receive the output.
addTrigger :: (Monoid i)
           => i -> Maybe (MVar a) -> TriggerState i a -> TriggerState i a
addTrigger i mmvar state = let rs = recipients state
                           in Pending (input state <> i)
                                      (maybe rs (: rs) mmvar)
  where
    recipients Idle           = []
    recipients (Pending _ rs) = rs
    input Idle          = mempty
    input (Pending j _) = j

-- | Represent an asynchronous worker whose single action execution returns a
-- value of type @a@.
data AsyncWorker i a
    = AsyncWorker ThreadId (IORef (TriggerState i a)) (MVar ())

-- | Given an action, construct an 'AsyncWorker'.
mkAsyncWorker :: (Monoid i, MonadBaseControl IO m)
              => (i -> m a) -> m (AsyncWorker i a)
mkAsyncWorker act = do
    trig <- newMVar ()
    ref <- newIORef Idle
    thId <- fork . forever $ do
        takeMVar trig           -- wait for a trigger
        state <- swap ref Idle  -- check the state of pending requests
        -- if there are pending requests, run the action and send them results
        case state of
          Idle          -> return () -- all trigers have been processed, we've
                                     -- been woken up by a trigger that has been
                                     -- already included in the last run
          Pending i rs  -> act i >>= forM_ rs . flip tryPutMVar
        -- Give other threads a chance to do work while we're waiting for
        -- something to happen.
        yield
    return $ AsyncWorker thId ref trig
  where
    swap :: (MonadBase IO m) => IORef a -> a -> m a
    swap ref x = atomicModifyIORef ref ((,) x)

-- | Given an action, construct an 'AsyncWorker' with no input.
mkAsyncWorker_ :: (MonadBaseControl IO m)
               => m a -> m (AsyncWorker () a)
mkAsyncWorker_ = mkAsyncWorker . const

-- * Triggering workers and obtaining their results

-- | An asynchronous result that will eventually yield a value.
newtype Async a = Async { asyncResult :: MVar a }

-- | Waits for an asynchronous result to finish and yield a value.
wait :: (MonadBase IO m) => Async a -> m a
wait = readMVar . asyncResult

-- | Waits for all asynchronous results in a collection to finish and yield a
-- value.
waitMany :: (MonadBase IO m, T.Traversable t) => t (Async a) -> m (t a)
waitMany = T.mapM wait

-- An internal function for triggering a worker, optionally registering
-- a callback 'MVar'
triggerInternal :: (MonadBase IO m, Monoid i)
                => i -> Maybe (MVar a) -> AsyncWorker i a -> m ()
triggerInternal i mmvar (AsyncWorker _ ref trig) = do
    atomicModifyIORef ref (\ts -> (addTrigger i mmvar ts, ()))
    _ <- tryPutMVar trig ()
    return ()

-- | Trigger a worker, letting it run its action asynchronously, but do not
-- wait for the result.
trigger :: (MonadBase IO m, Monoid i) => i -> AsyncWorker i a -> m ()
trigger = flip triggerInternal Nothing

-- | Trigger a worker with no input, letting it run its action asynchronously,
-- but do not wait for the result.
trigger_ :: (MonadBase IO m) => AsyncWorker () a -> m ()
trigger_ = trigger ()

-- | Trigger a worker and wait until the action following this trigger
-- finishes. The returned `Async` value can be used to wait for the result of
-- the action.
triggerWithResult :: (MonadBase IO m, Monoid i)
                  => i -> AsyncWorker i a -> m (Async a)
triggerWithResult i worker = do
    result <- newEmptyMVar
    triggerInternal i (Just result) worker
    return $ Async result

-- | Trigger a worker and wait until the action following this trigger
-- finishes.
--
-- See 'triggerWithResult'.
triggerWithResult_ :: (MonadBase IO m) => AsyncWorker () a -> m (Async a)
triggerWithResult_ = triggerWithResult ()

-- | Trigger a list of workers and wait until all the actions following these
-- triggers finish. The returned collection of `Async` values can be used to
-- wait for the results of the actions.
triggerWithResultMany :: (T.Traversable t, MonadBase IO m, Monoid i)
                      => i -> t (AsyncWorker i a) -> m (t (Async a))
triggerWithResultMany i = T.mapM (triggerWithResult i)
--
-- | Trigger a list of workers with no inputs and wait until all the actions
-- following these triggers finish.
--
-- See 'triggerWithResultMany'.
triggerWithResultMany_ :: (T.Traversable t, MonadBase IO m)
                       => t (AsyncWorker () a) -> m (t (Async a))
triggerWithResultMany_ = triggerWithResultMany ()

-- * Helper functions for waiting for results just after triggering workers

-- | Trigger a list of workers and wait until all the actions following these
-- triggers finish. Returns the results of the actions.
--
-- Note that there is a significant difference between 'triggerAndWaitMany'
-- and @mapM triggerAndWait@. The latter runs all the actions of the workers
-- sequentially, while the former runs them in parallel.
triggerAndWaitMany :: (T.Traversable t, MonadBase IO m, Monoid i)
                   => i -> t (AsyncWorker i a) -> m (t a)
triggerAndWaitMany i = waitMany <=< triggerWithResultMany i

-- See 'triggetAndWaitMany'.
triggerAndWaitMany_ :: (T.Traversable t, MonadBase IO m)
                    => t (AsyncWorker () a) -> m (t a)
triggerAndWaitMany_ = triggerAndWaitMany ()

-- | Trigger a worker and wait until the action following this trigger
-- finishes. Return the result of the action.
triggerAndWait :: (MonadBase IO m, Monoid i) => i -> AsyncWorker i a -> m a
triggerAndWait i = wait <=< triggerWithResult i

-- | Trigger a worker with no input and wait until the action following this
-- trigger finishes. Return the result of the action.
triggerAndWait_ :: (MonadBase IO m) => AsyncWorker () a -> m a
triggerAndWait_ = triggerAndWait ()

{-| Utility functions for MonadPlus operations

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

module Ganeti.Utils.Monad
  ( mretryN
  , retryMaybeN
  , anyM
  , allM
  , orM
  , unfoldrM
  , unfoldrM'
  , retryErrorN
  ) where

import Control.Monad
import Control.Monad.Error.Class (MonadError(..))
import Control.Monad.Trans.Maybe

-- | Retries the given action up to @n@ times.
-- The action signals failure by 'mzero'.
mretryN :: (MonadPlus m) => Int -> (Int -> m a) -> m a
mretryN n = msum . flip map [1..n]

-- | Retries the given action up to @n@ times.
-- The action signals failure by 'mzero'.
retryMaybeN :: (Monad m) => Int -> (Int -> MaybeT m a) -> m (Maybe a)
retryMaybeN = (runMaybeT .) . mretryN

-- | Retries the given action up to @n@ times until it succeeds.
-- If all actions fail, the error of the last one is returned.
-- The action is always run at least once, even if @n@ is less than 1.
retryErrorN :: (MonadError e m) => Int -> (Int -> m a) -> m a
retryErrorN n f = loop 1
  where
    loop i | i < n      = catchError (f i) (const $ loop (i + 1))
           | otherwise  = f i

-- * From monad-loops (until we can / want to depend on it):

-- | Short-circuit 'any' with a monadic predicate.
anyM :: (Monad m) => (a -> m Bool) -> [a] -> m Bool
anyM p = foldM (\v x -> if v then return True else p x) False

-- | Short-circuit 'all' with a monadic predicate.
allM :: (Monad m) => (a -> m Bool) -> [a] -> m Bool
allM p = foldM (\v x -> if v then p x else return False) True

-- | Short-circuit 'or' for values of type Monad m => m Bool
orM :: (Monad m) => [m Bool] -> m Bool
orM = anyM id

-- |See 'Data.List.unfoldr'.  This is a monad-friendly version of that.
unfoldrM :: (Monad m) => (a -> m (Maybe (b,a))) -> a -> m [b]
unfoldrM = unfoldrM'

-- | See 'Data.List.unfoldr'. This is a monad-friendly version of that, with a
-- twist. Rather than returning a list, it returns any MonadPlus type of your
-- choice.
unfoldrM' :: (Monad m, MonadPlus f) => (a -> m (Maybe (b,a))) -> a -> m (f b)
unfoldrM' f z = do
        x <- f z
        case x of
                Nothing         -> return mzero
                Just (x', z')   -> do
                        xs <- unfoldrM' f z'
                        return (return x' `mplus` xs)

{-# LANGUAGE FlexibleContexts, RankNTypes #-}

{-| Utility functions for working with IORefs. -}

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

module Ganeti.Utils.IORef
  ( atomicModifyWithLens
  , atomicModifyIORefErr
  , atomicModifyIORefErrLog
  ) where

import Control.Monad
import Control.Monad.Base
import Data.IORef.Lifted
import Data.Tuple (swap)

import Ganeti.BasicTypes
import Ganeti.Lens
import Ganeti.Logging
import Ganeti.Logging.WriterLog

-- | Atomically modifies an 'IORef' using a lens
atomicModifyWithLens :: (MonadBase IO m)
                     => IORef a -> Lens a a b c -> (b -> (r, c)) -> m r
atomicModifyWithLens ref l f = atomicModifyIORef ref (swap . traverseOf l f)

-- | Atomically modifies an 'IORef' using a function that can possibly fail.
-- If it fails, the value of the 'IORef' is preserved.
atomicModifyIORefErr :: (MonadBase IO m)
                     => IORef a -> (a -> GenericResult e (a, b))
                     -> ResultT e m b
atomicModifyIORefErr ref f =
  let f' x = genericResult ((,) x . Bad) (fmap Ok) (f x)
   in ResultT $ atomicModifyIORef ref f'

-- | Atomically modifies an 'IORef' using a function that can possibly fail
-- and log errors.
-- If it fails, the value of the 'IORef' is preserved.
-- Any log messages are passed to the outer monad.
atomicModifyIORefErrLog :: (MonadBase IO m, MonadLog m)
                        => IORef a -> (a -> ResultT e WriterLog (a, b))
                        -> ResultT e m b
atomicModifyIORefErrLog ref f = ResultT $ do
  let f' x = let ((a, b), w) = runWriterLog
                              . liftM (genericResult ((,) x . Bad) (fmap Ok))
                              . runResultT $ f x
             in (a, (b, w))
  (b, w) <- atomicModifyIORef ref f'
  dumpLogSeq w
  return b

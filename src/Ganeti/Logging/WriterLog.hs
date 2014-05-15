{-# LANGUAGE FlexibleInstances, FlexibleContexts, TypeFamilies,
             MultiParamTypeClasses #-}

{-| A pure implementation of MonadLog using MonadWriter

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

module Ganeti.Logging.WriterLog
  ( WriterLogT
  , runWriterLogT
  , execWriterLogT
  ) where

import Control.Applicative
import Control.Monad
import Control.Monad.Base
import Control.Monad.IO.Class
import Control.Monad.Trans.Control
import Control.Monad.Writer
import qualified Data.Foldable as F
import Data.Sequence

import Ganeti.Logging

-- * The data type of the monad transformer

type LogSeq = Seq (Priority, String)

type WriterSeq = WriterT LogSeq

-- | A monad transformer that adds pure logging capability.
newtype WriterLogT m a =
  WriterLogT { unwrapWriterLogT :: WriterSeq m a }

-- Runs a 'WriterLogT', returning the result and accumulated messages.
runWriterLogT :: WriterLogT m a -> m (a, LogSeq)
runWriterLogT = runWriterT . unwrapWriterLogT

-- | Runs a 'WriterLogT', and when it finishes, resends all log messages
-- to the underlying monad that implements 'MonadLog'.
--
-- This can be used to delay logging messages, by accumulating them
-- in 'WriterLogT', and resending them at the end to the underlying monad.
execWriterLogT :: (MonadLog m) => WriterLogT m a -> m a
execWriterLogT k = do
  (r, msgs) <- runWriterLogT k
  F.mapM_ (uncurry logAt) msgs
  return r

instance (Monad m) => Functor (WriterLogT m) where
  fmap = liftM

instance (Monad m) => Applicative (WriterLogT m) where
  pure = return
  (<*>) = ap

instance (MonadPlus m) => Alternative (WriterLogT m) where
  empty = mzero
  (<|>) = mplus

instance (Monad m) => Monad (WriterLogT m) where
  return = WriterLogT . return
  (WriterLogT k) >>= f = WriterLogT $ k >>= (unwrapWriterLogT . f)

instance (Monad m) => MonadLog (WriterLogT m) where
  logAt = curry (WriterLogT . tell . singleton)

instance (MonadIO m) => MonadIO (WriterLogT m) where
  liftIO = WriterLogT . liftIO

instance (MonadPlus m) => MonadPlus (WriterLogT m) where
  mzero = lift mzero
  mplus (WriterLogT x) (WriterLogT y) = WriterLogT $ mplus x y

instance (MonadBase IO m) => MonadBase IO (WriterLogT m) where
  liftBase = WriterLogT . liftBase

instance MonadTrans WriterLogT where
  lift = WriterLogT . lift

instance MonadTransControl WriterLogT where
    newtype StT WriterLogT a =
      StWriterLog { unStWriterLog :: (a, LogSeq) }
    liftWith f = WriterLogT . WriterT $ liftM (\x -> (x, mempty))
                              (f $ liftM StWriterLog . runWriterLogT)
    restoreT = WriterLogT . WriterT . liftM unStWriterLog
    {-# INLINE liftWith #-}
    {-# INLINE restoreT #-}

instance (MonadBaseControl IO m)
         => MonadBaseControl IO (WriterLogT m) where
  newtype StM (WriterLogT m) a
    = StMWriterLog { runStMWriterLog :: ComposeSt WriterLogT m a }
  liftBaseWith = defaultLiftBaseWith StMWriterLog
  restoreM = defaultRestoreM runStMWriterLog
  {-# INLINE liftBaseWith #-}
  {-# INLINE restoreM #-}

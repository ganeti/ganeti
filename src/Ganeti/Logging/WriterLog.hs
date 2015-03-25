{-# LANGUAGE FlexibleInstances, FlexibleContexts, TypeFamilies,
             MultiParamTypeClasses, GeneralizedNewtypeDeriving,
             StandaloneDeriving, UndecidableInstances, CPP #-}

{-| A pure implementation of MonadLog using MonadWriter

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

module Ganeti.Logging.WriterLog
  ( WriterLogT
  , WriterLog
  , runWriterLogT
  , runWriterLog
  , dumpLogSeq
  , execWriterLogT
  , execWriterLog
  ) where


import Control.Applicative
import Control.Monad
import Control.Monad.Base
import Control.Monad.IO.Class
import Control.Monad.Trans.Control
import Control.Monad.Writer
import qualified Data.Foldable as F
import Data.Functor.Identity
import Data.Sequence

import Ganeti.Logging

-- * The data type of the monad transformer

type LogSeq = Seq (Priority, String)

type WriterSeq = WriterT LogSeq

-- | A monad transformer that adds pure logging capability.
newtype WriterLogT m a =
  WriterLogT { unwrapWriterLogT :: WriterSeq m a }
  deriving (Functor, Applicative, Alternative, Monad, MonadPlus, MonadIO,
            MonadTrans)

deriving instance (MonadBase IO m) => MonadBase IO (WriterLogT m)

type WriterLog = WriterLogT Identity

-- Runs a 'WriterLogT', returning the result and accumulated messages.
runWriterLogT :: WriterLogT m a -> m (a, LogSeq)
runWriterLogT = runWriterT . unwrapWriterLogT

-- Runs a 'WriterLog', returning the result and accumulated messages.
runWriterLog :: WriterLog a -> (a, LogSeq)
runWriterLog = runIdentity . runWriterLogT

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

-- | Sends all log messages to the a monad that implements 'MonadLog'.
dumpLogSeq :: (MonadLog m) => LogSeq -> m ()
dumpLogSeq = F.mapM_ (uncurry logAt)

-- | Runs a 'WriterLog', and when it finishes, resends all log messages
-- to the a monad that implements 'MonadLog'.
execWriterLog :: (MonadLog m) => WriterLog a -> m a
execWriterLog k = do
  let (r, msgs) = runWriterLog k
  dumpLogSeq msgs
  return r

instance (Monad m) => MonadLog (WriterLogT m) where
  logAt = curry (WriterLogT . tell . singleton)

instance MonadTransControl WriterLogT where
#if MIN_VERSION_monad_control(1,0,0)
-- Needs Undecidable instances
    type StT WriterLogT a = (a, LogSeq)
    liftWith f = WriterLogT . WriterT $ liftM (\x -> (x, mempty))
                              (f runWriterLogT)
    restoreT = WriterLogT . WriterT
#else
    newtype StT WriterLogT a =
      StWriterLog { unStWriterLog :: (a, LogSeq) }
    liftWith f = WriterLogT . WriterT $ liftM (\x -> (x, mempty))
                              (f $ liftM StWriterLog . runWriterLogT)
    restoreT = WriterLogT . WriterT . liftM unStWriterLog
#endif
    {-# INLINE liftWith #-}
    {-# INLINE restoreT #-}

instance (MonadBaseControl IO m)
         => MonadBaseControl IO (WriterLogT m) where
#if MIN_VERSION_monad_control(1,0,0)
-- Needs Undecidable instances
  type StM (WriterLogT m) a
    = ComposeSt WriterLogT m a
  liftBaseWith = defaultLiftBaseWith
  restoreM = defaultRestoreM
#else
  newtype StM (WriterLogT m) a
    = StMWriterLog { runStMWriterLog :: ComposeSt WriterLogT m a }
  liftBaseWith = defaultLiftBaseWith StMWriterLog
  restoreM = defaultRestoreM runStMWriterLog
#endif
  {-# INLINE liftBaseWith #-}
  {-# INLINE restoreM #-}

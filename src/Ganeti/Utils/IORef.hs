{-# LANGUAGE FlexibleContexts, RankNTypes #-}

{-| Utility functions for working with IORefs. -}

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

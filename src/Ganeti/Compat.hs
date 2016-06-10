{-# LANGUAGE CPP #-}

{- | Compatibility helper module.

This module holds definitions that help with supporting multiple
library versions or transitions between versions.

-}

{-

Copyright (C) 2011, 2012 Google Inc.
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

module Ganeti.Compat
  ( rwhnf
  , Control.Parallel.Strategies.parMap
  , finiteBitSize
  , atomicModifyIORef'
  ) where

import qualified Control.Parallel.Strategies
import qualified Data.Bits
import qualified Data.IORef

-- | Wrapper over the function exported from
-- "Control.Parallel.Strategies".
--
-- This wraps either the old or the new name of the function,
-- depending on the detected library version.
rwhnf :: Control.Parallel.Strategies.Strategy a
#if MIN_VERSION_parallel(3,0,0)
rwhnf = Control.Parallel.Strategies.rseq
#else
rwhnf = Control.Parallel.Strategies.rwhnf
#endif


#if __GLASGOW_HASKELL__ < 707
finiteBitSize :: (Data.Bits.Bits a) => a -> Int
finiteBitSize = Data.Bits.bitSize
#else
finiteBitSize :: (Data.Bits.FiniteBits a) => a -> Int
finiteBitSize = Data.Bits.finiteBitSize
#endif
{-# INLINE finiteBitSize #-}

-- FIXME: remove this when dropping support for GHC 7.4.
atomicModifyIORef' :: Data.IORef.IORef a -> (a -> (a, b)) -> IO b
#if MIN_VERSION_base(4,6,0)
atomicModifyIORef' = Data.IORef.atomicModifyIORef'
#else
atomicModifyIORef' ref f = do
    b <- Data.IORef.atomicModifyIORef ref $ \a ->
            case f a of
                v@(a',_) -> a' `seq` v
    b `seq` return b
#endif

{-| Utilities related to randomized computations.

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

module Ganeti.Utils.Random
  ( generateSecret
  , generateOneMAC
  , delayRandom
  ) where

import Control.Applicative
import Control.Concurrent (threadDelay)
import Control.Monad
import Control.Monad.State
import System.Random
import Text.Printf

-- | Generates a random secret of a given length.
-- The type is chosen so that it can be easily wrapped into a state monad.
generateSecret :: (RandomGen g) => Int -> g -> (String, g)
generateSecret n =
  runState . liftM (concatMap $ printf "%02x")
  $ replicateM n (state $ randomR (0 :: Int, 255))

-- | Given a prefix, randomly generates a full MAC address.
--
-- See 'generateMAC' for discussion about how this function uses
-- the random generator.
generateOneMAC :: (RandomGen g) => String -> g -> (String, g)
generateOneMAC prefix = runState $
  let randByte = state (randomR (0, 255 :: Int))
  in printf "%s:%02x:%02x:%02x" prefix <$> randByte <*> randByte <*> randByte

-- | Wait a time period randomly chosen within the given bounds
-- (in microseconds).
delayRandom :: (Int, Int) -> IO ()
delayRandom = threadDelay <=< randomRIO

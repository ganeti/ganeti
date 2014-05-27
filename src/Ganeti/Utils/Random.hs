{-| Utilities related to randomized computations.

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

module Ganeti.Utils.Random
  ( generateSecret
  , generateOneMAC
  ) where

import Control.Applicative
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

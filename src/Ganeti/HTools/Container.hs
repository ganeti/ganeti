{-| Module abstracting the node and instance container implementation.

This is currently implemented on top of an 'IntMap', which seems to
give the best performance for our workload.

-}

{-

Copyright (C) 2009, 2010, 2011 Google Inc.
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

module Ganeti.HTools.Container
  ( -- * Types
    Container
  , Key
  -- * Creation
  , IntMap.empty
  , IntMap.singleton
  , IntMap.fromList
  -- * Query
  , IntMap.size
  , IntMap.null
  , find
  , IntMap.findMax
  , IntMap.member
  -- * Update
  , add
  , addTwo
  , IntMap.map
  , IntMap.mapAccum
  , IntMap.filter
  -- * Conversion
  , IntMap.elems
  , IntMap.keys
  -- * Element functions
  , nameOf
  , findByName
  ) where

import qualified Data.IntMap as IntMap

import qualified Ganeti.HTools.Types as T

-- | Our key type.

type Key = IntMap.Key

-- | Our container type.
type Container = IntMap.IntMap

-- | Locate a key in the map (must exist).
find :: Key -> Container a -> a
find k = (IntMap.! k)

-- | Add or update one element to the map.
add :: Key -> a -> Container a -> Container a
add = IntMap.insert

-- | Add or update two elements of the map.
addTwo :: Key -> a -> Key -> a -> Container a -> Container a
addTwo k1 v1 k2 v2 = add k1 v1 . add k2 v2

-- | Compute the name of an element in a container.
nameOf :: (T.Element a) => Container a -> Key -> String
nameOf c k = T.nameOf $ find k c

-- | Find an element by name in a Container; this is a very slow function.
findByName :: (T.Element a, Monad m) =>
              Container a -> String -> m a
findByName c n =
  let all_elems = IntMap.elems c
      result = filter ((n `elem`) . T.allNames) all_elems
  in case result of
       [item] -> return item
       _ -> fail $ "Wrong number of elems found with name " ++ n

{-| PyValueInstances contains instances for the 'PyValue' typeclass.

The typeclass 'PyValue' converts Haskell values to Python values.
This module contains instances of this typeclass for several generic
types.  These instances are used in the Haskell to Python generation
of opcodes and constants, for example.

-}

{-

Copyright (C) 2013 Google Inc.
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
{-# LANGUAGE FlexibleInstances, OverlappingInstances,
             TypeSynonymInstances, IncoherentInstances #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}
module Ganeti.PyValueInstances where

import Data.List (intercalate)
import Data.Map (Map)
import qualified Data.Map as Map
import qualified Data.Set as Set (toList)

import Ganeti.BasicTypes
import Ganeti.THH

instance PyValue Bool where
  showValue = show

instance PyValue Int where
  showValue = show

instance PyValue Integer where
  showValue = show

instance PyValue Double where
  showValue = show

instance PyValue Char where
  showValue = show

instance (PyValue a, PyValue b) => PyValue (a, b) where
  showValue (x, y) = "(" ++ showValue x ++ "," ++ showValue y ++ ")"

instance (PyValue a, PyValue b, PyValue c) => PyValue (a, b, c) where
  showValue (x, y, z) =
    "(" ++
    showValue x ++ "," ++
    showValue y ++ "," ++
    showValue z ++
    ")"

instance PyValue String where
  showValue = show

instance PyValue a => PyValue [a] where
  showValue xs = "[" ++ intercalate "," (map showValue xs) ++ "]"

instance (PyValue k, PyValue a) => PyValue (Map k a) where
  showValue mp =
    "{" ++ intercalate ", " (map showPair (Map.assocs mp)) ++ "}"
    where showPair (k, x) = showValue k ++ ":" ++ showValue x

instance PyValue a => PyValue (ListSet a) where
  showValue = showValue . Set.toList . unListSet

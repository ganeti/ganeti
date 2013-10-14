{-| PyValueInstances contains instances for the 'PyValue' typeclass.

The typeclass 'PyValue' converts Haskell values to Python values.
This module contains instances of this typeclass for several generic
types.  These instances are used in the Haskell to Python generation
of opcodes and constants, for example.

-}

{-

Copyright (C) 2013 Google Inc.

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

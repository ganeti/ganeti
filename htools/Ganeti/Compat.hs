{-# LANGUAGE CPP #-}

{- | Compatibility helper module.

This module holds definitions that help with supporting multiple
library versions or transitions between versions.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.Compat
  ( rwhnf
  , Control.Parallel.Strategies.parMap
  ) where

import qualified Control.Parallel.Strategies

-- | Wrapper over the function exported from
-- "Control.Parallel.Strategies".
--
-- This wraps either the old or the new name of the function,
-- depending on the detected library version.
rwhnf :: Control.Parallel.Strategies.Strategy a
#ifdef PARALLEL3
rwhnf = Control.Parallel.Strategies.rseq
#else
rwhnf = Control.Parallel.Strategies.rwhnf
#endif

{-| Utility functions for MonadPlus operations

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

module Ganeti.Utils.MonadPlus
  ( mretryN
  , retryMaybeN
  ) where

import Control.Monad
import Control.Monad.Trans.Maybe

-- | Retries the given action up to @n@ times.
-- The action signals failure by 'mzero'.
mretryN :: (MonadPlus m) => Int -> (Int -> m a) -> m a
mretryN n = msum . flip map [1..n]

-- | Retries the given action up to @n@ times.
-- The action signals failure by 'mzero'.
retryMaybeN :: (Monad m) => Int -> (Int -> MaybeT m a) -> m (Maybe a)
retryMaybeN = (runMaybeT .) . mretryN

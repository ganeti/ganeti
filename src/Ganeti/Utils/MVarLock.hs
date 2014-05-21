{-# LANGUAGE FlexibleContexts #-}

{-| Utility functions for using MVars as simple locks. -}

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

module Ganeti.Utils.MVarLock
  ( Lock()
  , newLock
  , withLock
  ) where

import Control.Exception.Lifted
import Control.Concurrent.MVar.Lifted
import Control.Monad
import Control.Monad.Base (MonadBase(..))
import Control.Monad.Trans.Control (MonadBaseControl(..))

newtype Lock = MVarLock (MVar ())

newLock :: (MonadBase IO m) => m Lock
newLock = MVarLock `liftM` newMVar ()

withLock :: (MonadBaseControl IO m) => Lock -> m a -> m a
withLock (MVarLock l) = bracket_ (takeMVar l) (putMVar l ())

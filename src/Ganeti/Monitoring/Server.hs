{-# LANGUAGE OverloadedStrings #-}

{-| Implementation of the Ganeti confd server functionality.

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

module Ganeti.Monitoring.Server
  ( main
  , checkMain
  , prepMain
  ) where

import Ganeti.Daemon

-- * Types and constants definitions

-- | Type alias for checkMain results.
type CheckResult = ()

-- | Type alias for prepMain results.
type PrepResult = ()

-- * Helper functions

-- | Check function for the monitoring agent.
checkMain :: CheckFn CheckResult
checkMain _ = return $ Right ()

-- | Prepare function for monitoring agent.
prepMain :: PrepFn CheckResult PrepResult
prepMain _ _ = return ()

-- | Main function.
main :: MainFn CheckResult PrepResult
main _ _ _ =
  return ()

{-# LANGUAGE FlexibleInstances, TypeSynonymInstances #-}
{-| Data types for Xen-specific hypervisor functionalities.

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
module Ganeti.Hypervisor.Xen.Types
  ( LispConfig(..)
  , Domain(..)
  , FromLispConfig(..)
  , UptimeInfo(..)
  , ActualState(..)
  ) where

import qualified Text.JSON as J

import Ganeti.BasicTypes

-- | Data type representing configuration data as produced by the
-- @xm list --long@ command.
data LispConfig = LCList [LispConfig]
                | LCString String
                | LCDouble Double
                deriving (Eq, Show)

-- | Data type representing a Xen Domain.
data Domain = Domain
  { domId      :: Int
  , domName    :: String
  , domCpuTime :: Double
  , domState   :: ActualState
  , domIsHung  :: Maybe Bool
  } deriving (Show, Eq)

-- | Class representing all the types that can be extracted from LispConfig.
class FromLispConfig a where
  fromLispConfig :: LispConfig -> Result a

-- | Instance of FromLispConfig for Int.
instance FromLispConfig Int where
  fromLispConfig (LCDouble d) = Ok $ floor d
  fromLispConfig (LCList (LCString _:LCDouble d:[])) = Ok $ floor d
  fromLispConfig c =
    Bad $ "Unable to extract a Int from this configuration: "
      ++ show c

-- | Instance of FromLispConfig for Double.
instance FromLispConfig Double where
  fromLispConfig (LCDouble d) = Ok d
  fromLispConfig (LCList (LCString _:LCDouble d:[])) = Ok d
  fromLispConfig c =
    Bad $ "Unable to extract a Double from this configuration: "
      ++ show c

-- | Instance of FromLispConfig for String
instance FromLispConfig String where
  fromLispConfig (LCString s) = Ok s
  fromLispConfig (LCList (LCString _:LCString s:[])) = Ok s
  fromLispConfig c =
    Bad $ "Unable to extract a String from this configuration: "
      ++ show c

-- | Instance of FromLispConfig for [LispConfig]
instance FromLispConfig [LispConfig] where
  fromLispConfig (LCList l) = Ok l
  fromLispConfig c =
    Bad $ "Unable to extract a List from this configuration: "
      ++ show c

-- Data type representing the information that can be obtained from @xm uptime@
data UptimeInfo = UptimeInfo
  { uInfoName   :: String
  , uInfoID     :: Int
  , uInfoUptime :: String
  } deriving (Eq, Show)

data ActualState = ActualRunning  -- ^ The instance is running
                 | ActualBlocked  -- ^ The instance is not running or runnable
                 | ActualPaused   -- ^ The instance has been paused
                 | ActualShutdown -- ^ The instance is shut down
                 | ActualCrashed  -- ^ The instance has crashed
                 | ActualDying    -- ^ The instance is in process of dying
                 | ActualHung     -- ^ The instance is hung
                 | ActualUnknown  -- ^ Unknown state. Parsing error.
                 deriving (Show, Eq)

instance J.JSON ActualState where
  showJSON ActualRunning = J.showJSON "running"
  showJSON ActualBlocked = J.showJSON "blocked"
  showJSON ActualPaused = J.showJSON "paused"
  showJSON ActualShutdown = J.showJSON "shutdown"
  showJSON ActualCrashed = J.showJSON "crashed"
  showJSON ActualDying = J.showJSON "dying"
  showJSON ActualHung = J.showJSON "hung"
  showJSON ActualUnknown = J.showJSON "unknown"

  readJSON = error "JSON read instance not implemented for type ActualState"

{-# LANGUAGE TemplateHaskell #-}

{-| Pure functions for manipulating the configuration state.

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

module Ganeti.WConfd.ConfigState
  ( ConfigState
  , csConfigData
  , csConfigDataL
  , mkConfigState
  , bumpSerial
  , needsFullDist
  ) where

import Control.Applicative
import Data.Function (on)
import System.Time (ClockTime(..))

import Ganeti.Config
import Ganeti.Lens
import Ganeti.Objects
import Ganeti.Objects.Lens

-- | In future this data type will include the current configuration
-- ('ConfigData') and the last 'FStat' of its file.
data ConfigState = ConfigState
  { csConfigData :: ConfigData
  }
  deriving (Eq, Show)

$(makeCustomLenses ''ConfigState)

-- | Creates a new configuration state.
-- This method will expand as more fields are added to 'ConfigState'.
mkConfigState :: ConfigData -> ConfigState
mkConfigState = ConfigState

bumpSerial :: (SerialNoObjectL a, TimeStampObjectL a) => ClockTime -> a -> a
bumpSerial now = set mTimeL now . over serialL succ

-- | Given two versions of the configuration, determine if its distribution
-- needs to be fully commited before returning the corresponding call to
-- WConfD.
needsFullDist :: ConfigState -> ConfigState -> Bool
needsFullDist = on (/=) (watched . csConfigData)
  where
    watched = (,,,,,,)
              <$> clusterCandidateCerts . configCluster
              <*> clusterMasterNode . configCluster
              <*> getMasterNodes
              <*> getMasterCandidates
              -- kvmd is running depending on the following:
              <*> clusterEnabledUserShutdown . configCluster
              <*> clusterEnabledHypervisors . configCluster
              <*> fmap nodeVmCapable . configNodes

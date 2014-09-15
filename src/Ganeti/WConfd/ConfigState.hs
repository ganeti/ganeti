{-# LANGUAGE TemplateHaskell #-}

{-| Pure functions for manipulating the configuration state.

-}

{-

Copyright (C) 2014 Google Inc.
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

{-| Algorithm Options for HTools

This module describes the parameters that influence the balancing
algorithm in htools.

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

module Ganeti.HTools.AlgorithmParams
  ( AlgorithmOptions(..)
  , defaultOptions
  , fromCLIOptions
  ) where

import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Types as T

data AlgorithmOptions = AlgorithmOptions
  { algDiskMoves :: Bool            -- ^ Whether disk moves are allowed
  , algInstanceMoves :: Bool        -- ^ Whether instance moves are allowed
  , algRestrictedMigration :: Bool  -- ^ Whether migration is restricted
  , algIgnoreSoftErrors :: Bool     -- ^ Whether to always ignore soft errors
  , algEvacMode :: Bool             -- ^ Consider only eavacation moves
  , algMinGain :: Double            -- ^ Minimal gain per balancing step
  , algMinGainLimit :: Double       -- ^ Limit below which minimal gain is used
  , algCapacity :: Bool             -- ^ Whether to check capacity properties,
                                    -- like global N+1 redundancy
  , algCapacityIgnoreGroups :: [T.Gdx] -- ^ Groups to ignore in capacity checks
  , algRestrictToNodes :: Maybe [String] -- ^ nodes to restrict allocation to
  , algAcceptExisting :: Bool       -- ^ accept existing violations in capacity
                                    -- checks
  }

-- | Obtain the relevant algorithmic option from the commandline options
fromCLIOptions :: CLI.Options -> AlgorithmOptions
fromCLIOptions opts = AlgorithmOptions
  { algDiskMoves = CLI.optDiskMoves opts
  , algInstanceMoves = CLI.optInstMoves opts
  , algRestrictedMigration = CLI.optRestrictedMigrate opts
  , algIgnoreSoftErrors = CLI.optIgnoreSoftErrors opts
  , algEvacMode = CLI.optEvacMode opts
  , algMinGain = CLI.optMinGain opts
  , algMinGainLimit = CLI.optMinGainLim opts
  , algCapacity = CLI.optCapacity opts
  , algCapacityIgnoreGroups = []
  , algRestrictToNodes = CLI.optRestrictToNodes opts
  , algAcceptExisting = CLI.optAcceptExisting opts
  }

-- | Default options for the balancing algorithm
defaultOptions :: AlgorithmOptions
defaultOptions = fromCLIOptions CLI.defaultOptions

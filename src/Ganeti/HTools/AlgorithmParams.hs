{-| Algorithm Options for HTools

This module describes the parameters that influence the balancing
algorithm in htools.

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

module Ganeti.HTools.AlgorithmParams
  ( AlgorithmOptions(..)
  , defaultOptions
  , fromCLIOptions
  ) where

import qualified Ganeti.HTools.CLI as CLI

data AlgorithmOptions = AlgorithmOptions
  { algDiskMoves :: Bool            -- ^ Whether disk moves are allowed
  , algInstanceMoves :: Bool        -- ^ Whether instance moves are allowed
  , algRestrictedMigration :: Bool  -- ^ Whether migration is restricted
  , algIgnoreSoftErrors :: Bool     -- ^ Whether to always ignore soft errors
  , algEvacMode :: Bool             -- ^ Consider only eavacation moves
  , algMinGain :: Double            -- ^ Minimal gain per balancing step
  , algMinGainLimit :: Double       -- ^ Limit below which minimal gain is used
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
  }

-- | Default options for the balancing algorithm
defaultOptions :: AlgorithmOptions
defaultOptions = fromCLIOptions CLI.defaultOptions

{-| Implementation of DataCollectors CLI functions.

This module holds the common command-line related functions for the
collector binaries.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Ganeti.DataCollectors.CLI
  ( Options(..)
  , OptType
  , defaultOptions
  -- * The options
  , oShowHelp
  , oShowVer
  , oShowComp
  , oDrbdPairing
  , oDrbdStatus
  , oNode
  , oConfdAddr
  , oConfdPort
  , genericOptions
  ) where

import System.Console.GetOpt

import Ganeti.BasicTypes
import Ganeti.Common as Common
import Ganeti.Utils


-- * Data types

-- | Command line options structure.
data Options = Options
  { optShowHelp    :: Bool           -- ^ Just show the help
  , optShowComp    :: Bool           -- ^ Just show the completion info
  , optShowVer     :: Bool           -- ^ Just show the program version
  , optDrbdStatus  :: Maybe FilePath -- ^ Path to the file containing DRBD
                                     -- status information
  , optDrbdPairing :: Maybe FilePath -- ^ Path to the file containing pairings
                                     -- between instances and DRBD minors
  , optNode        :: Maybe String   -- ^ Info are requested for this node
  , optConfdAddr   :: Maybe String   -- ^ IP address of the Confd server
  , optConfdPort   :: Maybe Int      -- ^ The port of the Confd server to
                                     -- connect to
  } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
  { optShowHelp    = False
  , optShowComp    = False
  , optShowVer     = False
  , optDrbdStatus  = Nothing
  , optDrbdPairing = Nothing
  , optNode        = Nothing
  , optConfdAddr   = Nothing
  , optConfdPort   = Nothing
  }

-- | Abbreviation for the option type.
type OptType = GenericOptType Options

instance StandardOptions Options where
  helpRequested = optShowHelp
  verRequested  = optShowVer
  compRequested = optShowComp
  requestHelp o = o { optShowHelp = True }
  requestVer  o = o { optShowVer  = True }
  requestComp o = o { optShowComp = True }

-- * Command line options
oDrbdPairing :: OptType
oDrbdPairing =
  ( Option "p" ["drbd-pairing"]
      (ReqArg (\ f o -> Ok o { optDrbdPairing = Just f}) "FILE")
      "the FILE containing pairings between instances and DRBD minors",
    OptComplFile)

oDrbdStatus :: OptType
oDrbdStatus =
  ( Option "s" ["drbd-status"]
      (ReqArg (\ f o -> Ok o { optDrbdStatus = Just f }) "FILE")
      "the DRBD status FILE",
    OptComplFile)

oNode :: OptType
oNode =
  ( Option "n" ["node"]
      (ReqArg (\ n o -> Ok o { optNode = Just n }) "NODE")
      "the FQDN of the NODE about which information is requested",
    OptComplFile)

oConfdAddr :: OptType
oConfdAddr =
  ( Option "a" ["address"]
      (ReqArg (\ a o -> Ok o { optConfdAddr = Just a }) "IP_ADDR")
      "the IP address of the Confd server to connect to",
    OptComplFile)

oConfdPort :: OptType
oConfdPort =
  (Option "p" ["port"]
    (reqWithConversion (tryRead "reading port")
      (\port opts -> Ok opts { optConfdPort = Just port }) "PORT")
    "Network port of the Confd server to connect to",
    OptComplInteger)

-- | Generic options.
genericOptions :: [GenericOptType Options]
genericOptions =  [ oShowVer
                  , oShowHelp
                  , oShowComp
                  ]

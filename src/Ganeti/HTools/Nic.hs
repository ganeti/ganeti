{-| Module describing an NIC.

The NIC data type only holds data about a NIC, but does not provide any
logic.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Ganeti.HTools.Nic
  ( Nic(..)
  , Mode(..)
  , List
  , create
  ) where

import qualified Ganeti.HTools.Container as Container

import qualified Ganeti.HTools.Types as T

-- * Type declarations

data Mode = Bridged | Routed | OpenVSwitch deriving (Show, Eq)

-- | The NIC type.
--
-- It holds the data for a NIC as it is provided via the IAllocator protocol
-- for an instance creation request. All data in those request is optional,
-- that's why all fields are Maybe's.
--
-- TODO: Another name might be more appropriate for this type, as for example
-- RequestedNic. But this type is used as a field in the Instance type, which
-- is not named RequestedInstance, so such a name would be weird. PartialNic
-- already exists in Objects, but doesn't fit the bill here, as it contains
-- a required field (mac). Objects and the types therein are subject to being
-- reworked, so until then this type is left as is.
data Nic = Nic
  { mac          :: Maybe String -- ^ MAC address of the NIC
  , ip           :: Maybe String -- ^ IP address of the NIC
  , mode         :: Maybe Mode   -- ^ the mode the NIC operates in
  , link         :: Maybe String -- ^ the link of the NIC
  , bridge       :: Maybe String -- ^ the bridge this NIC is connected to if
                                 --   the mode is Bridged
  , network      :: Maybe T.NetworkID -- ^ network UUID if this NIC is connected
                                 --   to a network
  } deriving (Show, Eq)

-- | A simple name for an instance map.
type List = Container.Container Nic

-- * Initialization

-- | Create a NIC.
--
create :: Maybe String
       -> Maybe String
       -> Maybe Mode
       -> Maybe String
       -> Maybe String
       -> Maybe T.NetworkID
       -> Nic
create mac_init ip_init mode_init link_init bridge_init network_init =
  Nic { mac = mac_init
      , ip = ip_init
      , mode = mode_init
      , link = link_init
      , bridge = bridge_init
      , network = network_init
      }

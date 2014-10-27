{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti Instance config object.

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

module Ganeti.Objects.Instance where

import Ganeti.Objects.Nic
import Ganeti.THH
import Ganeti.THH.Field
import Ganeti.Types
import Ganeti.Utils (parseUnitAssumeBinary)

$(buildParam "Be" "bep"
  [ specialNumericalField 'parseUnitAssumeBinary
      $ simpleField "minmem"      [t| Int  |]
  , specialNumericalField 'parseUnitAssumeBinary
      $ simpleField "maxmem"      [t| Int  |]
  , simpleField "vcpus"           [t| Int  |]
  , simpleField "auto_balance"    [t| Bool |]
  , simpleField "always_failover" [t| Bool |]
  , simpleField "spindle_use"     [t| Int  |]
  ])

$(buildObject "Instance" "inst" $
  [ simpleField "name"             [t| String             |]
  , simpleField "primary_node"     [t| String             |]
  , simpleField "os"               [t| String             |]
  , simpleField "hypervisor"       [t| Hypervisor         |]
  , simpleField "hvparams"         [t| HvParams           |]
  , simpleField "beparams"         [t| PartialBeParams    |]
  , simpleField "osparams"         [t| OsParams           |]
  , simpleField "osparams_private" [t| OsParamsPrivate    |]
  , simpleField "admin_state"      [t| AdminState         |]
  , simpleField "admin_state_source" [t| AdminStateSource   |]
  , simpleField "nics"             [t| [PartialNic]       |]
  , simpleField "disks"            [t| [String]           |]
  , simpleField "disk_template"    [t| DiskTemplate       |]
  , simpleField "disks_active"     [t| Bool               |]
  , optionalField $ simpleField "network_port" [t| Int  |]
  ]
  ++ timeStampFields
  ++ uuidFields
  ++ serialFields
  ++ tagsFields)

instance TimeStampObject Instance where
  cTimeOf = instCtime
  mTimeOf = instMtime

instance UuidObject Instance where
  uuidOf = instUuid

instance SerialNoObject Instance where
  serialOf = instSerial

instance TagsObject Instance where
  tagsOf = instTags

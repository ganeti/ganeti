{-# LANGUAGE TemplateHaskell #-}
{-| Type declarations specific for the instance status data collector.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.DataCollectors.InstStatusTypes
  ( InstStatus(..)
  , ReportData(..)
  ) where


import Ganeti.DataCollectors.Types
import Ganeti.Hypervisor.Xen.Types
import Ganeti.THH
import Ganeti.THH.Field
import Ganeti.Types

-- | Data type representing the status of an instance to be returned.
$(buildObject "InstStatus" "iStat"
  [ simpleField "name"         [t| String |]
  , simpleField "uuid"         [t| String |]
  , simpleField "adminState"   [t| AdminState |]
  , simpleField "actualState"  [t| ActualState |]
  , optionalNullSerField $
    simpleField "uptime"       [t| String |]
  , timeAsDoubleField "mtime"
  , simpleField "state_reason" [t| ReasonTrail |]
  , simpleField "status"       [t| DCStatus |]
  ])

$(buildObject "ReportData" "rData"
  [ simpleField "instances" [t| [InstStatus] |]
  , simpleField "status"    [t| DCStatus |]
  ])

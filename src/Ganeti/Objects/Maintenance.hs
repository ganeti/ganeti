{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti configuration for the maintenance daemon.

-}

{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.Objects.Maintenance
  ( MaintenanceData(..)
  , RepairAction(..)
  , RepairStatus(..)
  , Incident(..)
  ) where

import qualified Data.ByteString.UTF8 as UTF8
import qualified Text.JSON as J

import qualified Ganeti.Constants as C
import Ganeti.THH
import Ganeti.THH.Field
import Ganeti.Types

-- | Action to be taken for a certain repair event. Note
-- that the order is important, as we rely on values higher
-- in the derived order to be more intrusive actions.
$(declareLADT ''String "RepairAction"
    [ ("RANoop", "Ok")
    , ("RALiveRepair", "live-repair")
    , ("RAEvacuate", "evacuate")
    , ("RAEvacuateFailover", "evacuate-failover")
    ])
$(makeJSONInstance ''RepairAction)

-- | Progress made on the particular repair event. Again we rely
-- on the order in that everything larger than `RSPending` is finalized
-- in the sense that no further jobs will be submitted.
$(declareLADT ''String "RepairStatus"
   [ ("RSNoted", "noted")
   , ("RSPending", "pending")
   , ("RSCanceled", "canceled")
   , ("RSFailed", "failed")
   , ("RSCompleted", "completed")
   ])
$(makeJSONInstance ''RepairStatus)

$(buildObject "Incident" "incident" $
   [ simpleField "original" [t| J.JSValue |]
   , simpleField "action" [t| RepairAction |]
   , defaultField [| [] |] $ simpleField "jobs" [t| [ JobId ] |]
   , simpleField "node" [t| String |]
   , simpleField "repair-status" [t| RepairStatus |]
   , simpleField "tag" [t| String |]
   ]
   ++ uuidFields
   ++ timeStampFields
   ++ serialFields)

instance SerialNoObject Incident where
  serialOf = incidentSerial

instance TimeStampObject Incident where
  cTimeOf = incidentCtime
  mTimeOf = incidentMtime

instance UuidObject Incident where
  uuidOf = UTF8.toString . incidentUuid

$(buildObject "MaintenanceData" "maint" $
  [ defaultField [| C.maintdDefaultRoundDelay |]
    $ simpleField "roundDelay" [t| Int |]
  , defaultField [| [] |] $ simpleField "jobs" [t| [ JobId ] |]
  , defaultField [| False |] $ simpleField "balance" [t| Bool |]
  , defaultField [| 0.1 :: Double |]
    $ simpleField "balanceThreshold" [t| Double |]
  , defaultField [| [] |] $ simpleField "evacuated" [t| [ String ] |]
  , defaultField [| [] |] $ simpleField "incidents" [t| [ Incident ] |]
  ]
  ++ timeStampFields
  ++ serialFields)

instance SerialNoObject MaintenanceData where
  serialOf = maintSerial

instance TimeStampObject MaintenanceData where
  cTimeOf = maintCtime
  mTimeOf = maintMtime

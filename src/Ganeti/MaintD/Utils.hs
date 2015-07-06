{-| Utility functions for the maintenance daemon.

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

module Ganeti.MaintD.Utils
  ( annotateOpCode
  ) where

import Control.Lens.Setter (over)

import qualified Ganeti.Constants as C
import Ganeti.JQueue (reasonTrailTimestamp)
import Ganeti.JQueue.Objects (Timestamp)
import Ganeti.OpCodes (OpCode, MetaOpCode, wrapOpCode)
import Ganeti.OpCodes.Lens (metaParamsL, opReasonL)

-- | Wrap an `OpCode` into a `MetaOpCode` and adding an indication
-- that the `OpCode` was submitted by the maintenance daemon.
annotateOpCode :: String -> Timestamp -> OpCode -> MetaOpCode
annotateOpCode reason ts =
  over (metaParamsL . opReasonL)
    (++ [(C.opcodeReasonSrcMaintd, reason, reasonTrailTimestamp ts)])
  . wrapOpCode

{-# LANGUAGE TemplateHaskell, StandaloneDeriving #-}

{-| Objects in the job queue.

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

module Ganeti.JQueue.Objects
    ( Timestamp
    , InputOpCode(..)
    , QueuedOpCode(..)
    , QueuedJob(..)
    ) where

import Prelude hiding (id, log)
import qualified Text.JSON
import Text.JSON.Types

import Ganeti.THH
import Ganeti.THH.Field
import Ganeti.Types
import Ganeti.OpCodes

-- | The ganeti queue timestamp type. It represents the time as the pair
-- of seconds since the epoch and microseconds since the beginning of the
-- second.
type Timestamp = (Int, Int)

-- | An input opcode.
data InputOpCode = ValidOpCode MetaOpCode -- ^ OpCode was parsed successfully
                 | InvalidOpCode JSValue  -- ^ Invalid opcode
                   deriving (Show, Eq, Ord)

-- | JSON instance for 'InputOpCode', trying to parse it and if
-- failing, keeping the original JSValue.
instance Text.JSON.JSON InputOpCode where
  showJSON (ValidOpCode mo) = Text.JSON.showJSON mo
  showJSON (InvalidOpCode inv) = inv
  readJSON v = case Text.JSON.readJSON v of
                 Text.JSON.Error _ -> return $ InvalidOpCode v
                 Text.JSON.Ok mo -> return $ ValidOpCode mo

$(buildObject "QueuedOpCode" "qo"
  [ simpleField "input"           [t| InputOpCode |]
  , simpleField "status"          [t| OpStatus    |]
  , simpleField "result"          [t| JSValue     |]
  , defaultField [| [] |] $
    simpleField "log"             [t| [(Int, Timestamp, ELogType, JSValue)] |]
  , simpleField "priority"        [t| Int         |]
  , optionalNullSerField $
    simpleField "start_timestamp" [t| Timestamp   |]
  , optionalNullSerField $
    simpleField "exec_timestamp"  [t| Timestamp   |]
  , optionalNullSerField $
    simpleField "end_timestamp"   [t| Timestamp   |]
  ])

deriving instance Ord QueuedOpCode

$(buildObject "QueuedJob" "qj"
  [ simpleField "id"                 [t| JobId          |]
  , simpleField "ops"                [t| [QueuedOpCode] |]
  , optionalNullSerField $
    simpleField "received_timestamp" [t| Timestamp      |]
  , optionalNullSerField $
    simpleField "start_timestamp"    [t| Timestamp      |]
  , optionalNullSerField $
    simpleField "end_timestamp"      [t| Timestamp      |]
  , optionalField $
    simpleField "livelock"           [t| FilePath      |]
  , optionalField $ processIdField "process_id"
  ])

deriving instance Ord QueuedJob

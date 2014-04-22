{-# LANGUAGE TemplateHaskell #-}

{-| Objects in the job queue.

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
                   deriving (Show, Eq)

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


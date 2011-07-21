{-| Implementation of the job information.

-}

{-

Copyright (C) 2009, 2010, 2011 Google Inc.

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

module Ganeti.Jobs
    ( OpStatus(..)
    , JobStatus(..)
    ) where

import Text.JSON (readJSON, showJSON, JSON)
import qualified Text.JSON as J

import qualified Ganeti.Constants as C

-- | Our ADT for the OpCode status at runtime (while in a job).
data OpStatus = OP_STATUS_QUEUED
              | OP_STATUS_WAITING
              | OP_STATUS_CANCELING
              | OP_STATUS_RUNNING
              | OP_STATUS_CANCELED
              | OP_STATUS_SUCCESS
              | OP_STATUS_ERROR
                deriving (Eq, Enum, Bounded, Show, Read)

instance JSON OpStatus where
    showJSON os = showJSON w
      where w = case os of
              OP_STATUS_QUEUED    -> C.opStatusQueued
              OP_STATUS_WAITING   -> C.opStatusWaiting
              OP_STATUS_CANCELING -> C.opStatusCanceling
              OP_STATUS_RUNNING   -> C.opStatusRunning
              OP_STATUS_CANCELED  -> C.opStatusCanceled
              OP_STATUS_SUCCESS   -> C.opStatusSuccess
              OP_STATUS_ERROR     -> C.opStatusError
    readJSON s = case readJSON s of
      J.Ok v | v == C.opStatusQueued    -> J.Ok OP_STATUS_QUEUED
             | v == C.opStatusWaiting   -> J.Ok OP_STATUS_WAITING
             | v == C.opStatusCanceling -> J.Ok OP_STATUS_CANCELING
             | v == C.opStatusRunning   -> J.Ok OP_STATUS_RUNNING
             | v == C.opStatusCanceled  -> J.Ok OP_STATUS_CANCELED
             | v == C.opStatusSuccess   -> J.Ok OP_STATUS_SUCCESS
             | v == C.opStatusError     -> J.Ok OP_STATUS_ERROR
             | otherwise -> J.Error ("Unknown opcode status " ++ v)
      _ -> J.Error ("Cannot parse opcode status " ++ show s)

-- | The JobStatus data type. Note that this is ordered especially
-- such that greater\/lesser comparison on values of this type makes
-- sense.
data JobStatus = JOB_STATUS_QUEUED
               | JOB_STATUS_WAITING
               | JOB_STATUS_RUNNING
               | JOB_STATUS_SUCCESS
               | JOB_STATUS_CANCELING
               | JOB_STATUS_CANCELED
               | JOB_STATUS_ERROR
                 deriving (Eq, Enum, Ord, Bounded, Show, Read)

instance JSON JobStatus where
    showJSON js = showJSON w
        where w = case js of
                JOB_STATUS_QUEUED    -> C.jobStatusQueued
                JOB_STATUS_WAITING   -> C.jobStatusWaiting
                JOB_STATUS_CANCELING -> C.jobStatusCanceling
                JOB_STATUS_RUNNING   -> C.jobStatusRunning
                JOB_STATUS_CANCELED  -> C.jobStatusCanceled
                JOB_STATUS_SUCCESS   -> C.jobStatusSuccess
                JOB_STATUS_ERROR     -> C.jobStatusError
    readJSON s = case readJSON s of
      J.Ok v | v == C.jobStatusQueued    -> J.Ok JOB_STATUS_QUEUED
             | v == C.jobStatusWaiting   -> J.Ok JOB_STATUS_WAITING
             | v == C.jobStatusCanceling -> J.Ok JOB_STATUS_CANCELING
             | v == C.jobStatusRunning   -> J.Ok JOB_STATUS_RUNNING
             | v == C.jobStatusSuccess   -> J.Ok JOB_STATUS_SUCCESS
             | v == C.jobStatusCanceled  -> J.Ok JOB_STATUS_CANCELED
             | v == C.jobStatusError     -> J.Ok JOB_STATUS_ERROR
             | otherwise -> J.Error ("Unknown job status " ++ v)
      _ -> J.Error ("Unknown job status " ++ show s)

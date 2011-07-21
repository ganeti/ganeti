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
              OP_STATUS_QUEUED -> C.jobStatusQueued
              OP_STATUS_WAITING -> C.jobStatusWaiting
              OP_STATUS_CANCELING -> C.jobStatusCanceling
              OP_STATUS_RUNNING -> C.jobStatusRunning
              OP_STATUS_CANCELED -> C.jobStatusCanceled
              OP_STATUS_SUCCESS -> C.jobStatusSuccess
              OP_STATUS_ERROR -> C.jobStatusError
    readJSON s = case readJSON s of
      J.Ok v | v == C.jobStatusQueued -> J.Ok OP_STATUS_QUEUED
             | v == C.jobStatusWaiting -> J.Ok OP_STATUS_WAITING
             | v == C.jobStatusCanceling -> J.Ok OP_STATUS_CANCELING
             | v == C.jobStatusRunning -> J.Ok OP_STATUS_RUNNING
             | v == C.jobStatusCanceled -> J.Ok OP_STATUS_CANCELED
             | v == C.jobStatusSuccess -> J.Ok OP_STATUS_SUCCESS
             | v == C.jobStatusError -> J.Ok OP_STATUS_ERROR
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
                JOB_STATUS_QUEUED -> "queued"
                JOB_STATUS_WAITING -> "waiting"
                JOB_STATUS_CANCELING -> "canceling"
                JOB_STATUS_RUNNING -> "running"
                JOB_STATUS_CANCELED -> "canceled"
                JOB_STATUS_SUCCESS -> "success"
                JOB_STATUS_ERROR -> "error"
    readJSON s = case readJSON s of
      J.Ok "queued" -> J.Ok JOB_STATUS_QUEUED
      J.Ok "waiting" -> J.Ok JOB_STATUS_WAITING
      J.Ok "canceling" -> J.Ok JOB_STATUS_CANCELING
      J.Ok "running" -> J.Ok JOB_STATUS_RUNNING
      J.Ok "success" -> J.Ok JOB_STATUS_SUCCESS
      J.Ok "canceled" -> J.Ok JOB_STATUS_CANCELED
      J.Ok "error" -> J.Ok JOB_STATUS_ERROR
      _ -> J.Error ("Unknown job status " ++ show s)

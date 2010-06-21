{-| Implementation of the job information.

-}

{-

Copyright (C) 2009 Google Inc.

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
    ( JobStatus(..)
    ) where

import Text.JSON (readJSON, showJSON, JSON)
import qualified Text.JSON as J

-- | The JobStatus data type. Note that this is ordered especially
-- such that greater\/lesser comparison on values of this type makes
-- sense.
data JobStatus = JOB_STATUS_QUEUED
               | JOB_STATUS_WAITLOCK
               | JOB_STATUS_RUNNING
               | JOB_STATUS_SUCCESS
               | JOB_STATUS_CANCELING
               | JOB_STATUS_CANCELED
               | JOB_STATUS_ERROR
               | JOB_STATUS_GONE
                 deriving (Eq, Enum, Ord, Bounded, Show)

instance JSON JobStatus where
    showJSON js = showJSON w
        where w = case js of
                JOB_STATUS_QUEUED -> "queued"
                JOB_STATUS_WAITLOCK -> "waiting"
                JOB_STATUS_CANCELING -> "canceling"
                JOB_STATUS_RUNNING -> "running"
                JOB_STATUS_CANCELED -> "canceled"
                JOB_STATUS_SUCCESS -> "success"
                JOB_STATUS_ERROR -> "error"
                JOB_STATUS_GONE -> "gone" -- Fake status
    readJSON s = case readJSON s of
      J.Ok "queued" -> J.Ok JOB_STATUS_QUEUED
      J.Ok "waiting" -> J.Ok JOB_STATUS_WAITLOCK
      J.Ok "canceling" -> J.Ok JOB_STATUS_CANCELING
      J.Ok "running" -> J.Ok JOB_STATUS_RUNNING
      J.Ok "success" -> J.Ok JOB_STATUS_SUCCESS
      J.Ok "canceled" -> J.Ok JOB_STATUS_CANCELED
      J.Ok "error" -> J.Ok JOB_STATUS_ERROR
      _ -> J.Error ("Unknown job status " ++ show s)

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
data JobStatus = JobQueued
               | JobWaitLock
               | JobRunning
               | JobSuccess
               | JobCanceling
               | JobCanceled
               | JobError
               | JobGone
                 deriving (Eq, Enum, Ord, Bounded, Show)

instance JSON JobStatus where
    showJSON js = showJSON w
        where w = case js of
                    JobQueued -> "queued"
                    JobWaitLock -> "waiting"
                    JobCanceling -> "canceling"
                    JobRunning -> "running"
                    JobCanceled -> "canceled"
                    JobSuccess -> "success"
                    JobError -> "error"
                    JobGone -> "gone" -- Fake status
    readJSON s = case readJSON s of
                   J.Ok "queued" -> J.Ok JobQueued
                   J.Ok "waiting" -> J.Ok JobWaitLock
                   J.Ok "canceling" -> J.Ok JobCanceling
                   J.Ok "running" -> J.Ok JobRunning
                   J.Ok "success" -> J.Ok JobSuccess
                   J.Ok "canceled" -> J.Ok JobCanceled
                   J.Ok "error" -> J.Ok JobError
                   _ -> J.Error ("Unkown job status " ++ show s)

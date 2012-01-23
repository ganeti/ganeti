{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the job information.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

import qualified Ganeti.Constants as C
import qualified Ganeti.THH as THH

-- | Our ADT for the OpCode status at runtime (while in a job).
$(THH.declareSADT "OpStatus"
       [ ("OP_STATUS_QUEUED",    'C.opStatusQueued)
       , ("OP_STATUS_WAITING",   'C.opStatusWaiting)
       , ("OP_STATUS_CANCELING", 'C.opStatusCanceling)
       , ("OP_STATUS_RUNNING",   'C.opStatusRunning)
       , ("OP_STATUS_CANCELED",  'C.opStatusCanceled)
       , ("OP_STATUS_SUCCESS",   'C.opStatusSuccess)
       , ("OP_STATUS_ERROR",     'C.opStatusError)
       ])
$(THH.makeJSONInstance ''OpStatus)

-- | The JobStatus data type. Note that this is ordered especially
-- such that greater\/lesser comparison on values of this type makes
-- sense.
$(THH.declareSADT "JobStatus"
       [ ("JOB_STATUS_QUEUED",    'C.jobStatusQueued)
       , ("JOB_STATUS_WAITING",   'C.jobStatusWaiting)
       , ("JOB_STATUS_CANCELING", 'C.jobStatusCanceling)
       , ("JOB_STATUS_RUNNING",   'C.jobStatusRunning)
       , ("JOB_STATUS_CANCELED",  'C.jobStatusCanceled)
       , ("JOB_STATUS_SUCCESS",   'C.jobStatusSuccess)
       , ("JOB_STATUS_ERROR",     'C.jobStatusError)
       ])
$(THH.makeJSONInstance ''JobStatus)

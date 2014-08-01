{-| Unittests for 'Ganeti.JQueue.Objects'.

-}

{-

Copyright (C) 2012, 2013 Google Inc.

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

module Test.Ganeti.JQueue.Objects
  ( justNoTs
  , genQueuedOpCode
  , emptyJob
  , genJobId
  ) where

import Control.Applicative
import Test.QuickCheck as QuickCheck
import Text.JSON

import Test.Ganeti.Types ()
import Test.Ganeti.OpCodes ()

import qualified Ganeti.Constants as C
import Ganeti.JQueue
import Ganeti.Types as Types

-- | noTimestamp in Just form.
justNoTs :: Maybe Timestamp
justNoTs = Just noTimestamp

-- | Generates a simple queued opcode.
genQueuedOpCode :: Gen QueuedOpCode
genQueuedOpCode =
  QueuedOpCode <$> (ValidOpCode <$> arbitrary) <*>
    arbitrary <*> pure JSNull <*> pure [] <*>
    choose (C.opPrioLowest, C.opPrioHighest) <*>
    pure justNoTs <*> pure justNoTs <*> pure justNoTs

-- | Generates an static, empty job.
emptyJob :: (Monad m) => m QueuedJob
emptyJob = do
  jid0 <- makeJobId 0
  return $ QueuedJob jid0 [] justNoTs justNoTs justNoTs Nothing Nothing

-- | Generates a job ID.
genJobId :: Gen JobId
genJobId = do
  p <- arbitrary::Gen (Types.NonNegative Int)
  makeJobId $ fromNonNegative p

{-| Unittests for 'Ganeti.JQueue.Objects'.

-}

{-

Copyright (C) 2012, 2013 Google Inc.
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

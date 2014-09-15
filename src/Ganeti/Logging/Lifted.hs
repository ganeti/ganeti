{-| Ganeti logging functions expressed using MonadBase

This allows to use logging functions without having instances for all
possible transformers.

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

module Ganeti.Logging.Lifted
  ( MonadLog()
  , Priority(..)
  , L.withErrorLogAt
  , L.isDebugMode
  , logAt
  , logDebug
  , logInfo
  , logNotice
  , logWarning
  , logError
  , logCritical
  , logAlert
  , logEmergency
  ) where

import Control.Monad.Base

import Ganeti.Logging (MonadLog, Priority(..))
import qualified Ganeti.Logging as L

-- * Logging function aliases for MonadBase

-- | A monad that allows logging.
logAt :: (MonadLog b, MonadBase b m) => Priority -> String -> m ()
logAt p = liftBase . L.logAt p

-- | Log at debug level.
logDebug :: (MonadLog b, MonadBase b m) => String -> m ()
logDebug = logAt DEBUG

-- | Log at info level.
logInfo :: (MonadLog b, MonadBase b m) => String -> m ()
logInfo = logAt INFO

-- | Log at notice level.
logNotice :: (MonadLog b, MonadBase b m) => String -> m ()
logNotice = logAt NOTICE

-- | Log at warning level.
logWarning :: (MonadLog b, MonadBase b m) => String -> m ()
logWarning = logAt WARNING

-- | Log at error level.
logError :: (MonadLog b, MonadBase b m) => String -> m ()
logError = logAt ERROR

-- | Log at critical level.
logCritical :: (MonadLog b, MonadBase b m) => String -> m ()
logCritical = logAt CRITICAL

-- | Log at alert level.
logAlert :: (MonadLog b, MonadBase b m) => String -> m ()
logAlert = logAt ALERT

-- | Log at emergency level.
logEmergency :: (MonadLog b, MonadBase b m) => String -> m ()
logEmergency = logAt EMERGENCY

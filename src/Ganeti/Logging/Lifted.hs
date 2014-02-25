{-| Ganeti logging functions expressed using MonadBase

This allows to use logging functions without having instances for all
possible transformers.

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

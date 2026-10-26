{-| Time utility functions. -}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Ganeti.Utils.Time
  ( getCurrentTime
  , getCurrentTimeUSec
  , clockTimeToString
  , clockTimeToCTime
  , clockTimeToUSec
  , cTimeToClockTime
  , diffClockTimes
  , addToClockTime
  , noTimeDiff
  , TimeDiff(..)
  ) where

import qualified System.Time as STime
import System.Time (ClockTime(..), getClockTime)

import Foreign.C.Types (CTime(CTime))
import System.Posix.Types (EpochTime)


-- | Returns the current time as an 'Integer' representing the number
-- of seconds from the Unix epoch.
getCurrentTime :: IO Integer
getCurrentTime = do
  TOD ctime _ <- getClockTime
  return ctime

-- | Returns the current time as an 'Integer' representing the number
-- of microseconds from the Unix epoch (hence the need for 'Integer').
getCurrentTimeUSec :: IO Integer
getCurrentTimeUSec = fmap clockTimeToUSec getClockTime

-- | Convert a ClockTime into a (seconds-only) timestamp.
clockTimeToString :: ClockTime -> String
clockTimeToString (TOD t _) = show t

-- | Convert a ClockTime into a (seconds-only) 'EpochTime' (AKA @time_t@).
clockTimeToCTime :: ClockTime -> EpochTime
clockTimeToCTime (TOD secs _) = fromInteger secs

-- | Convert a ClockTime the number of microseconds since the epoch.
clockTimeToUSec :: ClockTime -> Integer
clockTimeToUSec (TOD ctime pico) =
  -- pico: 10^-12, micro: 10^-6, so we have to shift seconds left and
  -- picoseconds right
  ctime * 1000000 + pico `div` 1000000

-- | Convert a ClockTime into a (seconds-only) 'EpochTime' (AKA @time_t@).
cTimeToClockTime :: EpochTime -> ClockTime
cTimeToClockTime (CTime timet) = TOD (toInteger timet) 0


{- |
Like 'System.Time.TimeDiff' but misses 'tdYear', 'tdMonth'.
Their meaning depends on the start date and causes bugs like this one:
<https://github.com/haskell/old-time/issues/18>
This type is much simpler and less error-prone.
Also, our 'tdSec' has type 'Integer', which cannot overflow.
Like in original 'System.Time.TimeDiff' picoseconds can be negative,
that is, TimeDiff's are not normalized by default.
-}
data TimeDiff = TimeDiff {tdSec :: Integer, tdPicosec :: Integer}
  deriving (Show)

noTimeDiff :: TimeDiff
noTimeDiff = TimeDiff 0 0

diffClockTimes :: ClockTime -> ClockTime -> TimeDiff
diffClockTimes (STime.TOD secA picoA) (STime.TOD secB picoB) =
  TimeDiff (secA-secB) (picoA-picoB)

addToClockTime :: TimeDiff -> ClockTime -> ClockTime
addToClockTime (TimeDiff secDiff picoDiff) (TOD secA picoA) =
  case divMod (picoA+picoDiff) (1000*1000*1000*1000) of
    (secD, picoB) ->
      TOD (secA+secDiff+secD) picoB

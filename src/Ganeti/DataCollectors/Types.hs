{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti data collector types.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.DataCollectors.Types
  ( DCReport(..)
  , buildReport
  ) where

import Data.Maybe
import Text.JSON

import Ganeti.Constants as C
import Ganeti.THH
import Ganeti.Utils (getCurrentTime)

-- | This is the format of the report produced by each data collector.
$(buildObject "DCReport" "dcReport"
  [ simpleField "name"           [t| String |]
  , simpleField "version"        [t| String |]
  , simpleField "format_version" [t| Int |]
  , simpleField "timestamp"      [t| Integer |]
  , simpleField "data"           [t| JSValue |]
  ])

-- | Utility function for building a report automatically adding the current
-- timestamp (rounded up to seconds).
-- If the version is not specified, it will be set to the value indicating
-- a builtin collector.
buildReport :: String -> Maybe String -> Int -> JSValue -> IO DCReport
buildReport name version format_version jsonData = do
  now <- getCurrentTime
  let timestamp = now * 1000000000 :: Integer
      ver = fromMaybe C.builtinDataCollectorVersion version
  return $ DCReport name ver format_version timestamp jsonData

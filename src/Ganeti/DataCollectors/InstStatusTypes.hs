{-# LANGUAGE TemplateHaskell #-}
{-| Type declarations specific for the instance status data collector.

-}

{-

Copyright (C) 2013 Google Inc.

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

module Ganeti.DataCollectors.InstStatusTypes
  ( InstStatus(..)
  ) where


import Ganeti.Objects
import Ganeti.THH

-- | Data type representing the status of an instance to be returned.
$(buildObject "InstStatus" "iStat"
  [ simpleField "name"         [t| String |]
  , simpleField "uuid"         [t| String |]
  , simpleField "adminState"   [t| AdminState |]
  , optionalNullSerField $
    simpleField "uptime"       [t| String |]
  , simpleField "mtime"        [t| Double |]
  ])

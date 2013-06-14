{-# LANGUAGE TemplateHaskell #-}
{-| Diskstats data types

This module holds the definition of the data types describing the status of the
disks according to the information contained in @/proc/diskstats@.

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
module Ganeti.Storage.Diskstats.Types
  ( Diskstats(..)
  ) where

import Ganeti.THH


-- | This is the format of the report produced by each data collector.
$(buildObject "Diskstats" "ds"
  [ simpleField "major"        [t| Int |]
  , simpleField "minor"        [t| Int |]
  , simpleField "name"         [t| String |]
  , simpleField "readsNum"        [t| Int |]
  , simpleField "mergedReads"  [t| Int |]
  , simpleField "secRead"      [t| Int |]
  , simpleField "timeRead"     [t| Int |]
  , simpleField "writes"       [t| Int |]
  , simpleField "mergedWrites" [t| Int |]
  , simpleField "secWritten"   [t| Int |]
  , simpleField "timeWrite"    [t| Int |]
  , simpleField "ios"          [t| Int |]
  , simpleField "timeIO"       [t| Int |]
  , simpleField "wIOmillis"    [t| Int |]
  ])

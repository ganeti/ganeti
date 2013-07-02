{-# LANGUAGE TemplateHaskell #-}
{-| LVM data types

This module holds the definition of the data types describing the status of the
disks according to LVM (and particularly the lvs tool).

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
module Ganeti.Storage.Lvm.Types
  ( LVInfo(..)
  ) where

import Ganeti.THH


-- | This is the format of the report produced by each data collector.
$(buildObject "LVInfo" "lvi"
  [ simpleField "uuid"              [t| String |]
  , simpleField "name"              [t| String |]
  , simpleField "attr"              [t| String |]
  , simpleField "major"             [t| Int |]
  , simpleField "minor"             [t| Int |]
  , simpleField "kernel_major"      [t| Int |]
  , simpleField "kernel_minor"      [t| Int |]
  , simpleField "size"              [t| Int |]
  , simpleField "seg_count"         [t| Int |]
  , simpleField "tags"              [t| String |]
  , simpleField "modules"           [t| String |]
  , simpleField "vg_uuid"           [t| String |]
  , simpleField "vg_name"           [t| String |]
  , simpleField "segtype"           [t| String |]
  , simpleField "seg_start"         [t| Int |]
  , simpleField "seg_start_pe"      [t| Int |]
  , simpleField "seg_size"          [t| Int |]
  , simpleField "seg_tags"          [t| String |]
  , simpleField "seg_pe_ranges"     [t| String |]
  , simpleField "devices"           [t| String |]
  , optionalNullSerField $
    simpleField "instance"          [t| String |]
  ])

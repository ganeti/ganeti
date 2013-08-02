{-# LANGUAGE TemplateHaskell #-}
{-| CPUload data types

This module holds the definition of the data types describing the CPU
load according to information collected periodically from @/proc/stat@.

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
module Ganeti.Cpu.Types
  ( CPUstat(..)
  , CPUavgload(..)
  ) where

import Ganeti.THH

-- | This is the format of the report produced by the cpu load
-- collector.
$(buildObject "CPUavgload" "cav"
  [ simpleField "cpu_number" [t| Int |]
  , simpleField "cpus"       [t| [Double] |]
  , simpleField "cpu_total"  [t| Double |]
  ])

-- | This is the format of the data parsed by the input file.
$(buildObject "CPUstat" "cs"
  [ simpleField "name"       [t| String |]
  , simpleField "user"       [t| Int |]
  , simpleField "nice"       [t| Int |]
  , simpleField "system"     [t| Int |]
  , simpleField "idle"       [t| Int |]
  , simpleField "iowait"     [t| Int |]
  , simpleField "irq"        [t| Int |]
  , simpleField "softirq"    [t| Int |]
  , simpleField "steal"      [t| Int |]
  , simpleField "guest"      [t| Int |]
  , simpleField "guest_nice" [t| Int |]
  ])

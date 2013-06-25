{-| Small module holding program definitions for data collectors.

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

module Ganeti.DataCollectors.Program (personalities) where

import Ganeti.Common (PersonalityList)
import Ganeti.DataCollectors.CLI (Options)

import qualified Ganeti.DataCollectors.Diskstats as Diskstats
import qualified Ganeti.DataCollectors.Drbd as Drbd
import qualified Ganeti.DataCollectors.InstStatus as InstStatus
import qualified Ganeti.DataCollectors.Lv as Lv

-- | Supported binaries.
personalities :: PersonalityList Options
personalities = [ (Drbd.dcName, (Drbd.main, Drbd.options, Drbd.arguments,
                                 "gathers and displays DRBD statistics in JSON\
                                 \ format"))
                , (InstStatus.dcName, (InstStatus.main, InstStatus.options,
                                       InstStatus.arguments,
                                       "gathers and displays the status of the\
                                       \ instances in JSON format"))
                , (Diskstats.dcName, (Diskstats.main, Diskstats.options,
                                      Diskstats.arguments,
                                      "gathers and displays the disk usage\
                                      \ statistics in JSON format"))
                , (Lv.dcName, (Lv.main, Lv.options, Lv.arguments, "gathers and\
                               \ displays info about logical volumes"))
                ]

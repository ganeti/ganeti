{-| Small module holding program definitions for data collectors.

-}

{-

Copyright (C) 2012 Google Inc.
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

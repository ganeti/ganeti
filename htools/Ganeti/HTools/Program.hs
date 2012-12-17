{-| Small module holding program definitions.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.HTools.Program
  ( personalities
  ) where

import Ganeti.Common (PersonalityList)
import Ganeti.HTools.CLI (Options)

import qualified Ganeti.HTools.Program.Hail as Hail
import qualified Ganeti.HTools.Program.Hbal as Hbal
import qualified Ganeti.HTools.Program.Hcheck as Hcheck
import qualified Ganeti.HTools.Program.Hscan as Hscan
import qualified Ganeti.HTools.Program.Hspace as Hspace
import qualified Ganeti.HTools.Program.Hinfo as Hinfo

-- | Supported binaries.
personalities :: PersonalityList Options
personalities =
  [ ("hail",   (Hail.main,   Hail.options,   Hail.arguments,
                "Ganeti IAllocator plugin that implements the instance\
                \ placement and movement using the same algorithm as\
                \ hbal(1)"))
  , ("hbal",   (Hbal.main,   Hbal.options,   Hbal.arguments,
                "cluster balancer that looks at the current state of\
                \ the cluster and computes a series of steps designed\
                \ to bring the cluster into a better state"))
  , ("hcheck", (Hcheck.main, Hcheck.options, Hcheck.arguments,
               "cluster checker; prints information about cluster's\
               \ health and checks whether a rebalance done using\
               \ hbal would help"))
  , ("hscan",  (Hscan.main,  Hscan.options,  Hscan.arguments,
               "tool for scanning clusters via RAPI and saving their\
               \ data in the input format used by hbal(1) and hspace(1)"))
  , ("hspace", (Hspace.main, Hspace.options, Hspace.arguments,
               "computes how many additional instances can be fit on a\
               \ cluster, while maintaining N+1 status."))
  , ("hinfo",  (Hinfo.main,  Hinfo.options,  Hinfo.arguments,
               "cluster information printer; it prints information\
               \ about the current cluster state and its residing\
               \ nodes/instances"))
  ]

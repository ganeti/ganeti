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

import Ganeti.HTools.CLI (OptType, Options)

import qualified Ganeti.HTools.Program.Hail as Hail
import qualified Ganeti.HTools.Program.Hbal as Hbal
import qualified Ganeti.HTools.Program.Hcheck as Hcheck
import qualified Ganeti.HTools.Program.Hscan as Hscan
import qualified Ganeti.HTools.Program.Hspace as Hspace
import qualified Ganeti.HTools.Program.Hinfo as Hinfo

-- | Supported binaries.
personalities :: [(String, (Options -> [String] -> IO (), [OptType]))]
personalities = [ ("hail",   (Hail.main,   Hail.options))
                , ("hbal",   (Hbal.main,   Hbal.options))
                , ("hcheck", (Hcheck.main, Hcheck.options))
                , ("hscan",  (Hscan.main,  Hscan.options))
                , ("hspace", (Hspace.main, Hspace.options))
                , ("hinfo",  (Hinfo.main,  Hinfo.options))
                ]

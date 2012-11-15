{-| Cluster rolling maintenance helper.

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

module Ganeti.HTools.Program.Hroller
  ( main
  , options
  , arguments
  ) where

import Ganeti.Common
import Ganeti.HTools.CLI

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ luxi
    , oRapiMaster
    , oDataFile
    , oIAllocSrc
    , oOfflineNode
    , oVerbose
    , oQuiet
    , oNoHeaders
    , oSaveCluster
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = []

-- | Main function.
main :: Options -> [String] -> IO ()
main _ _ = return ()

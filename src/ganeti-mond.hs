{-# LANGUAGE TemplateHaskell #-}
{-| Ganeti monitoring agent daemon

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

module Main (main) where

import Data.List ((\\))

import Ganeti.Daemon
import Ganeti.DataCollectors (collectors)
import Ganeti.DataCollectors.Types (dName)
import Ganeti.Runtime
import qualified Ganeti.Monitoring.Server as S
import qualified Ganeti.Constants as C
import qualified Ganeti.ConstantUtils as CU

-- Check constistency of defined data collectors and their names used for the
-- Python constant generation:
$(let names = map dName collectors
      missing = names \\ CU.toList C.dataCollectorNames
  in if null missing
    then return []
    else fail $ "Please add " ++ show missing
              ++ " to the Ganeti.Constants.dataCollectorNames.")


-- | Options list and functions.
options :: [OptType]
options =
  [ oNoDaemonize
  , oNoUserChecks
  , oDebug
  , oBindAddress
  , oPort C.defaultMondPort
  ]

-- | Main function.
main :: IO ()
main =
  genericMain GanetiMond options
    S.checkMain
    S.prepMain
    S.main

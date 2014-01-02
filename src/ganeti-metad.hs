{-| Metadata daemon.

-}

{-

Copyright (C) 2014 Google Inc.

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

import qualified Ganeti.Constants as Constants
import Ganeti.Daemon (OptType)
import qualified Ganeti.Daemon as Daemon
import qualified Ganeti.Metad as Metad
import qualified Ganeti.Runtime as Runtime

options :: [OptType]
options =
  [ Daemon.oBindAddress
  , Daemon.oDebug
  , Daemon.oNoDaemonize
  , Daemon.oNoUserChecks
  , Daemon.oPort Constants.defaultMetadPort
  ]

main :: IO ()
main =
  Daemon.genericMain Runtime.GanetiMetad options
    (\_ -> return . Right $ ())
    (\_ _ -> return ())
    (\opts _ _ -> Metad.start opts)

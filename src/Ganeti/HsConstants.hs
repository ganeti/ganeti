{-| HsConstants contains the Haskell constants

This is a transitional module complementary to 'Ganeti.Constants'.  It
is intended to contain the Haskell constants that are meant to be
generated in Python.

Do not write any definitions in this file other than constants.  Do
not even write helper functions.  The definitions in this module are
automatically stripped to build the Makefile.am target
'ListConstants.hs'.  If there are helper functions in this module,
they will also be dragged and it will cause compilation to fail.
Therefore, all helper functions should go to a separate module and
imported.

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
module Ganeti.HsConstants where

import AutoConf
import Ganeti.ConstantUtils

-- * Admin states

adminstDown :: String
adminstDown = "down"

adminstOffline :: String
adminstOffline = "offline"

adminstUp :: String
adminstUp = "up"

adminstAll :: FrozenSet String
adminstAll = mkSet [adminstDown, adminstOffline, adminstUp]

-- * User separation

daemonsGroup :: String
daemonsGroup = AutoConf.daemonsGroup

adminGroup :: String
adminGroup = AutoConf.adminGroup

masterdUser :: String
masterdUser = AutoConf.masterdUser

masterdGroup :: String
masterdGroup = AutoConf.masterdGroup

rapiUser :: String
rapiUser = AutoConf.rapiUser

rapiGroup :: String
rapiGroup = AutoConf.rapiGroup

confdUser :: String
confdUser = AutoConf.confdUser

confdGroup :: String
confdGroup = AutoConf.confdGroup

luxidUser :: String
luxidUser = AutoConf.luxidUser

luxidGroup :: String
luxidGroup = AutoConf.luxidGroup

nodedUser :: String
nodedUser = AutoConf.nodedUser

nodedGroup :: String
nodedGroup = AutoConf.nodedGroup

mondUser :: String
mondUser = AutoConf.mondUser

mondGroup :: String
mondGroup = AutoConf.mondGroup

sshLoginUser :: String
sshLoginUser = AutoConf.sshLoginUser

sshConsoleUser :: String
sshConsoleUser = AutoConf.sshConsoleUser

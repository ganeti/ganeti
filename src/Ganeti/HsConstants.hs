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

import Data.Map (Map)
import qualified Data.Map as Map (fromList)

import AutoConf
import Ganeti.ConstantUtils (FrozenSet, Protocol(..))
import qualified Ganeti.ConstantUtils as ConstantUtils (mkSet, exitFailure)
import Ganeti.Runtime (GanetiDaemon(..), MiscGroup(..), GanetiGroup(..),
                       ExtraLogReason(..))
import qualified Ganeti.Runtime as Runtime

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
daemonsGroup = Runtime.daemonGroup (ExtraGroup DaemonsGroup)

adminGroup :: String
adminGroup = Runtime.daemonGroup (ExtraGroup AdminGroup)

masterdUser :: String
masterdUser = Runtime.daemonUser GanetiMasterd

masterdGroup :: String
masterdGroup = Runtime.daemonGroup (DaemonGroup GanetiMasterd)

rapiUser :: String
rapiUser = Runtime.daemonUser GanetiRapi

rapiGroup :: String
rapiGroup = Runtime.daemonGroup (DaemonGroup GanetiRapi)

confdUser :: String
confdUser = Runtime.daemonUser GanetiConfd

confdGroup :: String
confdGroup = Runtime.daemonGroup (DaemonGroup GanetiConfd)

luxidUser :: String
luxidUser = Runtime.daemonUser GanetiLuxid

luxidGroup :: String
luxidGroup = Runtime.daemonGroup (DaemonGroup GanetiLuxid)

nodedUser :: String
nodedUser = Runtime.daemonUser GanetiNoded

nodedGroup :: String
nodedGroup = Runtime.daemonGroup (DaemonGroup GanetiNoded)

mondUser :: String
mondUser = Runtime.daemonUser GanetiMond

mondGroup :: String
mondGroup = Runtime.daemonGroup (DaemonGroup GanetiMond)

sshLoginUser :: String
sshLoginUser = AutoConf.sshLoginUser

sshConsoleUser :: String
sshConsoleUser = AutoConf.sshConsoleUser

-- * SSH constants

ssh :: String
ssh = "ssh"

scp :: String
scp = "scp"

-- * Daemons

confd :: String
confd = Runtime.daemonName GanetiConfd

masterd :: String
masterd = Runtime.daemonName GanetiMasterd

mond :: String
mond = Runtime.daemonName GanetiMond

noded :: String
noded = Runtime.daemonName GanetiNoded

luxid :: String
luxid = Runtime.daemonName GanetiLuxid

rapi :: String
rapi = Runtime.daemonName GanetiRapi

daemons :: FrozenSet String
daemons =
  mkSet [confd,
         luxid,
         masterd,
         mond,
         noded,
         rapi]

defaultConfdPort :: Int
defaultConfdPort = 1814

defaultMondPort :: Int
defaultMondPort = 1815

defaultNodedPort :: Int
defaultNodedPort = 1811

defaultRapiPort :: Int
defaultRapiPort = 5080

daemonsPorts :: Map String (Protocol, Int)
daemonsPorts =
  Map.fromList [(confd, (Udp, defaultConfdPort)),
                (mond, (Tcp, defaultMondPort)),
                (noded, (Tcp, defaultNodedPort)),
                (rapi, (Tcp, defaultRapiPort)),
                (ssh, (Tcp, 22))]

extraLogreasonAccess :: String
extraLogreasonAccess = Runtime.daemonsExtraLogbase GanetiMond AccessLog

extraLogreasonError :: String
extraLogreasonError = Runtime.daemonsExtraLogbase GanetiMond ErrorLog

-- * Possible values for NodeGroup.alloc_policy

allocPolicyLastResort :: String
allocPolicyLastResort = "last_resort"

allocPolicyPreferred :: String
allocPolicyPreferred = "preferred"

allocPolicyUnallocable :: String
allocPolicyUnallocable = "unallocable"

validAllocPolicies :: [String]
validAllocPolicies =
  [allocPolicyLastResort,
   allocPolicyPreferred,
   allocPolicyUnallocable]

-- | Temporary external/shared storage parameters
blockdevDriverManual :: String
blockdevDriverManual = "manual"

-- * Auto-repair tag prefixes

autoRepairTagPrefix :: String
autoRepairTagPrefix = "ganeti:watcher:autorepair:"

autoRepairTagEnabled :: String
autoRepairTagEnabled = autoRepairTagPrefix

autoRepairTagPending :: String
autoRepairTagPending = autoRepairTagPrefix ++ "pending:"

autoRepairTagResult :: String
autoRepairTagResult = autoRepairTagPrefix ++ "result:"

autoRepairTagSuspended :: String
autoRepairTagSuspended = autoRepairTagPrefix ++ "suspend:"

-- * Auto-repair levels

autoRepairFailover :: String
autoRepairFailover = "failover"

autoRepairFixStorage :: String
autoRepairFixStorage = "fix-storage"

autoRepairMigrate :: String
autoRepairMigrate = "migrate"

autoRepairReinstall :: String
autoRepairReinstall = "reinstall"

autoRepairAllTypes :: FrozenSet String
autoRepairAllTypes =
  mkSet [autoRepairFailover,
         autoRepairFixStorage,
         autoRepairMigrate,
         autoRepairReinstall]

-- * Auto-repair results

autoRepairEnoperm :: String
autoRepairEnoperm = "enoperm"

autoRepairFailure :: String
autoRepairFailure = "failure"

autoRepairSuccess :: String
autoRepairSuccess = "success"

autoRepairAllResults :: FrozenSet String
autoRepairAllResults =
  mkSet [autoRepairEnoperm, autoRepairFailure, autoRepairSuccess]

-- | The version identifier for builtin data collectors
builtinDataCollectorVersion :: String
builtinDataCollectorVersion = "B"

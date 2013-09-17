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
import qualified Ganeti.ConstantUtils as ConstantUtils
import Ganeti.Runtime (GanetiDaemon(..), MiscGroup(..), GanetiGroup(..),
                       ExtraLogReason(..))
import Ganeti.Logging (SyslogUsage(..))
import qualified Ganeti.Logging as Logging (syslogUsageToRaw)
import qualified Ganeti.Runtime as Runtime
import Ganeti.Types
import qualified Ganeti.Types as Types

-- * OOB supported commands

oobPowerOn :: String
oobPowerOn = Types.oobCommandToRaw OobHealth

oobPowerOff :: String
oobPowerOff = Types.oobCommandToRaw OobPowerOff

oobPowerCycle :: String
oobPowerCycle = Types.oobCommandToRaw OobPowerOn

oobPowerStatus :: String
oobPowerStatus = Types.oobCommandToRaw OobPowerStatus

oobHealth :: String
oobHealth = Types.oobCommandToRaw OobHealth

oobCommands :: FrozenSet String
oobCommands = ConstantUtils.mkSet $ map Types.oobCommandToRaw [minBound..]

oobPowerStatusPowered :: String
oobPowerStatusPowered = "powered"

-- | 60 seconds
oobTimeout :: Int
oobTimeout = 60

-- | 2 seconds
oobPowerDelay :: Double
oobPowerDelay = 2.0

oobStatusCritical :: String
oobStatusCritical = Types.oobStatusToRaw OobStatusCritical

oobStatusOk :: String
oobStatusOk = Types.oobStatusToRaw OobStatusOk

oobStatusUnknown :: String
oobStatusUnknown = Types.oobStatusToRaw OobStatusUnknown

oobStatusWarning :: String
oobStatusWarning = Types.oobStatusToRaw OobStatusWarning

oobStatuses :: FrozenSet String
oobStatuses = ConstantUtils.mkSet $ map Types.oobStatusToRaw [minBound..]

-- * NIC_* constants are used inside the ganeti config

nicLink :: String
nicLink = "link"

nicMode :: String
nicMode = "mode"

nicVlan :: String
nicVlan = "vlan"

nicModeBridged :: String
nicModeBridged = Types.nICModeToRaw NMBridged

nicModeRouted :: String
nicModeRouted = Types.nICModeToRaw NMRouted

nicModeOvs :: String
nicModeOvs = Types.nICModeToRaw NMOvs

nicIpPool :: String
nicIpPool = Types.nICModeToRaw NMPool

nicValidModes :: FrozenSet String
nicValidModes = ConstantUtils.mkSet $ map Types.nICModeToRaw [minBound..]

-- * Hypervisor constants

htXenPvm :: String
htXenPvm = Types.hypervisorToRaw XenPvm

htFake :: String
htFake = Types.hypervisorToRaw Fake

htXenHvm :: String
htXenHvm = Types.hypervisorToRaw XenHvm

htKvm :: String
htKvm = Types.hypervisorToRaw Kvm

htChroot :: String
htChroot = Types.hypervisorToRaw Chroot

htLxc :: String
htLxc = Types.hypervisorToRaw Lxc

hyperTypes :: FrozenSet String
hyperTypes = ConstantUtils.mkSet $ map Types.hypervisorToRaw [minBound..]

htsReqPort :: FrozenSet String
htsReqPort = ConstantUtils.mkSet [htXenHvm, htKvm]

-- * Migration type

htMigrationLive :: String
htMigrationLive = Types.migrationModeToRaw MigrationLive

htMigrationNonlive :: String
htMigrationNonlive = Types.migrationModeToRaw MigrationNonLive

htMigrationModes :: FrozenSet String
htMigrationModes =
  ConstantUtils.mkSet $ map Types.migrationModeToRaw [minBound..]

-- * Cluster verify steps

verifyNplusoneMem :: String
verifyNplusoneMem = Types.verifyOptionalChecksToRaw VerifyNPlusOneMem

verifyOptionalChecks :: FrozenSet String
verifyOptionalChecks =
  ConstantUtils.mkSet $ map Types.verifyOptionalChecksToRaw [minBound..]

-- * Cluster Verify error classes

cvTcluster :: String
cvTcluster = "cluster"

cvTgroup :: String
cvTgroup = "group"

cvTnode :: String
cvTnode = "node"

cvTinstance :: String
cvTinstance = "instance"

-- * Cluster Verify error codes and documentation

cvEclustercert :: (String, String, String)
cvEclustercert =
  ("cluster",
   Types.cVErrorCodeToRaw CvECLUSTERCERT,
   "Cluster certificate files verification failure")

cvEclustercfg :: (String, String, String)
cvEclustercfg =
  ("cluster",
   Types.cVErrorCodeToRaw CvECLUSTERCFG,
   "Cluster configuration verification failure")

cvEclusterdanglinginst :: (String, String, String)
cvEclusterdanglinginst =
  ("node",
   Types.cVErrorCodeToRaw CvECLUSTERDANGLINGINST,
   "Some instances have a non-existing primary node")

cvEclusterdanglingnodes :: (String, String, String)
cvEclusterdanglingnodes =
  ("node",
   Types.cVErrorCodeToRaw CvECLUSTERDANGLINGNODES,
   "Some nodes belong to non-existing groups")

cvEclusterfilecheck :: (String, String, String)
cvEclusterfilecheck =
  ("cluster",
   Types.cVErrorCodeToRaw CvECLUSTERFILECHECK,
   "Cluster configuration verification failure")

cvEgroupdifferentpvsize :: (String, String, String)
cvEgroupdifferentpvsize =
  ("group",
   Types.cVErrorCodeToRaw CvEGROUPDIFFERENTPVSIZE,
   "PVs in the group have different sizes")

cvEinstancebadnode :: (String, String, String)
cvEinstancebadnode =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCEBADNODE,
   "Instance marked as running lives on an offline node")

cvEinstancedown :: (String, String, String)
cvEinstancedown =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCEDOWN,
   "Instance not running on its primary node")

cvEinstancefaultydisk :: (String, String, String)
cvEinstancefaultydisk =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCEFAULTYDISK,
   "Impossible to retrieve status for a disk")

cvEinstancelayout :: (String, String, String)
cvEinstancelayout =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCELAYOUT,
   "Instance has multiple secondary nodes")

cvEinstancemissingcfgparameter :: (String, String, String)
cvEinstancemissingcfgparameter =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCEMISSINGCFGPARAMETER,
   "A configuration parameter for an instance is missing")

cvEinstancemissingdisk :: (String, String, String)
cvEinstancemissingdisk =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCEMISSINGDISK,
   "Missing volume on an instance")

cvEinstancepolicy :: (String, String, String)
cvEinstancepolicy =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCEPOLICY,
   "Instance does not meet policy")

cvEinstancesplitgroups :: (String, String, String)
cvEinstancesplitgroups =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCESPLITGROUPS,
   "Instance with primary and secondary nodes in different groups")

cvEinstanceunsuitablenode :: (String, String, String)
cvEinstanceunsuitablenode =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCEUNSUITABLENODE,
   "Instance running on nodes that are not suitable for it")

cvEinstancewrongnode :: (String, String, String)
cvEinstancewrongnode =
  ("instance",
   Types.cVErrorCodeToRaw CvEINSTANCEWRONGNODE,
   "Instance running on the wrong node")

cvEnodedrbd :: (String, String, String)
cvEnodedrbd =
  ("node",
   Types.cVErrorCodeToRaw CvENODEDRBD,
   "Error parsing the DRBD status file")

cvEnodedrbdhelper :: (String, String, String)
cvEnodedrbdhelper =
  ("node",
   Types.cVErrorCodeToRaw CvENODEDRBDHELPER,
   "Error caused by the DRBD helper")

cvEnodedrbdversion :: (String, String, String)
cvEnodedrbdversion =
  ("node",
   Types.cVErrorCodeToRaw CvENODEDRBDVERSION,
   "DRBD version mismatch within a node group")

cvEnodefilecheck :: (String, String, String)
cvEnodefilecheck =
  ("node",
   Types.cVErrorCodeToRaw CvENODEFILECHECK,
   "Error retrieving the checksum of the node files")

cvEnodefilestoragepaths :: (String, String, String)
cvEnodefilestoragepaths =
  ("node",
   Types.cVErrorCodeToRaw CvENODEFILESTORAGEPATHS,
   "Detected bad file storage paths")

cvEnodefilestoragepathunusable :: (String, String, String)
cvEnodefilestoragepathunusable =
  ("node",
   Types.cVErrorCodeToRaw CvENODEFILESTORAGEPATHUNUSABLE,
   "File storage path unusable")

cvEnodehooks :: (String, String, String)
cvEnodehooks =
  ("node",
   Types.cVErrorCodeToRaw CvENODEHOOKS,
   "Communication failure in hooks execution")

cvEnodehv :: (String, String, String)
cvEnodehv =
  ("node",
   Types.cVErrorCodeToRaw CvENODEHV,
   "Hypervisor parameters verification failure")

cvEnodelvm :: (String, String, String)
cvEnodelvm =
  ("node",
   Types.cVErrorCodeToRaw CvENODELVM,
   "LVM-related node error")

cvEnoden1 :: (String, String, String)
cvEnoden1 =
  ("node",
   Types.cVErrorCodeToRaw CvENODEN1,
   "Not enough memory to accommodate instance failovers")

cvEnodenet :: (String, String, String)
cvEnodenet =
  ("node",
   Types.cVErrorCodeToRaw CvENODENET,
   "Network-related node error")

cvEnodeoobpath :: (String, String, String)
cvEnodeoobpath =
  ("node",
   Types.cVErrorCodeToRaw CvENODEOOBPATH,
   "Invalid Out Of Band path")

cvEnodeorphaninstance :: (String, String, String)
cvEnodeorphaninstance =
  ("node",
   Types.cVErrorCodeToRaw CvENODEORPHANINSTANCE,
   "Unknown intance running on a node")

cvEnodeorphanlv :: (String, String, String)
cvEnodeorphanlv =
  ("node",
   Types.cVErrorCodeToRaw CvENODEORPHANLV,
   "Unknown LVM logical volume")

cvEnodeos :: (String, String, String)
cvEnodeos =
  ("node",
   Types.cVErrorCodeToRaw CvENODEOS,
   "OS-related node error")

cvEnoderpc :: (String, String, String)
cvEnoderpc =
  ("node",
   Types.cVErrorCodeToRaw CvENODERPC,
   "Error during connection to the primary node of an instance")

cvEnodesetup :: (String, String, String)
cvEnodesetup =
  ("node",
   Types.cVErrorCodeToRaw CvENODESETUP,
   "Node setup error")

cvEnodesharedfilestoragepathunusable :: (String, String, String)
cvEnodesharedfilestoragepathunusable =
  ("node",
   Types.cVErrorCodeToRaw CvENODESHAREDFILESTORAGEPATHUNUSABLE,
   "Shared file storage path unusable")

cvEnodessh :: (String, String, String)
cvEnodessh =
  ("node",
   Types.cVErrorCodeToRaw CvENODESSH,
   "SSH-related node error")

cvEnodetime :: (String, String, String)
cvEnodetime =
  ("node",
   Types.cVErrorCodeToRaw CvENODETIME,
   "Node returned invalid time")

cvEnodeuserscripts :: (String, String, String)
cvEnodeuserscripts =
  ("node",
   Types.cVErrorCodeToRaw CvENODEUSERSCRIPTS,
   "User scripts not present or not executable")

cvEnodeversion :: (String, String, String)
cvEnodeversion =
  ("node",
   Types.cVErrorCodeToRaw CvENODEVERSION,
   "Protocol version mismatch or Ganeti version mismatch")

cvAllEcodes :: FrozenSet (String, String, String)
cvAllEcodes =
  ConstantUtils.mkSet
  [cvEclustercert,
   cvEclustercfg,
   cvEclusterdanglinginst,
   cvEclusterdanglingnodes,
   cvEclusterfilecheck,
   cvEgroupdifferentpvsize,
   cvEinstancebadnode,
   cvEinstancedown,
   cvEinstancefaultydisk,
   cvEinstancelayout,
   cvEinstancemissingcfgparameter,
   cvEinstancemissingdisk,
   cvEinstancepolicy,
   cvEinstancesplitgroups,
   cvEinstanceunsuitablenode,
   cvEinstancewrongnode,
   cvEnodedrbd,
   cvEnodedrbdhelper,
   cvEnodedrbdversion,
   cvEnodefilecheck,
   cvEnodefilestoragepaths,
   cvEnodefilestoragepathunusable,
   cvEnodehooks,
   cvEnodehv,
   cvEnodelvm,
   cvEnoden1,
   cvEnodenet,
   cvEnodeoobpath,
   cvEnodeorphaninstance,
   cvEnodeorphanlv,
   cvEnodeos,
   cvEnoderpc,
   cvEnodesetup,
   cvEnodesharedfilestoragepathunusable,
   cvEnodessh,
   cvEnodetime,
   cvEnodeuserscripts,
   cvEnodeversion]

cvAllEcodesStrings :: FrozenSet String
cvAllEcodesStrings =
  ConstantUtils.mkSet $ map Types.cVErrorCodeToRaw [minBound..]

-- * Instance status

inststAdmindown :: String
inststAdmindown = Types.instanceStatusToRaw StatusDown

inststAdminoffline :: String
inststAdminoffline = Types.instanceStatusToRaw StatusOffline

inststErrordown :: String
inststErrordown = Types.instanceStatusToRaw ErrorDown

inststErrorup :: String
inststErrorup = Types.instanceStatusToRaw ErrorUp

inststNodedown :: String
inststNodedown = Types.instanceStatusToRaw NodeDown

inststNodeoffline :: String
inststNodeoffline = Types.instanceStatusToRaw NodeOffline

inststRunning :: String
inststRunning = Types.instanceStatusToRaw Running

inststWrongnode :: String
inststWrongnode = Types.instanceStatusToRaw WrongNode

inststAll :: FrozenSet String
inststAll = ConstantUtils.mkSet $ map Types.instanceStatusToRaw [minBound..]

-- * Admin states

adminstDown :: String
adminstDown = "down"

adminstOffline :: String
adminstOffline = "offline"

adminstUp :: String
adminstUp = "up"

adminstAll :: FrozenSet String
adminstAll = ConstantUtils.mkSet [adminstDown, adminstOffline, adminstUp]

-- * Allocator framework constants

iallocatorVersion :: Int
iallocatorVersion = 2

iallocatorDirIn :: String
iallocatorDirIn = Types.iAllocatorTestDirToRaw IAllocatorDirIn

iallocatorDirOut :: String
iallocatorDirOut = Types.iAllocatorTestDirToRaw IAllocatorDirOut

validIallocatorDirections :: FrozenSet String
validIallocatorDirections =
  ConstantUtils.mkSet $ map Types.iAllocatorTestDirToRaw [minBound..]

iallocatorModeAlloc :: String
iallocatorModeAlloc = Types.iAllocatorModeToRaw IAllocatorAlloc

iallocatorModeChgGroup :: String
iallocatorModeChgGroup = Types.iAllocatorModeToRaw IAllocatorChangeGroup

iallocatorModeMultiAlloc :: String
iallocatorModeMultiAlloc = Types.iAllocatorModeToRaw IAllocatorMultiAlloc

iallocatorModeNodeEvac :: String
iallocatorModeNodeEvac = Types.iAllocatorModeToRaw IAllocatorNodeEvac

iallocatorModeReloc :: String
iallocatorModeReloc = Types.iAllocatorModeToRaw IAllocatorReloc

validIallocatorModes :: FrozenSet String
validIallocatorModes =
  ConstantUtils.mkSet $ map Types.iAllocatorModeToRaw [minBound..]

iallocatorSearchPath :: [String]
iallocatorSearchPath = AutoConf.iallocatorSearchPath

defaultIallocatorShortcut :: String
defaultIallocatorShortcut = "."

iallocatorNevacPri :: String
iallocatorNevacPri = Types.nodeEvacModeToRaw NEvacPrimary

iallocatorNevacSec :: String
iallocatorNevacSec = Types.nodeEvacModeToRaw NEvacSecondary

iallocatorNevacAll :: String
iallocatorNevacAll = Types.nodeEvacModeToRaw NEvacAll

iallocatorNevacModes :: FrozenSet String
iallocatorNevacModes =
  ConstantUtils.mkSet $ map Types.nodeEvacModeToRaw [minBound..]

-- * Node evacuation

nodeEvacPri :: String
nodeEvacPri = Types.nodeEvacModeToRaw NEvacPrimary

nodeEvacSec :: String
nodeEvacSec = Types.nodeEvacModeToRaw NEvacSecondary

nodeEvacAll :: String
nodeEvacAll = Types.nodeEvacModeToRaw NEvacAll

nodeEvacModes :: FrozenSet String
nodeEvacModes = ConstantUtils.mkSet $ map Types.nodeEvacModeToRaw [minBound..]

-- * Job status

jobStatusQueued :: String
jobStatusQueued = Types.jobStatusToRaw JOB_STATUS_QUEUED

jobStatusWaiting :: String
jobStatusWaiting = Types.jobStatusToRaw JOB_STATUS_WAITING

jobStatusCanceling :: String
jobStatusCanceling = Types.jobStatusToRaw JOB_STATUS_CANCELING

jobStatusRunning :: String
jobStatusRunning = Types.jobStatusToRaw JOB_STATUS_RUNNING

jobStatusCanceled :: String
jobStatusCanceled = Types.jobStatusToRaw JOB_STATUS_CANCELED

jobStatusSuccess :: String
jobStatusSuccess = Types.jobStatusToRaw JOB_STATUS_SUCCESS

jobStatusError :: String
jobStatusError = Types.jobStatusToRaw JOB_STATUS_ERROR

jobsPending :: FrozenSet String
jobsPending =
  ConstantUtils.mkSet [jobStatusQueued, jobStatusWaiting, jobStatusCanceling]

jobsFinalized :: FrozenSet String
jobsFinalized =
  ConstantUtils.mkSet $ map Types.finalizedJobStatusToRaw [minBound..]

jobStatusAll :: FrozenSet String
jobStatusAll = ConstantUtils.mkSet $ map Types.jobStatusToRaw [minBound..]

-- * OpCode status

-- ** Not yet finalized opcodes

opStatusCanceling :: String
opStatusCanceling = "canceling"

opStatusQueued :: String
opStatusQueued = "queued"

opStatusRunning :: String
opStatusRunning = "running"

opStatusWaiting :: String
opStatusWaiting = "waiting"

-- ** Finalized opcodes

opStatusCanceled :: String
opStatusCanceled = "canceled"

opStatusError :: String
opStatusError = "error"

opStatusSuccess :: String
opStatusSuccess = "success"

opsFinalized :: FrozenSet String
opsFinalized =
  ConstantUtils.mkSet [opStatusCanceled, opStatusError, opStatusSuccess]

-- * OpCode priority

opPrioLowest :: Int
opPrioLowest = 19

opPrioHighest :: Int
opPrioHighest = -20

opPrioLow :: Int
opPrioLow = Types.opSubmitPriorityToRaw OpPrioLow

opPrioNormal :: Int
opPrioNormal = Types.opSubmitPriorityToRaw OpPrioNormal

opPrioHigh :: Int
opPrioHigh = Types.opSubmitPriorityToRaw OpPrioHigh

opPrioSubmitValid :: FrozenSet Int
opPrioSubmitValid = ConstantUtils.mkSet [opPrioLow, opPrioNormal, opPrioHigh]

opPrioDefault :: Int
opPrioDefault = opPrioNormal

-- * Execution log types

elogMessage :: String
elogMessage = Types.eLogTypeToRaw ELogMessage

elogRemoteImport :: String
elogRemoteImport = Types.eLogTypeToRaw ELogRemoteImport

elogJqueueTest :: String
elogJqueueTest = Types.eLogTypeToRaw ELogJqueueTest

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
  ConstantUtils.mkSet [confd,
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

daemonsLogbase :: Map String String
daemonsLogbase =
  Map.fromList
  [ (Runtime.daemonName d, Runtime.daemonLogBase d) | d <- [minBound..] ]

extraLogreasonAccess :: String
extraLogreasonAccess = Runtime.daemonsExtraLogbase GanetiMond AccessLog

extraLogreasonError :: String
extraLogreasonError = Runtime.daemonsExtraLogbase GanetiMond ErrorLog

devConsole :: String
devConsole = ConstantUtils.devConsole

-- * Syslog

syslogUsage :: String
syslogUsage = AutoConf.syslogUsage

syslogNo :: String
syslogNo = Logging.syslogUsageToRaw SyslogNo

syslogYes :: String
syslogYes = Logging.syslogUsageToRaw SyslogYes

syslogOnly :: String
syslogOnly = Logging.syslogUsageToRaw SyslogOnly

syslogSocket :: String
syslogSocket = "/dev/log"

-- * Xen

xenBootloader :: String
xenBootloader = AutoConf.xenBootloader

xenCmdXl :: String
xenCmdXl = "xl"

xenCmdXm :: String
xenCmdXm = "xm"

xenInitrd :: String
xenInitrd = AutoConf.xenInitrd

xenKernel :: String
xenKernel = AutoConf.xenKernel

-- FIXME: perhaps rename to 'validXenCommands' for consistency with
-- other constants
knownXenCommands :: FrozenSet String
knownXenCommands = ConstantUtils.mkSet [xenCmdXl, xenCmdXm]

-- * Storage types

stBlock :: String
stBlock = Types.storageTypeToRaw StorageBlock

stDiskless :: String
stDiskless = Types.storageTypeToRaw StorageDiskless

stExt :: String
stExt = Types.storageTypeToRaw StorageExt

stFile :: String
stFile = Types.storageTypeToRaw StorageFile

stLvmPv :: String
stLvmPv = Types.storageTypeToRaw StorageLvmPv

stLvmVg :: String
stLvmVg = Types.storageTypeToRaw StorageLvmVg

stRados :: String
stRados = Types.storageTypeToRaw StorageRados

storageTypes :: FrozenSet String
storageTypes = ConstantUtils.mkSet $ map Types.storageTypeToRaw [minBound..]

-- * Disk template types

dtDiskless :: String
dtDiskless = Types.diskTemplateToRaw DTDiskless

dtFile :: String
dtFile = Types.diskTemplateToRaw DTFile

dtSharedFile :: String
dtSharedFile = Types.diskTemplateToRaw DTSharedFile

dtPlain :: String
dtPlain = Types.diskTemplateToRaw DTPlain

dtBlock :: String
dtBlock = Types.diskTemplateToRaw DTBlock

dtDrbd8 :: String
dtDrbd8 = Types.diskTemplateToRaw DTDrbd8

dtRbd :: String
dtRbd = Types.diskTemplateToRaw DTRbd

dtExt :: String
dtExt = Types.diskTemplateToRaw DTExt

-- | This is used to order determine the default disk template when
-- the list of enabled disk templates is inferred from the current
-- state of the cluster.  This only happens on an upgrade from a
-- version of Ganeti that did not support the 'enabled_disk_templates'
-- so far.
diskTemplatePreference :: [String]
diskTemplatePreference =
  map Types.diskTemplateToRaw
  [DTBlock, DTDiskless, DTDrbd8, DTExt, DTFile, DTPlain, DTRbd, DTSharedFile]

diskTemplates :: FrozenSet String
diskTemplates = ConstantUtils.mkSet $ map Types.diskTemplateToRaw [minBound..]

-- | Disk templates that are enabled by default
defaultEnabledDiskTemplates :: [String]
defaultEnabledDiskTemplates = map Types.diskTemplateToRaw [DTDrbd8, DTPlain]

-- * File backend driver

fdBlktap :: String
fdBlktap = Types.fileDriverToRaw FileBlktap

fdLoop :: String
fdLoop = Types.fileDriverToRaw FileLoop

-- * Instance export mode

exportModeLocal :: String
exportModeLocal = Types.exportModeToRaw ExportModeLocal

exportModeRemote :: String
exportModeRemote = Types.exportModeToRaw ExportModeRemote

exportModes :: FrozenSet String
exportModes = ConstantUtils.mkSet $ map Types.exportModeToRaw [minBound..]

-- * Instance creation modes

instanceCreate :: String
instanceCreate = Types.instCreateModeToRaw InstCreate

instanceImport :: String
instanceImport = Types.instCreateModeToRaw InstImport

instanceRemoteImport :: String
instanceRemoteImport = Types.instCreateModeToRaw InstRemoteImport

instanceCreateModes :: FrozenSet String
instanceCreateModes =
  ConstantUtils.mkSet $ map Types.instCreateModeToRaw [minBound..]

-- * Dynamic device modification

ddmAdd :: String
ddmAdd = Types.ddmFullToRaw DdmFullAdd

ddmModify :: String
ddmModify = Types.ddmFullToRaw DdmFullModify

ddmRemove :: String
ddmRemove = Types.ddmFullToRaw DdmFullRemove

ddmsValues :: FrozenSet String
ddmsValues = ConstantUtils.mkSet [ddmAdd, ddmRemove]

ddmsValuesWithModify :: FrozenSet String
ddmsValuesWithModify = ConstantUtils.mkSet $ map Types.ddmFullToRaw [minBound..]

-- * Common exit codes

exitSuccess :: Int
exitSuccess = 0

exitFailure :: Int
exitFailure = ConstantUtils.exitFailure

exitNotcluster :: Int
exitNotcluster = 5

exitNotmaster :: Int
exitNotmaster = 11

exitNodesetupError :: Int
exitNodesetupError = 12

-- | Need user confirmation
exitConfirmation :: Int
exitConfirmation = 13

-- | Exit code for query operations with unknown fields
exitUnknownField :: Int
exitUnknownField = 14

-- * Tags

tagCluster :: String
tagCluster = Types.tagKindToRaw TagKindCluster

tagInstance :: String
tagInstance = Types.tagKindToRaw TagKindInstance

tagNetwork :: String
tagNetwork = Types.tagKindToRaw TagKindNetwork

tagNode :: String
tagNode = Types.tagKindToRaw TagKindNode

tagNodegroup :: String
tagNodegroup = Types.tagKindToRaw TagKindGroup

validTagTypes :: FrozenSet String
validTagTypes = ConstantUtils.mkSet $ map Types.tagKindToRaw [minBound..]

maxTagLen :: Int
maxTagLen = 128

maxTagsPerObj :: Int
maxTagsPerObj = 4096

-- * Reboot types

instanceRebootSoft :: String
instanceRebootSoft = Types.rebootTypeToRaw RebootSoft

instanceRebootHard :: String
instanceRebootHard = Types.rebootTypeToRaw RebootHard

instanceRebootFull :: String
instanceRebootFull = Types.rebootTypeToRaw RebootFull

rebootTypes :: FrozenSet String
rebootTypes = ConstantUtils.mkSet $ map Types.rebootTypeToRaw [minBound..]

-- * Possible values for NodeGroup.alloc_policy

allocPolicyLastResort :: String
allocPolicyLastResort = Types.allocPolicyToRaw AllocLastResort

allocPolicyPreferred :: String
allocPolicyPreferred = Types.allocPolicyToRaw AllocPreferred

allocPolicyUnallocable :: String
allocPolicyUnallocable = Types.allocPolicyToRaw AllocUnallocable

validAllocPolicies :: [String]
validAllocPolicies = map Types.allocPolicyToRaw [minBound..]

-- | Temporary external/shared storage parameters
blockdevDriverManual :: String
blockdevDriverManual = "manual"

-- | Path generating random UUID
randomUuidFile :: String
randomUuidFile = ConstantUtils.randomUuidFile

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
  ConstantUtils.mkSet [autoRepairFailover,
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
  ConstantUtils.mkSet [autoRepairEnoperm, autoRepairFailure, autoRepairSuccess]

-- | The version identifier for builtin data collectors
builtinDataCollectorVersion :: String
builtinDataCollectorVersion = "B"

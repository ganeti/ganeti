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

import Data.List ((\\))
import Data.Map (Map)
import qualified Data.Map as Map (fromList, keys, insert)

import AutoConf
import Ganeti.ConstantUtils (FrozenSet, Protocol(..), buildVersion)
import qualified Ganeti.ConstantUtils as ConstantUtils
import Ganeti.Runtime (GanetiDaemon(..), MiscGroup(..), GanetiGroup(..),
                       ExtraLogReason(..))
import Ganeti.Logging (SyslogUsage(..))
import qualified Ganeti.Logging as Logging (syslogUsageToRaw)
import qualified Ganeti.Runtime as Runtime
import Ganeti.Types
import qualified Ganeti.Types as Types
import Ganeti.Confd.Types (ConfdRequestType(..), ConfdReqField(..),
                           ConfdReplyStatus(..), ConfdNodeRole(..),
                           ConfdErrorType(..))
import qualified Ganeti.Confd.Types as Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * 'autoconf' constants for Python only ('autotools/build-bash-completion')

htoolsProgs :: [String]
htoolsProgs = AutoConf.htoolsProgs

-- * 'autoconf' constants for Python only ('lib/constants.py')

drbdBarriers :: String
drbdBarriers = AutoConf.drbdBarriers

drbdNoMetaFlush :: Bool
drbdNoMetaFlush = AutoConf.drbdNoMetaFlush

lvmStripecount :: Int
lvmStripecount = AutoConf.lvmStripecount

-- * 'autoconf' constants for Python only ('lib/pathutils.py')

-- ** Build-time constants

exportDir :: String
exportDir = AutoConf.exportDir

osSearchPath :: [String]
osSearchPath = AutoConf.osSearchPath

esSearchPath :: [String]
esSearchPath = AutoConf.esSearchPath

sshConfigDir :: String
sshConfigDir = AutoConf.sshConfigDir

xenConfigDir :: String
xenConfigDir = AutoConf.xenConfigDir

sysconfdir :: String
sysconfdir = AutoConf.sysconfdir

toolsdir :: String
toolsdir = AutoConf.toolsdir

localstatedir :: String
localstatedir = AutoConf.localstatedir

-- ** Paths which don't change for a virtual cluster

pkglibdir :: String
pkglibdir = AutoConf.pkglibdir

sharedir :: String
sharedir = AutoConf.sharedir

-- * 'autoconf' constants for Python only ('lib/build/sphinx_ext.py')

manPages :: Map String Int
manPages = Map.fromList AutoConf.manPages

-- * 'autoconf' constants for QA cluster only ('qa/qa_cluster.py')

versionedsharedir :: String
versionedsharedir = AutoConf.versionedsharedir

-- * 'autoconf' constants for Python only ('tests/py/docs_unittest.py')

gntScripts :: [String]
gntScripts = AutoConf.gntScripts

-- * Various versions

releaseVersion :: String
releaseVersion = AutoConf.packageVersion

versionMajor :: Int
versionMajor = AutoConf.versionMajor

versionMinor :: Int
versionMinor = AutoConf.versionMinor

versionRevision :: Int
versionRevision = AutoConf.versionRevision

dirVersion :: String
dirVersion = AutoConf.dirVersion

osApiV10 :: Int
osApiV10 = 10

osApiV15 :: Int
osApiV15 = 15

osApiV20 :: Int
osApiV20 = 20

osApiVersions :: FrozenSet Int
osApiVersions = ConstantUtils.mkSet [osApiV10, osApiV15, osApiV20]

configMajor :: Int
configMajor = AutoConf.versionMajor

configMinor :: Int
configMinor = AutoConf.versionMinor

-- | The configuration is supposed to remain stable across
-- revisions. Therefore, the revision number is cleared to '0'.
configRevision :: Int
configRevision = 0

configVersion :: Int
configVersion = buildVersion configMajor configMinor configRevision

-- | Similarly to the configuration (see 'configRevision'), the
-- protocols are supposed to remain stable across revisions.
protocolVersion :: Int
protocolVersion = buildVersion configMajor configMinor configRevision

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

-- * Wipe

ddCmd :: String
ddCmd = "dd"

-- | 1GB
maxWipeChunk :: Int
maxWipeChunk = 1024

minWipeChunkPercent :: Int
minWipeChunkPercent = 10

-- * Directories

runDirsMode :: Int
runDirsMode = 0o775

secureDirMode :: Int
secureDirMode = 0o700

secureFileMode :: Int
secureFileMode = 0o600

adoptableBlockdevRoot :: String
adoptableBlockdevRoot = "/dev/disk/"

-- * 'autoconf' enable/disable

enableConfd :: Bool
enableConfd = AutoConf.enableConfd

enableMond :: Bool
enableMond = AutoConf.enableMond

enableRestrictedCommands :: Bool
enableRestrictedCommands = AutoConf.enableRestrictedCommands

enableSplitQuery :: Bool
enableSplitQuery = AutoConf.enableSplitQuery

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

firstDrbdPort :: Int
firstDrbdPort = 11000

lastDrbdPort :: Int
lastDrbdPort = 14999

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

-- * KVM and socat

kvmPath :: String
kvmPath = AutoConf.kvmPath

kvmKernel :: String
kvmKernel = AutoConf.kvmKernel

socatEscapeCode :: String
socatEscapeCode = "0x1d"

socatPath :: String
socatPath = AutoConf.socatPath

socatUseCompress :: Bool
socatUseCompress = AutoConf.socatUseCompress

socatUseEscape :: Bool
socatUseEscape = AutoConf.socatUseEscape

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

-- * Storage fields
-- ** First two are valid in LU context only, not passed to backend

sfNode :: String
sfNode = "node"

sfType :: String
sfType = "type"

-- ** and the rest are valid in backend

sfAllocatable :: String
sfAllocatable = Types.storageFieldToRaw SFAllocatable

sfFree :: String
sfFree = Types.storageFieldToRaw SFFree

sfName :: String
sfName = Types.storageFieldToRaw SFName

sfSize :: String
sfSize = Types.storageFieldToRaw SFSize

sfUsed :: String
sfUsed = Types.storageFieldToRaw SFUsed

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

-- * Disk access mode

diskRdonly :: String
diskRdonly = Types.diskModeToRaw DiskRdOnly

diskRdwr :: String
diskRdwr = Types.diskModeToRaw DiskRdWr

diskAccessSet :: FrozenSet String
diskAccessSet = ConstantUtils.mkSet $ map Types.diskModeToRaw [minBound..]

-- * Disk replacement mode

replaceDiskAuto :: String
replaceDiskAuto = Types.replaceDisksModeToRaw ReplaceAuto

replaceDiskChg :: String
replaceDiskChg = Types.replaceDisksModeToRaw ReplaceNewSecondary

replaceDiskPri :: String
replaceDiskPri = Types.replaceDisksModeToRaw ReplaceOnPrimary

replaceDiskSec :: String
replaceDiskSec = Types.replaceDisksModeToRaw ReplaceOnSecondary

replaceModes :: FrozenSet String
replaceModes =
  ConstantUtils.mkSet $ map Types.replaceDisksModeToRaw [minBound..]

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

-- | Node clock skew in seconds
nodeMaxClockSkew :: Int
nodeMaxClockSkew = 150

-- | Disk index separator
diskSeparator :: String
diskSeparator = AutoConf.diskSeparator

-- * Timeout table
--
-- Various time constants for the timeout table

rpcTmoUrgent :: Int
rpcTmoUrgent = Types.rpcTimeoutToRaw Urgent

rpcTmoFast :: Int
rpcTmoFast = Types.rpcTimeoutToRaw Fast

rpcTmoNormal :: Int
rpcTmoNormal = Types.rpcTimeoutToRaw Normal

rpcTmoSlow :: Int
rpcTmoSlow = Types.rpcTimeoutToRaw Slow

-- | 'rpcTmo_4hrs' contains an underscore to circumvent a limitation
-- in the 'Ganeti.THH.deCamelCase' function and generate the correct
-- Python name.
rpcTmo_4hrs :: Int
rpcTmo_4hrs = Types.rpcTimeoutToRaw FourHours

-- | 'rpcTmo_1day' contains an underscore to circumvent a limitation
-- in the 'Ganeti.THH.deCamelCase' function and generate the correct
-- Python name.
rpcTmo_1day :: Int
rpcTmo_1day = Types.rpcTimeoutToRaw OneDay

-- | Timeout for connecting to nodes (seconds)
rpcConnectTimeout :: Int
rpcConnectTimeout = 5

-- | Node parameter names

ndExclusiveStorage :: String
ndExclusiveStorage = "exclusive_storage"

ndOobProgram :: String
ndOobProgram = "oob_program"

ndSpindleCount :: String
ndSpindleCount = "spindle_count"

ndOvs :: String
ndOvs = "ovs"

ndOvsLink :: String
ndOvsLink = "ovs_link"

ndOvsName :: String
ndOvsName = "ovs_name"

ndsParameterTypes :: Map String VType
ndsParameterTypes =
  Map.fromList
  [(ndExclusiveStorage, VTypeBool),
   (ndOobProgram, VTypeString),
   (ndOvs, VTypeBool),
   (ndOvsLink, VTypeMaybeString),
   (ndOvsName, VTypeMaybeString),
   (ndSpindleCount, VTypeInt)]

ndsParameters :: FrozenSet String
ndsParameters = ConstantUtils.mkSet (Map.keys ndsParameterTypes)

ndsParameterTitles :: Map String String
ndsParameterTitles =
  Map.fromList
  [(ndExclusiveStorage, "ExclusiveStorage"),
   (ndOobProgram, "OutOfBandProgram"),
   (ndOvs, "OpenvSwitch"),
   (ndOvsLink, "OpenvSwitchLink"),
   (ndOvsName, "OpenvSwitchName"),
   (ndSpindleCount, "SpindleCount")]

ipCommandPath :: String
ipCommandPath = AutoConf.ipPath

-- * Reboot types

instanceRebootSoft :: String
instanceRebootSoft = Types.rebootTypeToRaw RebootSoft

instanceRebootHard :: String
instanceRebootHard = Types.rebootTypeToRaw RebootHard

instanceRebootFull :: String
instanceRebootFull = Types.rebootTypeToRaw RebootFull

rebootTypes :: FrozenSet String
rebootTypes = ConstantUtils.mkSet $ map Types.rebootTypeToRaw [minBound..]

-- * VTypes

vtypeBool :: String
vtypeBool = Types.vTypeToRaw VTypeBool

vtypeInt :: String
vtypeInt = Types.vTypeToRaw VTypeInt

vtypeMaybeString :: String
vtypeMaybeString = Types.vTypeToRaw VTypeMaybeString

-- | Size in MiBs
vtypeSize :: String
vtypeSize = Types.vTypeToRaw VTypeSize

vtypeString :: String
vtypeString = Types.vTypeToRaw VTypeString

enforceableTypes :: FrozenSet String
enforceableTypes = ConstantUtils.mkSet $ map Types.vTypeToRaw [minBound..]

-- * OOB supported commands

oobPowerOn :: String
oobPowerOn = Types.oobCommandToRaw OobPowerOn

oobPowerOff :: String
oobPowerOff = Types.oobCommandToRaw OobPowerOff

oobPowerCycle :: String
oobPowerCycle = Types.oobCommandToRaw OobPowerCycle

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
adminstDown = Types.adminStateToRaw AdminDown

adminstOffline :: String
adminstOffline = Types.adminStateToRaw AdminOffline

adminstUp :: String
adminstUp = Types.adminStateToRaw AdminUp

adminstAll :: FrozenSet String
adminstAll = ConstantUtils.mkSet $ map Types.adminStateToRaw [minBound..]

-- * Node roles

nrDrained :: String
nrDrained = Types.nodeRoleToRaw NRDrained

nrMaster :: String
nrMaster = Types.nodeRoleToRaw NRMaster

nrMcandidate :: String
nrMcandidate = Types.nodeRoleToRaw NRCandidate

nrOffline :: String
nrOffline = Types.nodeRoleToRaw NROffline

nrRegular :: String
nrRegular = Types.nodeRoleToRaw NRRegular

nrAll :: FrozenSet String
nrAll = ConstantUtils.mkSet $ map Types.nodeRoleToRaw [minBound..]

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

-- * Node evacuation

nodeEvacPri :: String
nodeEvacPri = Types.evacModeToRaw ChangePrimary

nodeEvacSec :: String
nodeEvacSec = Types.evacModeToRaw ChangeSecondary

nodeEvacAll :: String
nodeEvacAll = Types.evacModeToRaw ChangeAll

nodeEvacModes :: FrozenSet String
nodeEvacModes = ConstantUtils.mkSet $ map Types.evacModeToRaw [minBound..]

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

-- * Confd

confdProtocolVersion :: Int
confdProtocolVersion = ConstantUtils.confdProtocolVersion

-- Confd request type

confdReqPing :: Int
confdReqPing = Types.confdRequestTypeToRaw ReqPing

confdReqNodeRoleByname :: Int
confdReqNodeRoleByname = Types.confdRequestTypeToRaw ReqNodeRoleByName

confdReqNodePipByInstanceIp :: Int
confdReqNodePipByInstanceIp = Types.confdRequestTypeToRaw ReqNodePipByInstPip

confdReqClusterMaster :: Int
confdReqClusterMaster = Types.confdRequestTypeToRaw ReqClusterMaster

confdReqNodePipList :: Int
confdReqNodePipList = Types.confdRequestTypeToRaw ReqNodePipList

confdReqMcPipList :: Int
confdReqMcPipList = Types.confdRequestTypeToRaw ReqMcPipList

confdReqInstancesIpsList :: Int
confdReqInstancesIpsList = Types.confdRequestTypeToRaw ReqInstIpsList

confdReqNodeDrbd :: Int
confdReqNodeDrbd = Types.confdRequestTypeToRaw ReqNodeDrbd

confdReqNodeInstances :: Int
confdReqNodeInstances = Types.confdRequestTypeToRaw ReqNodeInstances

confdReqs :: FrozenSet Int
confdReqs =
  ConstantUtils.mkSet .
  map Types.confdRequestTypeToRaw $
  [minBound..] \\ [ReqNodeInstances]

-- * Confd request type

confdReqfieldName :: Int
confdReqfieldName = Types.confdReqFieldToRaw ReqFieldName

confdReqfieldIp :: Int
confdReqfieldIp = Types.confdReqFieldToRaw ReqFieldIp

confdReqfieldMnodePip :: Int
confdReqfieldMnodePip = Types.confdReqFieldToRaw ReqFieldMNodePip

-- * Confd repl status

confdReplStatusOk :: Int
confdReplStatusOk = Types.confdReplyStatusToRaw ReplyStatusOk

confdReplStatusError :: Int
confdReplStatusError = Types.confdReplyStatusToRaw ReplyStatusError

confdReplStatusNotimplemented :: Int
confdReplStatusNotimplemented = Types.confdReplyStatusToRaw ReplyStatusNotImpl

confdReplStatuses :: FrozenSet Int
confdReplStatuses =
  ConstantUtils.mkSet $ map Types.confdReplyStatusToRaw [minBound..]

-- * Confd node role

confdNodeRoleMaster :: Int
confdNodeRoleMaster = Types.confdNodeRoleToRaw NodeRoleMaster

confdNodeRoleCandidate :: Int
confdNodeRoleCandidate = Types.confdNodeRoleToRaw NodeRoleCandidate

confdNodeRoleOffline :: Int
confdNodeRoleOffline = Types.confdNodeRoleToRaw NodeRoleOffline

confdNodeRoleDrained :: Int
confdNodeRoleDrained = Types.confdNodeRoleToRaw NodeRoleDrained

confdNodeRoleRegular :: Int
confdNodeRoleRegular = Types.confdNodeRoleToRaw NodeRoleRegular

-- * A few common errors for confd

confdErrorUnknownEntry :: Int
confdErrorUnknownEntry = Types.confdErrorTypeToRaw ConfdErrorUnknownEntry

confdErrorInternal :: Int
confdErrorInternal = Types.confdErrorTypeToRaw ConfdErrorInternal

confdErrorArgument :: Int
confdErrorArgument = Types.confdErrorTypeToRaw ConfdErrorArgument

-- * Confd request query fields

confdReqqLink :: String
confdReqqLink = ConstantUtils.confdReqqLink

confdReqqIp :: String
confdReqqIp = ConstantUtils.confdReqqIp

confdReqqIplist :: String
confdReqqIplist = ConstantUtils.confdReqqIplist

confdReqqFields :: String
confdReqqFields = ConstantUtils.confdReqqFields

-- | Each request is "salted" by the current timestamp.
--
-- This constant decides how many seconds of skew to accept.
--
-- TODO: make this a default and allow the value to be more
-- configurable
confdMaxClockSkew :: Int
confdMaxClockSkew = 2 * nodeMaxClockSkew

-- | When we haven't reloaded the config for more than this amount of
-- seconds, we force a test to see if inotify is betraying us. Using a
-- prime number to ensure we get less chance of 'same wakeup' with
-- other processes.
confdConfigReloadTimeout :: Int
confdConfigReloadTimeout = 17

-- | If we receive more than one update in this amount of
-- microseconds, we move to polling every RATELIMIT seconds, rather
-- than relying on inotify, to be able to serve more requests.
confdConfigReloadRatelimit :: Int
confdConfigReloadRatelimit = 250000

-- | Magic number prepended to all confd queries.
--
-- This allows us to distinguish different types of confd protocols
-- and handle them. For example by changing this we can move the whole
-- payload to be compressed, or move away from json.
confdMagicFourcc :: String
confdMagicFourcc = "plj0"

-- | By default a confd request is sent to the minimum between this
-- number and all MCs. 6 was chosen because even in the case of a
-- disastrous 50% response rate, we should have enough answers to be
-- able to compare more than one.
confdDefaultReqCoverage :: Int
confdDefaultReqCoverage = 6

-- | Timeout in seconds to expire pending query request in the confd
-- client library. We don't actually expect any answer more than 10
-- seconds after we sent a request.
confdClientExpireTimeout :: Int
confdClientExpireTimeout = 10

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
blockdevDriverManual = Types.blockDriverToRaw BlockDrvManual

-- | 'qemu-img' path, required for 'ovfconverter'
qemuimgPath :: String
qemuimgPath = AutoConf.qemuimgPath

-- | Whether htools was enabled at compilation time
--
-- FIXME: this should be moved next to the other enable constants,
-- such as, 'enableConfd', and renamed to 'enableHtools'.
htools :: Bool
htools = AutoConf.htools

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

-- | The reason trail opcode parameter name
opcodeReason :: String
opcodeReason = "reason"

diskstatsFile :: String
diskstatsFile = "/proc/diskstats"

-- *  CPU load collector

statFile :: String
statFile = "/proc/stat"

cpuavgloadBufferSize :: Int
cpuavgloadBufferSize = 150

cpuavgloadWindowSize :: Int
cpuavgloadWindowSize = 600

-- | Mond's variable for periodical data collection
mondTimeInterval :: Int
mondTimeInterval = 5

-- * Disk access modes

diskUserspace :: String
diskUserspace = Types.diskAccessModeToRaw DiskUserspace

diskKernelspace :: String
diskKernelspace = Types.diskAccessModeToRaw DiskKernelspace

diskValidAccessModes :: FrozenSet String
diskValidAccessModes =
  ConstantUtils.mkSet $ map Types.diskAccessModeToRaw [minBound..]

-- | Timeout for queue draining in upgrades
upgradeQueueDrainTimeout :: Int
upgradeQueueDrainTimeout = 36 * 60 * 60 -- 1.5 days

-- | Intervall at which the queue is polled during upgrades
upgradeQueuePollInterval :: Int
upgradeQueuePollInterval  = 10

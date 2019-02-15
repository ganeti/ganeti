{-# OPTIONS -fno-warn-type-defaults #-}
{-| Constants contains the Haskell constants

The constants in this module are used in Haskell and are also
converted to Python.

Do not write any definitions in this file other than constants.  Do
not even write helper functions.  The definitions in this module are
automatically stripped to build the Makefile.am target
'ListConstants.hs'.  If there are helper functions in this module,
they will also be dragged and it will cause compilation to fail.
Therefore, all helper functions should go to a separate module and
imported.

-}

{-

Copyright (C) 2013, 2014 Google Inc.
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
module Ganeti.Constants where

import Control.Arrow ((***),(&&&))
import Data.List ((\\))
import Data.Map (Map)
import qualified Data.Map as Map (empty, fromList, keys, insert)
import Data.Monoid

import qualified AutoConf
import Ganeti.ConstantUtils (PythonChar(..), FrozenSet, Protocol(..),
                             buildVersion)
import qualified Ganeti.ConstantUtils as ConstantUtils
import qualified Ganeti.HTools.Types as Types
import Ganeti.HTools.Types (AutoRepairResult(..), AutoRepairType(..))
import Ganeti.Logging (SyslogUsage(..))
import qualified Ganeti.Logging as Logging (syslogUsageToRaw)
import qualified Ganeti.Runtime as Runtime
import Ganeti.Runtime (GanetiDaemon(..), MiscGroup(..), GanetiGroup(..),
                       ExtraLogReason(..))
import Ganeti.THH (PyValueEx(..))
import Ganeti.Types
import qualified Ganeti.Types as Types
import Ganeti.Confd.Types (ConfdRequestType(..), ConfdReqField(..),
                           ConfdReplyStatus(..), ConfdNodeRole(..),
                           ConfdErrorType(..))
import qualified Ganeti.Confd.Types as Types
import qualified Ganeti.HTools.Tags.Constants as Tags

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

hasGnuLn :: Bool
hasGnuLn = AutoConf.hasGnuLn

-- * 'autoconf' constants for Python only ('lib/pathutils.py')

-- ** Build-time constants

exportDir :: String
exportDir = AutoConf.exportDir

backupDir :: String
backupDir = AutoConf.backupDir

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

-- | The version of the backup/export instance description file format we are
-- producing when exporting and accepting when importing. The two are currently
-- tightly intertwined.
exportVersion :: Int
exportVersion = 0

rapiVersion :: Int
rapiVersion = 2

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

metadUser :: String
metadUser = Runtime.daemonUser GanetiMetad

metadGroup :: String
metadGroup = Runtime.daemonGroup (DaemonGroup GanetiMetad)

rapiUser :: String
rapiUser = Runtime.daemonUser GanetiRapi

rapiGroup :: String
rapiGroup = Runtime.daemonGroup (DaemonGroup GanetiRapi)

confdUser :: String
confdUser = Runtime.daemonUser GanetiConfd

confdGroup :: String
confdGroup = Runtime.daemonGroup (DaemonGroup GanetiConfd)

wconfdUser :: String
wconfdUser = Runtime.daemonUser GanetiWConfd

wconfdGroup :: String
wconfdGroup = Runtime.daemonGroup (DaemonGroup GanetiWConfd)

kvmdUser :: String
kvmdUser = Runtime.daemonUser GanetiKvmd

kvmdGroup :: String
kvmdGroup = Runtime.daemonGroup (DaemonGroup GanetiKvmd)

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

-- * Cpu pinning separators and constants

cpuPinningSep :: String
cpuPinningSep = ":"

cpuPinningAll :: String
cpuPinningAll = "all"

-- | Internal representation of "all"
cpuPinningAllVal :: Int
cpuPinningAllVal = -1

-- | One "all" entry in a CPU list means CPU pinning is off
cpuPinningOff :: [Int]
cpuPinningOff = [cpuPinningAllVal]

-- | A Xen-specific implementation detail is that there is no way to
-- actually say "use any cpu for pinning" in a Xen configuration file,
-- as opposed to the command line, where you can say
-- @
-- xm vcpu-pin <domain> <vcpu> all
-- @
--
-- The workaround used in Xen is "0-63" (see source code function
-- "xm_vcpu_pin" in @<xen-source>/tools/python/xen/xm/main.py@).
--
-- To support future changes, the following constant is treated as a
-- blackbox string that simply means "use any cpu for pinning under
-- xen".
cpuPinningAllXen :: String
cpuPinningAllXen = "0-63"

-- * Image and wipe

ddCmd :: String
ddCmd = "dd"

-- | 1 MiB
-- The default block size for the 'dd' command
ddBlockSize :: Int
ddBlockSize = 1024^2

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

enableMond :: Bool
enableMond = AutoConf.enableMond

enableMetad :: Bool
enableMetad = AutoConf.enableMetad

enableRestrictedCommands :: Bool
enableRestrictedCommands = AutoConf.enableRestrictedCommands

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

metad :: String
metad = Runtime.daemonName GanetiMetad

mond :: String
mond = Runtime.daemonName GanetiMond

noded :: String
noded = Runtime.daemonName GanetiNoded

wconfd :: String
wconfd = Runtime.daemonName GanetiWConfd

luxid :: String
luxid = Runtime.daemonName GanetiLuxid

rapi :: String
rapi = Runtime.daemonName GanetiRapi

kvmd :: String
kvmd = Runtime.daemonName GanetiKvmd

-- Set of daemons which only run on the master.
-- Keep in sync with the 'daemon-util' script.
daemonsMaster :: FrozenSet String
daemonsMaster = ConstantUtils.mkSet [wconfd, luxid, rapi]

daemons :: FrozenSet String
daemons =
  ConstantUtils.mkSet
  $ map Runtime.daemonName [minBound .. maxBound]

defaultConfdPort :: Int
defaultConfdPort = 1814

defaultMondPort :: Int
defaultMondPort = 1815

defaultMetadPort :: Int
defaultMetadPort = 80

defaultNodedPort :: Int
defaultNodedPort = 1811

defaultRapiPort :: Int
defaultRapiPort = 5080

daemonsPorts :: Map String (Protocol, Int)
daemonsPorts =
  Map.fromList
  [ (confd, (Udp, defaultConfdPort))
  , (metad, (Tcp, defaultMetadPort))
  , (mond, (Tcp, defaultMondPort))
  , (noded, (Tcp, defaultNodedPort))
  , (rapi, (Tcp, defaultRapiPort))
  , (ssh, (Tcp, 22))
  ]

firstDrbdPort :: Int
firstDrbdPort = 11000

lastDrbdPort :: Int
lastDrbdPort = 14999

daemonsLogbase :: Map String String
daemonsLogbase =
  Map.fromList
  [ (Runtime.daemonName d, Runtime.daemonLogBase d) | d <- [minBound..] ]

daemonsExtraLogbase :: Map String (Map String String)
daemonsExtraLogbase =
  Map.fromList $
  map (Runtime.daemonName *** id)
  [ (GanetiMond, Map.fromList
                 [ ("access", Runtime.daemonsExtraLogbase GanetiMond AccessLog)
                 , ("error", Runtime.daemonsExtraLogbase GanetiMond ErrorLog)
                 ])
  ]

extraLogreasonAccess :: String
extraLogreasonAccess = Runtime.daemonsExtraLogbase GanetiMond AccessLog

extraLogreasonError :: String
extraLogreasonError = Runtime.daemonsExtraLogbase GanetiMond ErrorLog

devConsole :: String
devConsole = ConstantUtils.devConsole

procMounts :: String
procMounts = "/proc/mounts"

-- * Luxi (Local UniX Interface) related constants

luxiEom :: PythonChar
luxiEom = PythonChar '\x03'

-- | Environment variable for the luxi override socket
luxiOverride :: String
luxiOverride = "FORCE_LUXI_SOCKET"

luxiOverrideMaster :: String
luxiOverrideMaster = "master"

luxiOverrideQuery :: String
luxiOverrideQuery = "query"

luxiVersion :: Int
luxiVersion = configVersion

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

exportConfFile :: String
exportConfFile = "config.ini"

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

xlSocatCmd :: String
xlSocatCmd = "socat -b524288 - TCP:%s:%d #"

xlMigrationPidfile :: String
xlMigrationPidfile = "socat.pid"

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

-- * LXC
-- If you are trying to change the value of these default constants, you also
-- need to edit the default value declaration in man/gnt-instance.rst.
lxcDevicesDefault :: String
lxcDevicesDefault =
     "c 1:3 rw"     -- /dev/null
  ++ ",c 1:5 rw"    -- /dev/zero
  ++ ",c 1:7 rw"    -- /dev/full
  ++ ",c 1:8 rw"    -- /dev/random
  ++ ",c 1:9 rw"    -- /dev/urandom
  ++ ",c 1:10 rw"   -- /dev/aio
  ++ ",c 5:0 rw"    -- /dev/tty
  ++ ",c 5:1 rw"    -- /dev/console
  ++ ",c 5:2 rw"    -- /dev/ptmx
  ++ ",c 136:* rw"  -- first block of Unix98 PTY slaves

lxcDropCapabilitiesDefault :: String
lxcDropCapabilitiesDefault =
     "mac_override" -- Allow MAC configuration or state changes
  ++ ",sys_boot"    -- Use reboot(2) and kexec_load(2)
  ++ ",sys_module"  -- Load and unload kernel modules
  ++ ",sys_time"    -- Set system clock, set real-time (hardware) clock
  ++ ",sys_admin"   -- Various system administration operations

lxcStateRunning :: String
lxcStateRunning = "RUNNING"

-- * Console types

-- | Display a message for console access
consMessage :: String
consMessage = "msg"

-- | Console as SPICE server
consSpice :: String
consSpice = "spice"

-- | Console as SSH command
consSsh :: String
consSsh = "ssh"

-- | Console as VNC server
consVnc :: String
consVnc = "vnc"

consAll :: FrozenSet String
consAll = ConstantUtils.mkSet [consMessage, consSpice, consSsh, consVnc]

-- | RSA key bit length
--
-- For RSA keys more bits are better, but they also make operations
-- more expensive. NIST SP 800-131 recommends a minimum of 2048 bits
-- from the year 2010 on.
rsaKeyBits :: Int
rsaKeyBits = 2048

-- | Ciphers allowed for SSL connections.
--
-- For the format, see ciphers(1). A better way to disable ciphers
-- would be to use the exclamation mark (!), but socat versions below
-- 1.5 can't parse exclamation marks in options properly. When
-- modifying the ciphers, ensure not to accidentially add something
-- after it's been removed. Use the "openssl" utility to check the
-- allowed ciphers, e.g.  "openssl ciphers -v HIGH:-DES".
opensslCiphers :: String
opensslCiphers = "HIGH:-DES:-3DES:-EXPORT:-DH"

-- * X509

-- | commonName (CN) used in certificates
x509CertCn :: String
x509CertCn = "ganeti.example.com"

-- | Default validity of certificates in days
x509CertDefaultValidity :: Int
x509CertDefaultValidity = 365 * 5

x509CertSignatureHeader :: String
x509CertSignatureHeader = "X-Ganeti-Signature"

-- | Digest used to sign certificates ("openssl x509" uses SHA1 by default)
x509CertSignDigest :: String
x509CertSignDigest = "SHA1"

-- * Import/export daemon mode

iemExport :: String
iemExport = "export"

iemImport :: String
iemImport = "import"

-- * Import/export transport compression

iecGzip :: String
iecGzip = "gzip"

iecGzipFast :: String
iecGzipFast = "gzip-fast"

iecGzipSlow :: String
iecGzipSlow = "gzip-slow"

iecLzop :: String
iecLzop = "lzop"

iecNone :: String
iecNone = "none"

iecAll :: [String]
iecAll = [iecGzip, iecGzipFast, iecGzipSlow, iecLzop, iecNone]

iecDefaultTools :: [String]
iecDefaultTools = [iecGzip, iecGzipFast, iecGzipSlow]

iecCompressionUtilities :: Map String String
iecCompressionUtilities =
  Map.fromList
  [ (iecGzipFast, iecGzip)
  , (iecGzipSlow, iecGzip)
  ]

ieCustomSize :: String
ieCustomSize = "fd"

-- * Import/export I/O

-- | Direct file I/O, equivalent to a shell's I/O redirection using
-- '<' or '>'
ieioFile :: String
ieioFile = "file"

-- | Raw block device I/O using "dd"
ieioRawDisk :: String
ieioRawDisk = "raw"

-- | OS definition import/export script
ieioScript :: String
ieioScript = "script"

-- * Values

valueDefault :: String
valueDefault = "default"

valueAuto :: String
valueAuto = "auto"

valueGenerate :: String
valueGenerate = "generate"

valueNone :: String
valueNone = "none"

valueTrue :: String
valueTrue = "true"

valueFalse :: String
valueFalse = "false"

-- * Hooks

hooksNameCfgupdate :: String
hooksNameCfgupdate = "config-update"

hooksNameWatcher :: String
hooksNameWatcher = "watcher"

hooksPath :: String
hooksPath = "/sbin:/bin:/usr/sbin:/usr/bin"

hooksPhasePost :: String
hooksPhasePost = "post"

hooksPhasePre :: String
hooksPhasePre = "pre"

hooksVersion :: Int
hooksVersion = 2

-- * Hooks subject type (what object type does the LU deal with)

htypeCluster :: String
htypeCluster = "CLUSTER"

htypeGroup :: String
htypeGroup = "GROUP"

htypeInstance :: String
htypeInstance = "INSTANCE"

htypeNetwork :: String
htypeNetwork = "NETWORK"

htypeNode :: String
htypeNode = "NODE"

-- * Hkr

hkrSkip :: Int
hkrSkip = 0

hkrFail :: Int
hkrFail = 1

hkrSuccess :: Int
hkrSuccess = 2

-- * Storage types

stBlock :: String
stBlock = Types.storageTypeToRaw StorageBlock

stDiskless :: String
stDiskless = Types.storageTypeToRaw StorageDiskless

stExt :: String
stExt = Types.storageTypeToRaw StorageExt

stFile :: String
stFile = Types.storageTypeToRaw StorageFile

stSharedFile :: String
stSharedFile = Types.storageTypeToRaw StorageSharedFile

stGluster :: String
stGluster = Types.storageTypeToRaw StorageGluster

stLvmPv :: String
stLvmPv = Types.storageTypeToRaw StorageLvmPv

stLvmVg :: String
stLvmVg = Types.storageTypeToRaw StorageLvmVg

stRados :: String
stRados = Types.storageTypeToRaw StorageRados

storageTypes :: FrozenSet String
storageTypes = ConstantUtils.mkSet $ map Types.storageTypeToRaw [minBound..]

-- | The set of storage types for which full storage reporting is available
stsReport :: FrozenSet String
stsReport = ConstantUtils.mkSet [stFile, stLvmPv, stLvmVg]

-- | The set of storage types for which node storage reporting is available
-- | (as used by LUQueryNodeStorage)
stsReportNodeStorage :: FrozenSet String
stsReportNodeStorage = ConstantUtils.union stsReport $
                                           ConstantUtils.mkSet [ stSharedFile
                                                               , stGluster
                                                               ]

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

validStorageFields :: FrozenSet String
validStorageFields =
  ConstantUtils.mkSet $ map Types.storageFieldToRaw [minBound..] ++
                        [sfNode, sfType]

modifiableStorageFields :: Map String (FrozenSet String)
modifiableStorageFields =
  Map.fromList [(Types.storageTypeToRaw StorageLvmPv,
                 ConstantUtils.mkSet [sfAllocatable])]

-- * Storage operations

soFixConsistency :: String
soFixConsistency = "fix-consistency"

validStorageOperations :: Map String (FrozenSet String)
validStorageOperations =
  Map.fromList [(Types.storageTypeToRaw StorageLvmVg,
                 ConstantUtils.mkSet [soFixConsistency])]

-- * Volume fields

vfDev :: String
vfDev = "dev"

vfInstance :: String
vfInstance = "instance"

vfName :: String
vfName = "name"

vfNode :: String
vfNode = "node"

vfPhys :: String
vfPhys = "phys"

vfSize :: String
vfSize = "size"

vfVg :: String
vfVg = "vg"

-- * Local disk status

ldsFaulty :: Int
ldsFaulty = Types.localDiskStatusToRaw DiskStatusFaulty

ldsOkay :: Int
ldsOkay = Types.localDiskStatusToRaw DiskStatusOk

ldsUnknown :: Int
ldsUnknown = Types.localDiskStatusToRaw DiskStatusUnknown

ldsSync :: Int
ldsSync = Types.localDiskStatusToRaw DiskStatusSync

ldsNames :: Map Int String
ldsNames =
  Map.fromList [ (Types.localDiskStatusToRaw ds,
                  localDiskStatusName ds) | ds <- [minBound..] ]

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

dtGluster :: String
dtGluster = Types.diskTemplateToRaw DTGluster

dtMixed :: String
dtMixed = "mixed"

-- | This is used to order determine the default disk template when
-- the list of enabled disk templates is inferred from the current
-- state of the cluster.  This only happens on an upgrade from a
-- version of Ganeti that did not support the 'enabled_disk_templates'
-- so far.
diskTemplatePreference :: [String]
diskTemplatePreference =
  map Types.diskTemplateToRaw
  [DTBlock, DTDiskless, DTDrbd8, DTExt, DTFile,
   DTPlain, DTRbd, DTSharedFile, DTGluster]

diskTemplates :: FrozenSet String
diskTemplates = ConstantUtils.mkSet $ map Types.diskTemplateToRaw [minBound..]

-- | Disk templates that are enabled by default
defaultEnabledDiskTemplates :: [String]
defaultEnabledDiskTemplates = map Types.diskTemplateToRaw [DTDrbd8, DTPlain]

-- | Mapping of disk templates to storage types
mapDiskTemplateStorageType :: Map String String
mapDiskTemplateStorageType =
  Map.fromList $
  map (   Types.diskTemplateToRaw
      &&& Types.storageTypeToRaw . diskTemplateToStorageType)
  [minBound..maxBound]

-- | The set of network-mirrored disk templates
dtsIntMirror :: FrozenSet String
dtsIntMirror = ConstantUtils.mkSet [dtDrbd8]

-- | 'DTDiskless' is 'trivially' externally mirrored
dtsExtMirror :: FrozenSet String
dtsExtMirror =
  ConstantUtils.mkSet $
  map Types.diskTemplateToRaw
  [DTDiskless, DTBlock, DTExt, DTSharedFile, DTRbd, DTGluster]

-- | The set of non-lvm-based disk templates
dtsNotLvm :: FrozenSet String
dtsNotLvm =
  ConstantUtils.mkSet $
  map Types.diskTemplateToRaw
  [DTSharedFile, DTDiskless, DTBlock, DTExt, DTFile, DTRbd, DTGluster]

-- | The set of disk templates which can be grown
dtsGrowable :: FrozenSet String
dtsGrowable =
  ConstantUtils.mkSet $
  map Types.diskTemplateToRaw
  [DTSharedFile, DTDrbd8, DTPlain, DTExt, DTFile, DTRbd, DTGluster]

-- | The set of disk templates that allow adoption
dtsMayAdopt :: FrozenSet String
dtsMayAdopt =
  ConstantUtils.mkSet $ map Types.diskTemplateToRaw [DTBlock, DTPlain]

-- | The set of disk templates that *must* use adoption
dtsMustAdopt :: FrozenSet String
dtsMustAdopt = ConstantUtils.mkSet [Types.diskTemplateToRaw DTBlock]

-- | The set of disk templates that allow migrations
dtsMirrored :: FrozenSet String
dtsMirrored = dtsIntMirror `ConstantUtils.union` dtsExtMirror

-- | The set of file based disk templates
dtsFilebased :: FrozenSet String
dtsFilebased =
  ConstantUtils.mkSet $ map Types.diskTemplateToRaw
  [DTSharedFile, DTFile, DTGluster]

-- | The set of file based disk templates whose path is tied to the instance
-- name
dtsInstanceDependentPath :: FrozenSet String
dtsInstanceDependentPath =
  ConstantUtils.mkSet $ map Types.diskTemplateToRaw
  [DTSharedFile, DTFile]

-- | The set of disk templates that can be moved by copying
--
-- Note: a requirement is that they're not accessed externally or
-- shared between nodes; in particular, sharedfile is not suitable.
dtsCopyable :: FrozenSet String
dtsCopyable =
  ConstantUtils.mkSet $ map Types.diskTemplateToRaw [DTPlain, DTFile]

-- | The set of disk templates which can be snapshot.
dtsSnapshotCapable :: FrozenSet String
dtsSnapshotCapable =
  ConstantUtils.mkSet $ map Types.diskTemplateToRaw [DTPlain, DTDrbd8, DTExt]

-- | The set of disk templates that are supported by exclusive_storage
dtsExclStorage :: FrozenSet String
dtsExclStorage = ConstantUtils.mkSet $ map Types.diskTemplateToRaw [DTPlain]

-- | Templates for which we don't perform checks on free space
dtsNoFreeSpaceCheck :: FrozenSet String
dtsNoFreeSpaceCheck =
  ConstantUtils.mkSet $
  map Types.diskTemplateToRaw [DTExt, DTSharedFile, DTFile, DTRbd, DTGluster]

dtsBlock :: FrozenSet String
dtsBlock =
  ConstantUtils.mkSet $
  map Types.diskTemplateToRaw [DTPlain, DTDrbd8, DTBlock, DTRbd, DTExt]

-- | The set of lvm-based disk templates
dtsLvm :: FrozenSet String
dtsLvm = diskTemplates `ConstantUtils.difference` dtsNotLvm

-- | The set of lvm-based disk templates
dtsHaveAccess :: FrozenSet String
dtsHaveAccess = ConstantUtils.mkSet $
  map Types.diskTemplateToRaw [DTRbd, DTGluster, DTExt]

-- | The set of disk templates that cannot convert from
dtsNotConvertibleFrom :: FrozenSet String
dtsNotConvertibleFrom =
  ConstantUtils.mkSet $
  map Types.diskTemplateToRaw [DTDiskless]

-- | The set of disk templates that cannot convert to
dtsNotConvertibleTo :: FrozenSet String
dtsNotConvertibleTo =
  ConstantUtils.mkSet $
  map Types.diskTemplateToRaw [DTDiskless, DTBlock]

-- * Drbd

drbdHmacAlg :: String
drbdHmacAlg = "md5"

drbdDefaultNetProtocol :: String
drbdDefaultNetProtocol = "C"

drbdMigrationNetProtocol :: String
drbdMigrationNetProtocol = "C"

drbdStatusFile :: String
drbdStatusFile = "/proc/drbd"

-- | The length of generated DRBD secrets (see also TempRes module).
drbdSecretLength :: Int
drbdSecretLength = 20

-- | Size of DRBD meta block device
drbdMetaSize :: Int
drbdMetaSize = 128

-- * Drbd barrier types

drbdBDiskBarriers :: String
drbdBDiskBarriers = "b"

drbdBDiskDrain :: String
drbdBDiskDrain = "d"

drbdBDiskFlush :: String
drbdBDiskFlush = "f"

drbdBNone :: String
drbdBNone = "n"

-- | Valid barrier combinations: "n" or any non-null subset of "bfd"
drbdValidBarrierOpt :: FrozenSet (FrozenSet String)
drbdValidBarrierOpt =
  ConstantUtils.mkSet
  [ ConstantUtils.mkSet [drbdBNone]
  , ConstantUtils.mkSet [drbdBDiskBarriers]
  , ConstantUtils.mkSet [drbdBDiskDrain]
  , ConstantUtils.mkSet [drbdBDiskFlush]
  , ConstantUtils.mkSet [drbdBDiskDrain, drbdBDiskFlush]
  , ConstantUtils.mkSet [drbdBDiskBarriers, drbdBDiskDrain]
  , ConstantUtils.mkSet [drbdBDiskBarriers, drbdBDiskFlush]
  , ConstantUtils.mkSet [drbdBDiskBarriers, drbdBDiskFlush, drbdBDiskDrain]
  ]

-- | Rbd tool command
rbdCmd :: String
rbdCmd = "rbd"

-- * File backend driver

fdBlktap :: String
fdBlktap = Types.fileDriverToRaw FileBlktap

fdBlktap2 :: String
fdBlktap2 = Types.fileDriverToRaw FileBlktap2

fdLoop :: String
fdLoop = Types.fileDriverToRaw FileLoop

fdDefault :: String
fdDefault = fdLoop

fileDriver :: FrozenSet String
fileDriver =
  ConstantUtils.mkSet $
  map Types.fileDriverToRaw [minBound..]

-- | The set of drbd-like disk types
dtsDrbd :: FrozenSet String
dtsDrbd = ConstantUtils.mkSet [Types.diskTemplateToRaw DTDrbd8]

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

-- * Remote import/export handshake message and version

rieHandshake :: String
rieHandshake = "Hi, I'm Ganeti"

rieVersion :: Int
rieVersion = 0

-- | Remote import/export certificate validity (seconds)
rieCertValidity :: Int
rieCertValidity = 24 * 60 * 60

-- | Export only: how long to wait per connection attempt (seconds)
rieConnectAttemptTimeout :: Int
rieConnectAttemptTimeout = 20

-- | Export only: number of attempts to connect
rieConnectRetries :: Int
rieConnectRetries = 10

-- | Overall timeout for establishing connection
rieConnectTimeout :: Int
rieConnectTimeout = 180

-- | Give child process up to 5 seconds to exit after sending a signal
childLingerTimeout :: Double
childLingerTimeout = 5.0

-- * Import/export config options

inisectBep :: String
inisectBep = "backend"

inisectExp :: String
inisectExp = "export"

inisectHyp :: String
inisectHyp = "hypervisor"

inisectIns :: String
inisectIns = "instance"

inisectOsp :: String
inisectOsp = "os"

inisectOspPrivate :: String
inisectOspPrivate = "os_private"

-- * Dynamic device modification

ddmAdd :: String
ddmAdd = Types.ddmFullToRaw DdmFullAdd

ddmAttach :: String
ddmAttach = Types.ddmFullToRaw DdmFullAttach

ddmModify :: String
ddmModify = Types.ddmFullToRaw DdmFullModify

ddmRemove :: String
ddmRemove = Types.ddmFullToRaw DdmFullRemove

ddmDetach :: String
ddmDetach = Types.ddmFullToRaw DdmFullDetach

ddmsValues :: FrozenSet String
ddmsValues = ConstantUtils.mkSet [ddmAdd, ddmAttach, ddmRemove, ddmDetach]

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

-- * Others

defaultBridge :: String
defaultBridge = AutoConf.defaultBridge

defaultOvs :: String
defaultOvs = "switch1"

-- | 60 MiB/s, expressed in KiB/s
classicDrbdSyncSpeed :: Int
classicDrbdSyncSpeed = 60 * 1024

ip4AddressAny :: String
ip4AddressAny = "0.0.0.0"

ip4AddressLocalhost :: String
ip4AddressLocalhost = "127.0.0.1"

ip6AddressAny :: String
ip6AddressAny = "::"

ip6AddressLocalhost :: String
ip6AddressLocalhost = "::1"

ip4Version :: Int
ip4Version = 4

ip6Version :: Int
ip6Version = 6

validIpVersions :: FrozenSet Int
validIpVersions = ConstantUtils.mkSet [ip4Version, ip6Version]

tcpPingTimeout :: Int
tcpPingTimeout = 10

defaultVg :: String
defaultVg = AutoConf.defaultVg

defaultDrbdHelper :: String
defaultDrbdHelper = "/bin/true"

minVgSize :: Int
minVgSize = 20480

defaultMacPrefix :: String
defaultMacPrefix = "aa:00:00"

-- | Default maximum instance wait time (seconds)
defaultShutdownTimeout :: Int
defaultShutdownTimeout = 120

-- | Node clock skew (seconds)
nodeMaxClockSkew :: Int
nodeMaxClockSkew = 150

-- | Time for an intra-cluster disk transfer to wait for a connection
diskTransferConnectTimeout :: Int
diskTransferConnectTimeout = 60

-- | Disk index separator
diskSeparator :: String
diskSeparator = AutoConf.diskSeparator

ipCommandPath :: String
ipCommandPath = AutoConf.ipPath

-- | Key for job IDs in opcode result
jobIdsKey :: String
jobIdsKey = "jobs"

-- * Runparts results

runpartsErr :: Int
runpartsErr = 2

runpartsRun :: Int
runpartsRun = 1

runpartsSkip :: Int
runpartsSkip = 0

runpartsStatus :: [Int]
runpartsStatus = [runpartsErr, runpartsRun, runpartsSkip]

-- * RPC

rpcEncodingNone :: Int
rpcEncodingNone = 0

rpcEncodingZlibBase64 :: Int
rpcEncodingZlibBase64 = 1

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

-- OS

osScriptCreate :: String
osScriptCreate = "create"

osScriptCreateUntrusted :: String
osScriptCreateUntrusted = "create_untrusted"

osScriptExport :: String
osScriptExport = "export"

osScriptImport :: String
osScriptImport = "import"

osScriptRename :: String
osScriptRename = "rename"

osScriptVerify :: String
osScriptVerify = "verify"

osScripts :: [String]
osScripts = [osScriptCreate, osScriptCreateUntrusted, osScriptExport,
             osScriptImport, osScriptRename, osScriptVerify]

osApiFile :: String
osApiFile = "ganeti_api_version"

osVariantsFile :: String
osVariantsFile = "variants.list"

osParametersFile :: String
osParametersFile = "parameters.list"

osValidateParameters :: String
osValidateParameters = "parameters"

osValidateCalls :: FrozenSet String
osValidateCalls = ConstantUtils.mkSet [osValidateParameters]

-- | External Storage (ES) related constants

esActionAttach :: String
esActionAttach = "attach"

esActionCreate :: String
esActionCreate = "create"

esActionDetach :: String
esActionDetach = "detach"

esActionGrow :: String
esActionGrow = "grow"

esActionRemove :: String
esActionRemove = "remove"

esActionSetinfo :: String
esActionSetinfo = "setinfo"

esActionVerify :: String
esActionVerify = "verify"

esActionSnapshot :: String
esActionSnapshot = "snapshot"

esActionOpen :: String
esActionOpen = "open"

esActionClose :: String
esActionClose = "close"

esScriptCreate :: String
esScriptCreate = esActionCreate

esScriptRemove :: String
esScriptRemove = esActionRemove

esScriptGrow :: String
esScriptGrow = esActionGrow

esScriptAttach :: String
esScriptAttach = esActionAttach

esScriptDetach :: String
esScriptDetach = esActionDetach

esScriptSetinfo :: String
esScriptSetinfo = esActionSetinfo

esScriptVerify :: String
esScriptVerify = esActionVerify

esScriptSnapshot :: String
esScriptSnapshot = esActionSnapshot

esScriptOpen :: String
esScriptOpen = esActionOpen

esScriptClose :: String
esScriptClose = esActionClose

esScripts :: FrozenSet String
esScripts =
  ConstantUtils.mkSet [esScriptAttach,
                       esScriptCreate,
                       esScriptDetach,
                       esScriptGrow,
                       esScriptRemove,
                       esScriptSetinfo,
                       esScriptVerify,
                       esScriptSnapshot,
                       esScriptOpen,
                       esScriptClose]

esParametersFile :: String
esParametersFile = "parameters.list"

-- * Reboot types

instanceRebootSoft :: String
instanceRebootSoft = Types.rebootTypeToRaw RebootSoft

instanceRebootHard :: String
instanceRebootHard = Types.rebootTypeToRaw RebootHard

instanceRebootFull :: String
instanceRebootFull = Types.rebootTypeToRaw RebootFull

rebootTypes :: FrozenSet String
rebootTypes = ConstantUtils.mkSet $ map Types.rebootTypeToRaw [minBound..]

-- * Instance reboot behaviors

instanceRebootAllowed :: String
instanceRebootAllowed = "reboot"

instanceRebootExit :: String
instanceRebootExit = "exit"

rebootBehaviors :: [String]
rebootBehaviors = [instanceRebootAllowed, instanceRebootExit]

-- * VTypes

vtypeBool :: VType
vtypeBool = VTypeBool

vtypeInt :: VType
vtypeInt = VTypeInt

vtypeFloat :: VType
vtypeFloat = VTypeFloat

vtypeMaybeString :: VType
vtypeMaybeString = VTypeMaybeString

-- | Size in MiBs
vtypeSize :: VType
vtypeSize = VTypeSize

vtypeString :: VType
vtypeString = VTypeString

enforceableTypes :: FrozenSet VType
enforceableTypes = ConstantUtils.mkSet [minBound..]

-- | Constant representing that the user does not specify any IP version
ifaceNoIpVersionSpecified :: Int
ifaceNoIpVersionSpecified = 0

validSerialSpeeds :: [Int]
validSerialSpeeds =
  [75,
   110,
   300,
   600,
   1200,
   1800,
   2400,
   4800,
   9600,
   14400,
   19200,
   28800,
   38400,
   57600,
   115200,
   230400,
   345600,
   460800]

-- * HV parameter names (global namespace)

hvAcpi :: String
hvAcpi = "acpi"

hvBlockdevPrefix :: String
hvBlockdevPrefix = "blockdev_prefix"

hvBootloaderArgs :: String
hvBootloaderArgs = "bootloader_args"

hvBootloaderPath :: String
hvBootloaderPath = "bootloader_path"

hvBootOrder :: String
hvBootOrder = "boot_order"

hvCdromImagePath :: String
hvCdromImagePath = "cdrom_image_path"

hvCpuCap :: String
hvCpuCap = "cpu_cap"

hvCpuCores :: String
hvCpuCores = "cpu_cores"

hvCpuMask :: String
hvCpuMask = "cpu_mask"

hvCpuSockets :: String
hvCpuSockets = "cpu_sockets"

hvCpuThreads :: String
hvCpuThreads = "cpu_threads"

hvCpuType :: String
hvCpuType = "cpu_type"

hvCpuWeight :: String
hvCpuWeight = "cpu_weight"

hvDeviceModel :: String
hvDeviceModel = "device_model"

hvDiskCache :: String
hvDiskCache = "disk_cache"

hvDiskDiscard :: String
hvDiskDiscard = "disk_discard"

hvDiskType :: String
hvDiskType = "disk_type"

hvInitrdPath :: String
hvInitrdPath = "initrd_path"

hvInitScript :: String
hvInitScript = "init_script"

hvKernelArgs :: String
hvKernelArgs = "kernel_args"

hvKernelPath :: String
hvKernelPath = "kernel_path"

hvKeymap :: String
hvKeymap = "keymap"

hvKvmCdrom2ImagePath :: String
hvKvmCdrom2ImagePath = "cdrom2_image_path"

hvKvmCdromDiskType :: String
hvKvmCdromDiskType = "cdrom_disk_type"

hvKvmExtra :: String
hvKvmExtra = "kvm_extra"

hvKvmFlag :: String
hvKvmFlag = "kvm_flag"

hvKvmFloppyImagePath :: String
hvKvmFloppyImagePath = "floppy_image_path"

hvKvmMachineVersion :: String
hvKvmMachineVersion = "machine_version"

hvKvmMigrationCaps :: String
hvKvmMigrationCaps = "migration_caps"

hvKvmPath :: String
hvKvmPath = "kvm_path"

hvKvmDiskAio :: String
hvKvmDiskAio = "disk_aio"

hvKvmScsiControllerType :: String
hvKvmScsiControllerType = "scsi_controller_type"

hvKvmPciReservations :: String
hvKvmPciReservations = "kvm_pci_reservations"

hvKvmSpiceAudioCompr :: String
hvKvmSpiceAudioCompr = "spice_playback_compression"

hvKvmSpiceBind :: String
hvKvmSpiceBind = "spice_bind"

hvKvmSpiceIpVersion :: String
hvKvmSpiceIpVersion = "spice_ip_version"

hvKvmSpiceJpegImgCompr :: String
hvKvmSpiceJpegImgCompr = "spice_jpeg_wan_compression"

hvKvmSpiceLosslessImgCompr :: String
hvKvmSpiceLosslessImgCompr = "spice_image_compression"

hvKvmSpicePasswordFile :: String
hvKvmSpicePasswordFile = "spice_password_file"

hvKvmSpiceStreamingVideoDetection :: String
hvKvmSpiceStreamingVideoDetection = "spice_streaming_video"

hvKvmSpiceTlsCiphers :: String
hvKvmSpiceTlsCiphers = "spice_tls_ciphers"

hvKvmSpiceUseTls :: String
hvKvmSpiceUseTls = "spice_use_tls"

hvKvmSpiceUseVdagent :: String
hvKvmSpiceUseVdagent = "spice_use_vdagent"

hvKvmSpiceZlibGlzImgCompr :: String
hvKvmSpiceZlibGlzImgCompr = "spice_zlib_glz_wan_compression"

hvKvmUseChroot :: String
hvKvmUseChroot = "use_chroot"

hvKvmUserShutdown :: String
hvKvmUserShutdown = "user_shutdown"

hvLxcStartupTimeout :: String
hvLxcStartupTimeout = "startup_timeout"

hvLxcExtraCgroups :: String
hvLxcExtraCgroups = "extra_cgroups"

hvLxcDevices :: String
hvLxcDevices = "devices"

hvLxcDropCapabilities :: String
hvLxcDropCapabilities = "drop_capabilities"

hvLxcExtraConfig :: String
hvLxcExtraConfig = "extra_config"

hvLxcNumTtys :: String
hvLxcNumTtys = "num_ttys"

hvMemPath :: String
hvMemPath = "mem_path"

hvMigrationBandwidth :: String
hvMigrationBandwidth = "migration_bandwidth"

hvMigrationDowntime :: String
hvMigrationDowntime = "migration_downtime"

hvMigrationMode :: String
hvMigrationMode = "migration_mode"

hvMigrationPort :: String
hvMigrationPort = "migration_port"

hvNicType :: String
hvNicType = "nic_type"

hvPae :: String
hvPae = "pae"

hvPassthrough :: String
hvPassthrough = "pci_pass"

hvRebootBehavior :: String
hvRebootBehavior = "reboot_behavior"

hvRootPath :: String
hvRootPath = "root_path"

hvSecurityDomain :: String
hvSecurityDomain = "security_domain"

hvSecurityModel :: String
hvSecurityModel = "security_model"

hvSerialConsole :: String
hvSerialConsole = "serial_console"

hvSerialSpeed :: String
hvSerialSpeed = "serial_speed"

hvSoundhw :: String
hvSoundhw = "soundhw"

hvUsbDevices :: String
hvUsbDevices = "usb_devices"

hvUsbMouse :: String
hvUsbMouse = "usb_mouse"

hvUseBootloader :: String
hvUseBootloader = "use_bootloader"

hvUseGuestAgent :: String
hvUseGuestAgent = "use_guest_agent"

hvUseLocaltime :: String
hvUseLocaltime = "use_localtime"

hvVga :: String
hvVga = "vga"

hvVhostNet :: String
hvVhostNet = "vhost_net"

hvVirtioNetQueues :: String
hvVirtioNetQueues = "virtio_net_queues"

hvVifScript :: String
hvVifScript = "vif_script"

hvVifType :: String
hvVifType = "vif_type"

hvViridian :: String
hvViridian = "viridian"

hvVncBindAddress :: String
hvVncBindAddress = "vnc_bind_address"

hvVncPasswordFile :: String
hvVncPasswordFile = "vnc_password_file"

hvVncTls :: String
hvVncTls = "vnc_tls"

hvVncX509 :: String
hvVncX509 = "vnc_x509_path"

hvVncX509Verify :: String
hvVncX509Verify = "vnc_x509_verify"

hvVnetHdr :: String
hvVnetHdr = "vnet_hdr"

hvXenCmd :: String
hvXenCmd = "xen_cmd"

hvXenCpuid :: String
hvXenCpuid = "cpuid"

hvsParameterTitles :: Map String String
hvsParameterTitles =
  Map.fromList
  [(hvAcpi, "ACPI"),
   (hvBootOrder, "Boot_order"),
   (hvCdromImagePath, "CDROM_image_path"),
   (hvCpuType, "cpu_type"),
   (hvDiskType, "Disk_type"),
   (hvInitrdPath, "Initrd_path"),
   (hvKernelPath, "Kernel_path"),
   (hvNicType, "NIC_type"),
   (hvPae, "PAE"),
   (hvPassthrough, "pci_pass"),
   (hvVncBindAddress, "VNC_bind_address")]

hvsParameters :: FrozenSet String
hvsParameters = ConstantUtils.mkSet $ Map.keys hvsParameterTypes

hvsParameterTypes :: Map String VType
hvsParameterTypes = Map.fromList
  [ (hvAcpi,                            VTypeBool)
  , (hvBlockdevPrefix,                  VTypeString)
  , (hvBootloaderArgs,                  VTypeString)
  , (hvBootloaderPath,                  VTypeString)
  , (hvBootOrder,                       VTypeString)
  , (hvCdromImagePath,                  VTypeString)
  , (hvCpuCap,                          VTypeInt)
  , (hvCpuCores,                        VTypeInt)
  , (hvCpuMask,                         VTypeString)
  , (hvCpuSockets,                      VTypeInt)
  , (hvCpuThreads,                      VTypeInt)
  , (hvCpuType,                         VTypeString)
  , (hvCpuWeight,                       VTypeInt)
  , (hvDeviceModel,                     VTypeString)
  , (hvDiskCache,                       VTypeString)
  , (hvDiskDiscard,                     VTypeString)
  , (hvDiskType,                        VTypeString)
  , (hvInitrdPath,                      VTypeString)
  , (hvInitScript,                      VTypeString)
  , (hvKernelArgs,                      VTypeString)
  , (hvKernelPath,                      VTypeString)
  , (hvKeymap,                          VTypeString)
  , (hvKvmCdrom2ImagePath,              VTypeString)
  , (hvKvmCdromDiskType,                VTypeString)
  , (hvKvmExtra,                        VTypeString)
  , (hvKvmFlag,                         VTypeString)
  , (hvKvmFloppyImagePath,              VTypeString)
  , (hvKvmMachineVersion,               VTypeString)
  , (hvKvmMigrationCaps,                VTypeString)
  , (hvKvmPath,                         VTypeString)
  , (hvKvmDiskAio,                      VTypeString)
  , (hvKvmScsiControllerType,           VTypeString)
  , (hvKvmPciReservations,              VTypeInt)
  , (hvKvmSpiceAudioCompr,              VTypeBool)
  , (hvKvmSpiceBind,                    VTypeString)
  , (hvKvmSpiceIpVersion,               VTypeInt)
  , (hvKvmSpiceJpegImgCompr,            VTypeString)
  , (hvKvmSpiceLosslessImgCompr,        VTypeString)
  , (hvKvmSpicePasswordFile,            VTypeString)
  , (hvKvmSpiceStreamingVideoDetection, VTypeString)
  , (hvKvmSpiceTlsCiphers,              VTypeString)
  , (hvKvmSpiceUseTls,                  VTypeBool)
  , (hvKvmSpiceUseVdagent,              VTypeBool)
  , (hvKvmSpiceZlibGlzImgCompr,         VTypeString)
  , (hvKvmUseChroot,                    VTypeBool)
  , (hvKvmUserShutdown,                 VTypeBool)
  , (hvLxcDevices,                      VTypeString)
  , (hvLxcDropCapabilities,             VTypeString)
  , (hvLxcExtraCgroups,                 VTypeString)
  , (hvLxcExtraConfig,                  VTypeString)
  , (hvLxcNumTtys,                      VTypeInt)
  , (hvLxcStartupTimeout,               VTypeInt)
  , (hvMemPath,                         VTypeString)
  , (hvMigrationBandwidth,              VTypeInt)
  , (hvMigrationDowntime,               VTypeInt)
  , (hvMigrationMode,                   VTypeString)
  , (hvMigrationPort,                   VTypeInt)
  , (hvNicType,                         VTypeString)
  , (hvPae,                             VTypeBool)
  , (hvPassthrough,                     VTypeString)
  , (hvRebootBehavior,                  VTypeString)
  , (hvRootPath,                        VTypeMaybeString)
  , (hvSecurityDomain,                  VTypeString)
  , (hvSecurityModel,                   VTypeString)
  , (hvSerialConsole,                   VTypeBool)
  , (hvSerialSpeed,                     VTypeInt)
  , (hvSoundhw,                         VTypeString)
  , (hvUsbDevices,                      VTypeString)
  , (hvUsbMouse,                        VTypeString)
  , (hvUseBootloader,                   VTypeBool)
  , (hvUseGuestAgent,                   VTypeBool)
  , (hvUseLocaltime,                    VTypeBool)
  , (hvVga,                             VTypeString)
  , (hvVhostNet,                        VTypeBool)
  , (hvVirtioNetQueues,                 VTypeInt)
  , (hvVifScript,                       VTypeString)
  , (hvVifType,                         VTypeString)
  , (hvViridian,                        VTypeBool)
  , (hvVncBindAddress,                  VTypeString)
  , (hvVncPasswordFile,                 VTypeString)
  , (hvVncTls,                          VTypeBool)
  , (hvVncX509,                         VTypeString)
  , (hvVncX509Verify,                   VTypeBool)
  , (hvVnetHdr,                         VTypeBool)
  , (hvXenCmd,                          VTypeString)
  , (hvXenCpuid,                        VTypeString)
  ]

-- * Migration statuses

hvMigrationActive :: String
hvMigrationActive = "active"

hvMigrationCancelled :: String
hvMigrationCancelled = "cancelled"

hvMigrationCompleted :: String
hvMigrationCompleted = "completed"

hvMigrationFailed :: String
hvMigrationFailed = "failed"

hvMigrationValidStatuses :: FrozenSet String
hvMigrationValidStatuses =
  ConstantUtils.mkSet [hvMigrationActive,
                       hvMigrationCancelled,
                       hvMigrationCompleted,
                       hvMigrationFailed]

hvMigrationFailedStatuses :: FrozenSet String
hvMigrationFailedStatuses =
  ConstantUtils.mkSet [hvMigrationFailed, hvMigrationCancelled]

-- | KVM-specific statuses
--
-- FIXME: this constant seems unnecessary
hvKvmMigrationValidStatuses :: FrozenSet String
hvKvmMigrationValidStatuses = hvMigrationValidStatuses

-- | Node info keys
hvNodeinfoKeyVersion :: String
hvNodeinfoKeyVersion = "hv_version"

-- * Hypervisor state

hvstCpuNode :: String
hvstCpuNode = "cpu_node"

hvstCpuTotal :: String
hvstCpuTotal = "cpu_total"

hvstMemoryHv :: String
hvstMemoryHv = "mem_hv"

hvstMemoryNode :: String
hvstMemoryNode = "mem_node"

hvstMemoryTotal :: String
hvstMemoryTotal = "mem_total"

hvstsParameters :: FrozenSet String
hvstsParameters =
  ConstantUtils.mkSet [hvstCpuNode,
                       hvstCpuTotal,
                       hvstMemoryHv,
                       hvstMemoryNode,
                       hvstMemoryTotal]

hvstDefaults :: Map String Int
hvstDefaults =
  Map.fromList
  [(hvstCpuNode, 1),
   (hvstCpuTotal, 1),
   (hvstMemoryHv, 0),
   (hvstMemoryTotal, 0),
   (hvstMemoryNode, 0)]

hvstsParameterTypes :: Map String VType
hvstsParameterTypes =
  Map.fromList [(hvstMemoryTotal, VTypeInt),
                (hvstMemoryNode, VTypeInt),
                (hvstMemoryHv, VTypeInt),
                (hvstCpuTotal, VTypeInt),
                (hvstCpuNode, VTypeInt)]

-- * Disk state

dsDiskOverhead :: String
dsDiskOverhead = "disk_overhead"

dsDiskReserved :: String
dsDiskReserved = "disk_reserved"

dsDiskTotal :: String
dsDiskTotal = "disk_total"

dsDefaults :: Map String Int
dsDefaults =
  Map.fromList
  [(dsDiskTotal, 0),
   (dsDiskReserved, 0),
   (dsDiskOverhead, 0)]

dssParameterTypes :: Map String VType
dssParameterTypes =
  Map.fromList [(dsDiskTotal, VTypeInt),
                (dsDiskReserved, VTypeInt),
                (dsDiskOverhead, VTypeInt)]

dssParameters :: FrozenSet String
dssParameters =
  ConstantUtils.mkSet [dsDiskTotal, dsDiskReserved, dsDiskOverhead]

dsValidTypes :: FrozenSet String
dsValidTypes = ConstantUtils.mkSet [Types.diskTemplateToRaw DTPlain]

-- Backend parameter names

beAlwaysFailover :: String
beAlwaysFailover = "always_failover"

beAutoBalance :: String
beAutoBalance = "auto_balance"

beMaxmem :: String
beMaxmem = "maxmem"

-- | Deprecated and replaced by max and min mem
beMemory :: String
beMemory = "memory"

beMinmem :: String
beMinmem = "minmem"

beSpindleUse :: String
beSpindleUse = "spindle_use"

beVcpus :: String
beVcpus = "vcpus"

besParameterTypes :: Map String VType
besParameterTypes =
  Map.fromList [(beAlwaysFailover, VTypeBool),
                (beAutoBalance, VTypeBool),
                (beMaxmem, VTypeSize),
                (beMinmem, VTypeSize),
                (beSpindleUse, VTypeInt),
                (beVcpus, VTypeInt)]

besParameterTitles :: Map String String
besParameterTitles =
  Map.fromList [(beAutoBalance, "Auto_balance"),
                (beMinmem, "ConfigMinMem"),
                (beVcpus, "ConfigVCPUs"),
                (beMaxmem, "ConfigMaxMem")]

besParameterCompat :: Map String VType
besParameterCompat = Map.insert beMemory VTypeSize besParameterTypes

besParameters :: FrozenSet String
besParameters =
  ConstantUtils.mkSet [beAlwaysFailover,
                       beAutoBalance,
                       beMaxmem,
                       beMinmem,
                       beSpindleUse,
                       beVcpus]

-- | Instance specs
--
-- FIXME: these should be associated with 'Ganeti.HTools.Types.ISpec'

ispecMemSize :: String
ispecMemSize = ConstantUtils.ispecMemSize

ispecCpuCount :: String
ispecCpuCount = ConstantUtils.ispecCpuCount

ispecDiskCount :: String
ispecDiskCount = ConstantUtils.ispecDiskCount

ispecDiskSize :: String
ispecDiskSize = ConstantUtils.ispecDiskSize

ispecNicCount :: String
ispecNicCount = ConstantUtils.ispecNicCount

ispecSpindleUse :: String
ispecSpindleUse = ConstantUtils.ispecSpindleUse

ispecsParameterTypes :: Map String VType
ispecsParameterTypes =
  Map.fromList
  [(ConstantUtils.ispecDiskSize, VTypeInt),
   (ConstantUtils.ispecCpuCount, VTypeInt),
   (ConstantUtils.ispecSpindleUse, VTypeInt),
   (ConstantUtils.ispecMemSize, VTypeInt),
   (ConstantUtils.ispecNicCount, VTypeInt),
   (ConstantUtils.ispecDiskCount, VTypeInt)]

ispecsParameters :: FrozenSet String
ispecsParameters =
  ConstantUtils.mkSet [ConstantUtils.ispecCpuCount,
                       ConstantUtils.ispecDiskCount,
                       ConstantUtils.ispecDiskSize,
                       ConstantUtils.ispecMemSize,
                       ConstantUtils.ispecNicCount,
                       ConstantUtils.ispecSpindleUse]

ispecsMinmax :: String
ispecsMinmax = ConstantUtils.ispecsMinmax

ispecsMax :: String
ispecsMax = "max"

ispecsMin :: String
ispecsMin = "min"

ispecsStd :: String
ispecsStd = ConstantUtils.ispecsStd

ipolicyDts :: String
ipolicyDts = ConstantUtils.ipolicyDts

ipolicyVcpuRatio :: String
ipolicyVcpuRatio = ConstantUtils.ipolicyVcpuRatio

ipolicySpindleRatio :: String
ipolicySpindleRatio = ConstantUtils.ipolicySpindleRatio

ispecsMinmaxKeys :: FrozenSet String
ispecsMinmaxKeys = ConstantUtils.mkSet [ispecsMax, ispecsMin]

ipolicyParameters :: FrozenSet String
ipolicyParameters =
  ConstantUtils.mkSet [ConstantUtils.ipolicyVcpuRatio,
                       ConstantUtils.ipolicySpindleRatio]

ipolicyAllKeys :: FrozenSet String
ipolicyAllKeys =
  ConstantUtils.union ipolicyParameters $
  ConstantUtils.mkSet [ConstantUtils.ipolicyDts,
                       ConstantUtils.ispecsMinmax,
                       ispecsStd]

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

ndSshPort :: String
ndSshPort = "ssh_port"

ndCpuSpeed :: String
ndCpuSpeed = "cpu_speed"

ndsParameterTypes :: Map String VType
ndsParameterTypes =
  Map.fromList
  [(ndExclusiveStorage, VTypeBool),
   (ndOobProgram, VTypeString),
   (ndOvs, VTypeBool),
   (ndOvsLink, VTypeMaybeString),
   (ndOvsName, VTypeMaybeString),
   (ndSpindleCount, VTypeInt),
   (ndSshPort, VTypeInt),
   (ndCpuSpeed, VTypeFloat)]

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

-- * Logical Disks parameters

ldpAccess :: String
ldpAccess = "access"

ldpBarriers :: String
ldpBarriers = "disabled-barriers"

ldpDefaultMetavg :: String
ldpDefaultMetavg = "default-metavg"

ldpDelayTarget :: String
ldpDelayTarget = "c-delay-target"

ldpDiskCustom :: String
ldpDiskCustom = "disk-custom"

ldpDynamicResync :: String
ldpDynamicResync = "dynamic-resync"

ldpFillTarget :: String
ldpFillTarget = "c-fill-target"

ldpMaxRate :: String
ldpMaxRate = "c-max-rate"

ldpMinRate :: String
ldpMinRate = "c-min-rate"

ldpNetCustom :: String
ldpNetCustom = "net-custom"

ldpNoMetaFlush :: String
ldpNoMetaFlush = "disable-meta-flush"

ldpPlanAhead :: String
ldpPlanAhead = "c-plan-ahead"

ldpPool :: String
ldpPool = "pool"

ldpProtocol :: String
ldpProtocol = "protocol"

ldpResyncRate :: String
ldpResyncRate = "resync-rate"

ldpStripes :: String
ldpStripes = "stripes"

diskLdTypes :: Map String VType
diskLdTypes =
  Map.fromList
  [(ldpAccess, VTypeString),
   (ldpResyncRate, VTypeInt),
   (ldpStripes, VTypeInt),
   (ldpBarriers, VTypeString),
   (ldpNoMetaFlush, VTypeBool),
   (ldpDefaultMetavg, VTypeString),
   (ldpDiskCustom, VTypeString),
   (ldpNetCustom, VTypeString),
   (ldpProtocol, VTypeString),
   (ldpDynamicResync, VTypeBool),
   (ldpPlanAhead, VTypeInt),
   (ldpFillTarget, VTypeInt),
   (ldpDelayTarget, VTypeInt),
   (ldpMaxRate, VTypeInt),
   (ldpMinRate, VTypeInt),
   (ldpPool, VTypeString)]

diskLdParameters :: FrozenSet String
diskLdParameters = ConstantUtils.mkSet (Map.keys diskLdTypes)

-- * Disk template parameters
--
-- Disk template parameters can be set/changed by the user via
-- gnt-cluster and gnt-group)

drbdResyncRate :: String
drbdResyncRate = "resync-rate"

drbdDataStripes :: String
drbdDataStripes = "data-stripes"

drbdMetaStripes :: String
drbdMetaStripes = "meta-stripes"

drbdDiskBarriers :: String
drbdDiskBarriers = "disk-barriers"

drbdMetaBarriers :: String
drbdMetaBarriers = "meta-barriers"

drbdDefaultMetavg :: String
drbdDefaultMetavg = "metavg"

drbdDiskCustom :: String
drbdDiskCustom = "disk-custom"

drbdNetCustom :: String
drbdNetCustom = "net-custom"

drbdProtocol :: String
drbdProtocol = "protocol"

drbdDynamicResync :: String
drbdDynamicResync = "dynamic-resync"

drbdPlanAhead :: String
drbdPlanAhead = "c-plan-ahead"

drbdFillTarget :: String
drbdFillTarget = "c-fill-target"

drbdDelayTarget :: String
drbdDelayTarget = "c-delay-target"

drbdMaxRate :: String
drbdMaxRate = "c-max-rate"

drbdMinRate :: String
drbdMinRate = "c-min-rate"

lvStripes :: String
lvStripes = "stripes"

rbdAccess :: String
rbdAccess = "access"

rbdPool :: String
rbdPool = "pool"

diskDtTypes :: Map String VType
diskDtTypes =
  Map.fromList [(drbdResyncRate, VTypeInt),
                (drbdDataStripes, VTypeInt),
                (drbdMetaStripes, VTypeInt),
                (drbdDiskBarriers, VTypeString),
                (drbdMetaBarriers, VTypeBool),
                (drbdDefaultMetavg, VTypeString),
                (drbdDiskCustom, VTypeString),
                (drbdNetCustom, VTypeString),
                (drbdProtocol, VTypeString),
                (drbdDynamicResync, VTypeBool),
                (drbdPlanAhead, VTypeInt),
                (drbdFillTarget, VTypeInt),
                (drbdDelayTarget, VTypeInt),
                (drbdMaxRate, VTypeInt),
                (drbdMinRate, VTypeInt),
                (lvStripes, VTypeInt),
                (rbdAccess, VTypeString),
                (rbdPool, VTypeString),
                (glusterHost, VTypeString),
                (glusterVolume, VTypeString),
                (glusterPort, VTypeInt)
               ]

diskDtParameters :: FrozenSet String
diskDtParameters = ConstantUtils.mkSet (Map.keys diskDtTypes)

-- * Dynamic disk parameters

ddpLocalIp :: String
ddpLocalIp = "local-ip"

ddpRemoteIp :: String
ddpRemoteIp = "remote-ip"

ddpPort :: String
ddpPort = "port"

ddpLocalMinor :: String
ddpLocalMinor = "local-minor"

ddpRemoteMinor :: String
ddpRemoteMinor = "remote-minor"

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

-- | Instance Parameters Profile
ppDefault :: String
ppDefault = "default"

-- * nic* constants are used inside the ganeti config

nicLink :: String
nicLink = "link"

nicMode :: String
nicMode = "mode"

nicVlan :: String
nicVlan = "vlan"

nicsParameterTypes :: Map String VType
nicsParameterTypes =
  Map.fromList [(nicMode, vtypeString),
                (nicLink, vtypeString),
                (nicVlan, vtypeString)]

nicsParameters :: FrozenSet String
nicsParameters = ConstantUtils.mkSet (Map.keys nicsParameterTypes)

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

releaseAction :: String
releaseAction = "release"

reserveAction :: String
reserveAction = "reserve"

-- * idisk* constants are used in opcodes, to create/change disks

idiskAdopt :: String
idiskAdopt = "adopt"

idiskMetavg :: String
idiskMetavg = "metavg"

idiskMode :: String
idiskMode = "mode"

idiskName :: String
idiskName = "name"

idiskSize :: String
idiskSize = "size"

idiskSpindles :: String
idiskSpindles = "spindles"

idiskVg :: String
idiskVg = "vg"

idiskProvider :: String
idiskProvider = "provider"

idiskAccess :: String
idiskAccess = "access"

idiskType :: String
idiskType = "dev_type"

idiskParamsTypes :: Map String VType
idiskParamsTypes =
  Map.fromList [ (idiskSize, VTypeSize)
               , (idiskSpindles, VTypeInt)
               , (idiskMode, VTypeString)
               , (idiskAdopt, VTypeString)
               , (idiskVg, VTypeString)
               , (idiskMetavg, VTypeString)
               , (idiskProvider, VTypeString)
               , (idiskAccess, VTypeString)
               , (idiskName, VTypeMaybeString)
               , (idiskType, VTypeString)
               ]

idiskParams :: FrozenSet String
idiskParams = ConstantUtils.mkSet (Map.keys idiskParamsTypes)

modifiableIdiskParamsTypes :: Map String VType
modifiableIdiskParamsTypes =
  Map.fromList [(idiskMode, VTypeString),
                (idiskName, VTypeString)]

modifiableIdiskParams :: FrozenSet String
modifiableIdiskParams =
  ConstantUtils.mkSet (Map.keys modifiableIdiskParamsTypes)

-- * inic* constants are used in opcodes, to create/change nics

inicBridge :: String
inicBridge = "bridge"

inicIp :: String
inicIp = "ip"

inicLink :: String
inicLink = "link"

inicMac :: String
inicMac = "mac"

inicMode :: String
inicMode = "mode"

inicName :: String
inicName = "name"

inicNetwork :: String
inicNetwork = "network"

inicVlan :: String
inicVlan = "vlan"

inicParamsTypes :: Map String VType
inicParamsTypes =
  Map.fromList [(inicBridge, VTypeMaybeString),
                (inicIp, VTypeMaybeString),
                (inicLink, VTypeString),
                (inicMac, VTypeString),
                (inicMode, VTypeString),
                (inicName, VTypeMaybeString),
                (inicNetwork, VTypeMaybeString),
                (inicVlan, VTypeMaybeString)]

inicParams :: FrozenSet String
inicParams = ConstantUtils.mkSet (Map.keys inicParamsTypes)

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

vncBasePort :: Int
vncBasePort = 5900

vncDefaultBindAddress :: String
vncDefaultBindAddress = ip4AddressAny

qemuPciSlots :: Int
qemuPciSlots = 32

qemuDefaultPciReservations :: Int
qemuDefaultPciReservations = 12

-- * NIC types

htNicE1000 :: String
htNicE1000 = "e1000"

htNicI82551 :: String
htNicI82551 = "i82551"

htNicI8259er :: String
htNicI8259er = "i82559er"

htNicI85557b :: String
htNicI85557b = "i82557b"

htNicNe2kIsa :: String
htNicNe2kIsa = "ne2k_isa"

htNicNe2kPci :: String
htNicNe2kPci = "ne2k_pci"

htNicParavirtual :: String
htNicParavirtual = "paravirtual"

htNicPcnet :: String
htNicPcnet = "pcnet"

htNicRtl8139 :: String
htNicRtl8139 = "rtl8139"

htHvmValidNicTypes :: FrozenSet String
htHvmValidNicTypes =
  ConstantUtils.mkSet [htNicE1000,
                       htNicNe2kIsa,
                       htNicNe2kPci,
                       htNicParavirtual,
                       htNicRtl8139]

htKvmValidNicTypes :: FrozenSet String
htKvmValidNicTypes =
  ConstantUtils.mkSet [htNicE1000,
                       htNicI82551,
                       htNicI8259er,
                       htNicI85557b,
                       htNicNe2kIsa,
                       htNicNe2kPci,
                       htNicParavirtual,
                       htNicPcnet,
                       htNicRtl8139]

-- * Vif types

-- | Default vif type in xen-hvm
htHvmVifIoemu :: String
htHvmVifIoemu = "ioemu"

htHvmVifVif :: String
htHvmVifVif = "vif"

htHvmValidVifTypes :: FrozenSet String
htHvmValidVifTypes = ConstantUtils.mkSet [htHvmVifIoemu, htHvmVifVif]

-- * Disk types

htDiskIde :: String
htDiskIde = "ide"

htDiskIoemu :: String
htDiskIoemu = "ioemu"

htDiskMtd :: String
htDiskMtd = "mtd"

htDiskParavirtual :: String
htDiskParavirtual = "paravirtual"

htDiskPflash :: String
htDiskPflash = "pflash"

htDiskScsi :: String
htDiskScsi = "scsi"

htDiskSd :: String
htDiskSd = "sd"

htDiskScsiGeneric :: String
htDiskScsiGeneric = "scsi-generic"

htDiskScsiBlock :: String
htDiskScsiBlock = "scsi-block"

htDiskScsiCd :: String
htDiskScsiCd = "scsi-cd"

htDiskScsiHd :: String
htDiskScsiHd = "scsi-hd"

htScsiDeviceTypes :: FrozenSet String
htScsiDeviceTypes =
  ConstantUtils.mkSet [htDiskScsiGeneric,
                       htDiskScsiBlock,
                       htDiskScsiCd,
                       htDiskScsiHd]

htHvmValidDiskTypes :: FrozenSet String
htHvmValidDiskTypes = ConstantUtils.mkSet [htDiskIoemu, htDiskParavirtual]

htKvmValidDiskTypes :: FrozenSet String
htKvmValidDiskTypes =
  ConstantUtils.mkSet [htDiskIde,
                       htDiskMtd,
                       htDiskParavirtual,
                       htDiskPflash,
                       htDiskScsi,
                       htDiskSd,
                       htDiskScsiGeneric,
                       htDiskScsiBlock,
                       htDiskScsiHd,
                       htDiskScsiCd]

-- * SCSI controller types

htScsiControllerLsi :: String
htScsiControllerLsi = "lsi"

htScsiControllerVirtio :: String
htScsiControllerVirtio = "virtio-scsi-pci"

htScsiControllerMegasas :: String
htScsiControllerMegasas = "megasas"

htKvmValidScsiControllerTypes :: FrozenSet String
htKvmValidScsiControllerTypes =
  ConstantUtils.mkSet [htScsiControllerLsi,
                       htScsiControllerVirtio,
                       htScsiControllerMegasas]

htCacheDefault :: String
htCacheDefault = "default"

htCacheNone :: String
htCacheNone = "none"

htCacheWback :: String
htCacheWback = "writeback"

htCacheWthrough :: String
htCacheWthrough = "writethrough"

htValidCacheTypes :: FrozenSet String
htValidCacheTypes =
  ConstantUtils.mkSet [htCacheDefault,
                       htCacheNone,
                       htCacheWback,
                       htCacheWthrough]

htDiscardDefault :: String
htDiscardDefault = "default"

htDiscardIgnore :: String
htDiscardIgnore = "ignore"

htDiscardUnmap :: String
htDiscardUnmap = "unmap"

htValidDiscardTypes :: FrozenSet String
htValidDiscardTypes =
  ConstantUtils.mkSet [htDiscardDefault,
                       htDiscardIgnore,
                       htDiscardUnmap]

htKvmAioThreads :: String
htKvmAioThreads = "threads"

htKvmAioNative :: String
htKvmAioNative = "native"

htKvmValidAioTypes :: FrozenSet String
htKvmValidAioTypes =
  ConstantUtils.mkSet [htKvmAioThreads,
                       htKvmAioNative]

-- * Mouse types

htMouseMouse :: String
htMouseMouse = "mouse"

htMouseTablet :: String
htMouseTablet = "tablet"

htKvmValidMouseTypes :: FrozenSet String
htKvmValidMouseTypes = ConstantUtils.mkSet [htMouseMouse, htMouseTablet]

-- * Boot order

htBoCdrom :: String
htBoCdrom = "cdrom"

htBoDisk :: String
htBoDisk = "disk"

htBoFloppy :: String
htBoFloppy = "floppy"

htBoNetwork :: String
htBoNetwork = "network"

htKvmValidBoTypes :: FrozenSet String
htKvmValidBoTypes =
  ConstantUtils.mkSet [htBoCdrom, htBoDisk, htBoFloppy, htBoNetwork]

-- * SPICE lossless image compression options

htKvmSpiceLosslessImgComprAutoGlz :: String
htKvmSpiceLosslessImgComprAutoGlz = "auto_glz"

htKvmSpiceLosslessImgComprAutoLz :: String
htKvmSpiceLosslessImgComprAutoLz = "auto_lz"

htKvmSpiceLosslessImgComprGlz :: String
htKvmSpiceLosslessImgComprGlz = "glz"

htKvmSpiceLosslessImgComprLz :: String
htKvmSpiceLosslessImgComprLz = "lz"

htKvmSpiceLosslessImgComprOff :: String
htKvmSpiceLosslessImgComprOff = "off"

htKvmSpiceLosslessImgComprQuic :: String
htKvmSpiceLosslessImgComprQuic = "quic"

htKvmSpiceValidLosslessImgComprOptions :: FrozenSet String
htKvmSpiceValidLosslessImgComprOptions =
  ConstantUtils.mkSet [htKvmSpiceLosslessImgComprAutoGlz,
                       htKvmSpiceLosslessImgComprAutoLz,
                       htKvmSpiceLosslessImgComprGlz,
                       htKvmSpiceLosslessImgComprLz,
                       htKvmSpiceLosslessImgComprOff,
                       htKvmSpiceLosslessImgComprQuic]

htKvmSpiceLossyImgComprAlways :: String
htKvmSpiceLossyImgComprAlways = "always"

htKvmSpiceLossyImgComprAuto :: String
htKvmSpiceLossyImgComprAuto = "auto"

htKvmSpiceLossyImgComprNever :: String
htKvmSpiceLossyImgComprNever = "never"

htKvmSpiceValidLossyImgComprOptions :: FrozenSet String
htKvmSpiceValidLossyImgComprOptions =
  ConstantUtils.mkSet [htKvmSpiceLossyImgComprAlways,
                       htKvmSpiceLossyImgComprAuto,
                       htKvmSpiceLossyImgComprNever]

-- * SPICE video stream detection

htKvmSpiceVideoStreamDetectionAll :: String
htKvmSpiceVideoStreamDetectionAll = "all"

htKvmSpiceVideoStreamDetectionFilter :: String
htKvmSpiceVideoStreamDetectionFilter = "filter"

htKvmSpiceVideoStreamDetectionOff :: String
htKvmSpiceVideoStreamDetectionOff = "off"

htKvmSpiceValidVideoStreamDetectionOptions :: FrozenSet String
htKvmSpiceValidVideoStreamDetectionOptions =
  ConstantUtils.mkSet [htKvmSpiceVideoStreamDetectionAll,
                       htKvmSpiceVideoStreamDetectionFilter,
                       htKvmSpiceVideoStreamDetectionOff]

-- * Security models

htSmNone :: String
htSmNone = "none"

htSmPool :: String
htSmPool = "pool"

htSmUser :: String
htSmUser = "user"

htKvmValidSmTypes :: FrozenSet String
htKvmValidSmTypes = ConstantUtils.mkSet [htSmNone, htSmPool, htSmUser]

-- * Kvm flag values

htKvmDisabled :: String
htKvmDisabled = "disabled"

htKvmEnabled :: String
htKvmEnabled = "enabled"

htKvmFlagValues :: FrozenSet String
htKvmFlagValues = ConstantUtils.mkSet [htKvmDisabled, htKvmEnabled]

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

-- * Cluster Verify error levels

cvWarning :: String
cvWarning = "WARNING"

cvError :: String
cvError = "ERROR"

-- * Cluster Verify error codes and documentation

cvEclustercert :: (String, String, String)
cvEclustercert =
  ("cluster",
   Types.cVErrorCodeToRaw CvECLUSTERCERT,
   "Cluster certificate files verification failure")

cvEclusterclientcert :: (String, String, String)
cvEclusterclientcert =
  ("cluster",
   Types.cVErrorCodeToRaw CvECLUSTERCLIENTCERT,
   "Cluster client certificate files verification failure")

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

cvEextags :: (String, String, String)
cvEextags =
  ("node",
   Types.cVErrorCodeToRaw CvEEXTAGS,
   "Instances with same exclusion tag on the same node")

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

cvEnodeglusterstoragepathunusable :: (String, String, String)
cvEnodeglusterstoragepathunusable =
  ("node",
   Types.cVErrorCodeToRaw CvENODEGLUSTERSTORAGEPATHUNUSABLE,
   "Gluster storage path unusable")

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
   cvEnodeglusterstoragepathunusable,
   cvEnodessh,
   cvEnodetime,
   cvEnodeuserscripts,
   cvEnodeversion]

cvAllEcodesStrings :: FrozenSet String
cvAllEcodesStrings =
  ConstantUtils.mkSet $ map Types.cVErrorCodeToRaw [minBound..]

-- * Node verify constants

nvBridges :: String
nvBridges = "bridges"

nvClientCert :: String
nvClientCert = "client-cert"

nvDrbdhelper :: String
nvDrbdhelper = "drbd-helper"

nvDrbdversion :: String
nvDrbdversion = "drbd-version"

nvDrbdlist :: String
nvDrbdlist = "drbd-list"

nvExclusivepvs :: String
nvExclusivepvs = "exclusive-pvs"

nvFilelist :: String
nvFilelist = "filelist"

nvAcceptedStoragePaths :: String
nvAcceptedStoragePaths = "allowed-file-storage-paths"

nvFileStoragePath :: String
nvFileStoragePath = "file-storage-path"

nvSharedFileStoragePath :: String
nvSharedFileStoragePath = "shared-file-storage-path"

nvGlusterStoragePath :: String
nvGlusterStoragePath = "gluster-storage-path"

nvHvinfo :: String
nvHvinfo = "hvinfo"

nvHvparams :: String
nvHvparams = "hvparms"

nvHypervisor :: String
nvHypervisor = "hypervisor"

nvInstancelist :: String
nvInstancelist = "instancelist"

nvLvlist :: String
nvLvlist = "lvlist"

nvMasterip :: String
nvMasterip = "master-ip"

nvNodelist :: String
nvNodelist = "nodelist"

nvNodenettest :: String
nvNodenettest = "node-net-test"

nvNodesetup :: String
nvNodesetup = "nodesetup"

nvOobPaths :: String
nvOobPaths = "oob-paths"

nvOslist :: String
nvOslist = "oslist"

nvPvlist :: String
nvPvlist = "pvlist"

nvTime :: String
nvTime = "time"

nvUserscripts :: String
nvUserscripts = "user-scripts"

nvVersion :: String
nvVersion = "version"

nvVglist :: String
nvVglist = "vglist"

nvNonvmnodes :: String
nvNonvmnodes = "nonvmnodes"

nvSshSetup :: String
nvSshSetup = "ssh-setup"

nvSshClutter :: String
nvSshClutter = "ssh-clutter"

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

inststUserdown :: String
inststUserdown = Types.instanceStatusToRaw UserDown

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

-- * Admin state sources

adminSource :: AdminStateSource
adminSource = AdminSource

userSource :: AdminStateSource
userSource = UserSource

adminStateSources :: FrozenSet AdminStateSource
adminStateSources = ConstantUtils.mkSet [minBound..]

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

-- * SSL certificate check constants (in days)

sslCertExpirationError :: Int
sslCertExpirationError = 7

sslCertExpirationWarn :: Int
sslCertExpirationWarn = 30

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

iallocatorModeAllocateSecondary :: String
iallocatorModeAllocateSecondary =
  Types.iAllocatorModeToRaw IAllocatorAllocateSecondary

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

-- * Opportunistic allocator usage

-- | Time delay in seconds between repeated opportunistic instance creations.
-- Rather than failing with an informative error message if the opportunistic
-- creation cannot grab enough nodes, for some uses it is better to retry the
-- creation with an interval between attempts. This is a reasonable default.
defaultOpportunisticRetryInterval :: Int
defaultOpportunisticRetryInterval = 30

-- * Node evacuation

nodeEvacPri :: String
nodeEvacPri = Types.evacModeToRaw ChangePrimary

nodeEvacSec :: String
nodeEvacSec = Types.evacModeToRaw ChangeSecondary

nodeEvacAll :: String
nodeEvacAll = Types.evacModeToRaw ChangeAll

nodeEvacModes :: FrozenSet String
nodeEvacModes = ConstantUtils.mkSet $ map Types.evacModeToRaw [minBound..]

-- * Job queue

jobQueueVersion :: Int
jobQueueVersion = 1

jobQueueSizeHardLimit :: Int
jobQueueSizeHardLimit = 5000

jobQueueFilesPerms :: Int
jobQueueFilesPerms = 0o640

-- * Unchanged job return

jobNotchanged :: String
jobNotchanged = "nochange"

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

-- * Lock recalculate mode

locksAppend :: String
locksAppend = "append"

locksReplace :: String
locksReplace = "replace"

-- * Lock timeout
--
-- The lock timeout (sum) before we transition into blocking acquire
-- (this can still be reset by priority change).  Computed as max time
-- (10 hours) before we should actually go into blocking acquire,
-- given that we start from the default priority level.

lockAttemptsMaxwait :: Double
lockAttemptsMaxwait = 75.0

lockAttemptsMinwait :: Double
lockAttemptsMinwait = 5.0

lockAttemptsTimeout :: Int
lockAttemptsTimeout = (10 * 3600) `div` (opPrioDefault - opPrioHighest)

-- * Execution log types
elogMessage :: String
elogMessage = Types.eLogTypeToRaw ELogMessage

-- ELogMessageList is internal to Python code only, used to distinguish
-- calling conventions in Feedback(), but is never serialized or loaded
-- in Luxi.
elogMessageList :: String
elogMessageList = Types.eLogTypeToRaw ELogMessageList

elogRemoteImport :: String
elogRemoteImport = Types.eLogTypeToRaw ELogRemoteImport

elogJqueueTest :: String
elogJqueueTest = Types.eLogTypeToRaw ELogJqueueTest

elogDelayTest :: String
elogDelayTest = Types.eLogTypeToRaw ELogDelayTest

-- * /etc/hosts modification

etcHostsAdd :: String
etcHostsAdd = "add"

etcHostsRemove :: String
etcHostsRemove = "remove"

-- * Job queue test

jqtMsgprefix :: String
jqtMsgprefix = "TESTMSG="

jqtExec :: String
jqtExec = "exec"

jqtExpandnames :: String
jqtExpandnames = "expandnames"

jqtLogmsg :: String
jqtLogmsg = "logmsg"

jqtStartmsg :: String
jqtStartmsg = "startmsg"

jqtAll :: FrozenSet String
jqtAll = ConstantUtils.mkSet [jqtExec, jqtExpandnames, jqtLogmsg, jqtStartmsg]

-- * Query resources

qrCluster :: String
qrCluster = "cluster"

qrExport :: String
qrExport = "export"

qrExtstorage :: String
qrExtstorage = "extstorage"

qrGroup :: String
qrGroup = "group"

qrInstance :: String
qrInstance = "instance"

qrJob :: String
qrJob = "job"

qrLock :: String
qrLock = "lock"

qrNetwork :: String
qrNetwork = "network"

qrFilter :: String
qrFilter = "filter"

qrNode :: String
qrNode = "node"

qrOs :: String
qrOs = "os"

-- | List of resources which can be queried using 'Ganeti.OpCodes.OpQuery'
qrViaOp :: FrozenSet String
qrViaOp =
  ConstantUtils.mkSet [qrCluster,
                       qrOs,
                       qrExtstorage]

-- | List of resources which can be queried using Local UniX Interface
qrViaLuxi :: FrozenSet String
qrViaLuxi = ConstantUtils.mkSet [qrGroup,
                                 qrExport,
                                 qrInstance,
                                 qrJob,
                                 qrLock,
                                 qrNetwork,
                                 qrNode,
                                 qrFilter]

-- | List of resources which can be queried using RAPI
qrViaRapi :: FrozenSet String
qrViaRapi = qrViaLuxi

-- | List of resources which can be queried via RAPI including PUT requests
qrViaRapiPut :: FrozenSet String
qrViaRapiPut = ConstantUtils.mkSet [qrLock, qrJob, qrFilter]

-- * Query field types

qftBool :: String
qftBool = "bool"

qftNumber :: String
qftNumber = "number"

qftNumberFloat :: String
qftNumberFloat = "float"

qftOther :: String
qftOther = "other"

qftText :: String
qftText = "text"

qftTimestamp :: String
qftTimestamp = "timestamp"

qftUnit :: String
qftUnit = "unit"

qftUnknown :: String
qftUnknown = "unknown"

qftAll :: FrozenSet String
qftAll =
  ConstantUtils.mkSet [qftBool,
                       qftNumber,
                       qftNumberFloat,
                       qftOther,
                       qftText,
                       qftTimestamp,
                       qftUnit,
                       qftUnknown]

-- * Query result field status
--
-- Don't change or reuse values as they're used by clients.
--
-- FIXME: link with 'Ganeti.Query.Language.ResultStatus'

-- | No data (e.g. RPC error), can be used instead of 'rsOffline'
rsNodata :: Int
rsNodata = 2

rsNormal :: Int
rsNormal = 0

-- | Resource marked offline
rsOffline :: Int
rsOffline = 4

-- | Value unavailable/unsupported for item; if this field is
-- supported but we cannot get the data for the moment, 'rsNodata' or
-- 'rsOffline' should be used
rsUnavail :: Int
rsUnavail = 3

rsUnknown :: Int
rsUnknown = 1

rsAll :: FrozenSet Int
rsAll =
  ConstantUtils.mkSet [rsNodata,
                       rsNormal,
                       rsOffline,
                       rsUnavail,
                       rsUnknown]

-- | Special field cases and their verbose/terse formatting
rssDescription :: Map Int (String, String)
rssDescription =
  Map.fromList [(rsUnknown, ("(unknown)", "??")),
                (rsNodata, ("(nodata)", "?")),
                (rsOffline, ("(offline)", "*")),
                (rsUnavail, ("(unavail)", "-"))]

-- * Max dynamic devices

maxDisks :: Int
maxDisks = Types.maxDisks

maxNics :: Int
maxNics = Types.maxNics

-- | SSCONF file prefix
ssconfFileprefix :: String
ssconfFileprefix = "ssconf_"

-- * SSCONF keys

ssClusterName :: String
ssClusterName = "cluster_name"

ssClusterTags :: String
ssClusterTags = "cluster_tags"

ssFileStorageDir :: String
ssFileStorageDir = "file_storage_dir"

ssSharedFileStorageDir :: String
ssSharedFileStorageDir = "shared_file_storage_dir"

ssGlusterStorageDir :: String
ssGlusterStorageDir = "gluster_storage_dir"

ssMasterCandidates :: String
ssMasterCandidates = "master_candidates"

ssMasterCandidatesIps :: String
ssMasterCandidatesIps = "master_candidates_ips"

ssMasterCandidatesCerts :: String
ssMasterCandidatesCerts = "master_candidates_certs"

ssMasterIp :: String
ssMasterIp = "master_ip"

ssMasterNetdev :: String
ssMasterNetdev = "master_netdev"

ssMasterNetmask :: String
ssMasterNetmask = "master_netmask"

ssMasterNode :: String
ssMasterNode = "master_node"

ssNodeList :: String
ssNodeList = "node_list"

ssNodePrimaryIps :: String
ssNodePrimaryIps = "node_primary_ips"

ssNodeSecondaryIps :: String
ssNodeSecondaryIps = "node_secondary_ips"

ssNodeVmCapable :: String
ssNodeVmCapable = "node_vm_capable"

ssOfflineNodes :: String
ssOfflineNodes = "offline_nodes"

ssOnlineNodes :: String
ssOnlineNodes = "online_nodes"

ssPrimaryIpFamily :: String
ssPrimaryIpFamily = "primary_ip_family"

ssInstanceList :: String
ssInstanceList = "instance_list"

ssReleaseVersion :: String
ssReleaseVersion = "release_version"

ssHypervisorList :: String
ssHypervisorList = "hypervisor_list"

ssMaintainNodeHealth :: String
ssMaintainNodeHealth = "maintain_node_health"

ssUidPool :: String
ssUidPool = "uid_pool"

ssNodegroups :: String
ssNodegroups = "nodegroups"

ssNetworks :: String
ssNetworks = "networks"

-- | This is not a complete SSCONF key, but the prefix for the
-- hypervisor keys
ssHvparamsPref :: String
ssHvparamsPref = "hvparams_"

-- * Hvparams keys

ssHvparamsXenChroot :: String
ssHvparamsXenChroot = ssHvparamsPref ++ htChroot

ssHvparamsXenFake :: String
ssHvparamsXenFake = ssHvparamsPref ++ htFake

ssHvparamsXenHvm :: String
ssHvparamsXenHvm = ssHvparamsPref ++ htXenHvm

ssHvparamsXenKvm :: String
ssHvparamsXenKvm = ssHvparamsPref ++ htKvm

ssHvparamsXenLxc :: String
ssHvparamsXenLxc = ssHvparamsPref ++ htLxc

ssHvparamsXenPvm :: String
ssHvparamsXenPvm = ssHvparamsPref ++ htXenPvm

validSsHvparamsKeys :: FrozenSet String
validSsHvparamsKeys =
  ConstantUtils.mkSet [ssHvparamsXenChroot,
                       ssHvparamsXenLxc,
                       ssHvparamsXenFake,
                       ssHvparamsXenHvm,
                       ssHvparamsXenKvm,
                       ssHvparamsXenPvm]

ssFilePerms :: Int
ssFilePerms = 0o444

ssEnabledUserShutdown :: String
ssEnabledUserShutdown = "enabled_user_shutdown"

ssSshPorts :: String
ssSshPorts = "ssh_ports"

validSsKeys :: FrozenSet String
validSsKeys = ConstantUtils.mkSet
  [ ssClusterName
  , ssClusterTags
  , ssFileStorageDir
  , ssSharedFileStorageDir
  , ssGlusterStorageDir
  , ssMasterCandidates
  , ssMasterCandidatesIps
  , ssMasterCandidatesCerts
  , ssMasterIp
  , ssMasterNetdev
  , ssMasterNetmask
  , ssMasterNode
  , ssNodeList
  , ssNodePrimaryIps
  , ssNodeSecondaryIps
  , ssNodeVmCapable
  , ssOfflineNodes
  , ssOnlineNodes
  , ssPrimaryIpFamily
  , ssInstanceList
  , ssReleaseVersion
  , ssHypervisorList
  , ssMaintainNodeHealth
  , ssUidPool
  , ssNodegroups
  , ssNetworks
  , ssEnabledUserShutdown
  , ssSshPorts
  ]
  <>
  validSsHvparamsKeys


-- | Cluster wide default parameters
defaultEnabledHypervisor :: String
defaultEnabledHypervisor = htXenPvm

hvcDefaults :: Map Hypervisor (Map String PyValueEx)
hvcDefaults =
  Map.fromList
  [ (XenPvm, Map.fromList
             [ (hvUseBootloader,  PyValueEx False)
             , (hvBootloaderPath, PyValueEx xenBootloader)
             , (hvBootloaderArgs, PyValueEx "")
             , (hvKernelPath,     PyValueEx xenKernel)
             , (hvInitrdPath,     PyValueEx "")
             , (hvRootPath,       PyValueEx "/dev/xvda1")
             , (hvKernelArgs,     PyValueEx "ro")
             , (hvMigrationPort,  PyValueEx (8002 :: Int))
             , (hvMigrationMode,  PyValueEx htMigrationLive)
             , (hvBlockdevPrefix, PyValueEx "sd")
             , (hvRebootBehavior, PyValueEx instanceRebootAllowed)
             , (hvCpuMask,        PyValueEx cpuPinningAll)
             , (hvCpuCap,         PyValueEx (0 :: Int))
             , (hvCpuWeight,      PyValueEx (256 :: Int))
             , (hvVifScript,      PyValueEx "")
             , (hvXenCmd,         PyValueEx xenCmdXm)
             , (hvXenCpuid,       PyValueEx "")
             , (hvSoundhw,        PyValueEx "")
             ])
  , (XenHvm, Map.fromList
             [ (hvBootOrder,      PyValueEx "cd")
             , (hvCdromImagePath, PyValueEx "")
             , (hvNicType,        PyValueEx htNicRtl8139)
             , (hvDiskType,       PyValueEx htDiskParavirtual)
             , (hvVncBindAddress, PyValueEx ip4AddressAny)
             , (hvAcpi,           PyValueEx True)
             , (hvPae,            PyValueEx True)
             , (hvKernelPath,     PyValueEx "/usr/lib/xen/boot/hvmloader")
             , (hvDeviceModel,    PyValueEx "/usr/lib/xen/bin/qemu-dm")
             , (hvMigrationPort,  PyValueEx (8002 :: Int))
             , (hvMigrationMode,  PyValueEx htMigrationNonlive)
             , (hvUseLocaltime,   PyValueEx False)
             , (hvBlockdevPrefix, PyValueEx "hd")
             , (hvPassthrough,    PyValueEx "")
             , (hvRebootBehavior, PyValueEx instanceRebootAllowed)
             , (hvCpuMask,        PyValueEx cpuPinningAll)
             , (hvCpuCap,         PyValueEx (0 :: Int))
             , (hvCpuWeight,      PyValueEx (256 :: Int))
             , (hvVifType,        PyValueEx htHvmVifIoemu)
             , (hvVifScript,      PyValueEx "")
             , (hvViridian,       PyValueEx False)
             , (hvXenCmd,         PyValueEx xenCmdXm)
             , (hvXenCpuid,       PyValueEx "")
             , (hvSoundhw,        PyValueEx "")
             ])
  , (Kvm, Map.fromList
          [ (hvKvmPath,                         PyValueEx kvmPath)
          , (hvKernelPath,                      PyValueEx kvmKernel)
          , (hvInitrdPath,                      PyValueEx "")
          , (hvKernelArgs,                      PyValueEx "ro")
          , (hvRootPath,                        PyValueEx "/dev/vda1")
          , (hvAcpi,                            PyValueEx True)
          , (hvSerialConsole,                   PyValueEx True)
          , (hvSerialSpeed,                     PyValueEx (38400 :: Int))
          , (hvVncBindAddress,                  PyValueEx "")
          , (hvVncTls,                          PyValueEx False)
          , (hvVncX509,                         PyValueEx "")
          , (hvVncX509Verify,                   PyValueEx False)
          , (hvVncPasswordFile,                 PyValueEx "")
          , (hvKvmScsiControllerType,           PyValueEx htScsiControllerLsi)
          , (hvKvmPciReservations,         PyValueEx qemuDefaultPciReservations)
          , (hvKvmSpiceBind,                    PyValueEx "")
          , (hvKvmSpiceIpVersion,           PyValueEx ifaceNoIpVersionSpecified)
          , (hvKvmSpicePasswordFile,            PyValueEx "")
          , (hvKvmSpiceLosslessImgCompr,        PyValueEx "")
          , (hvKvmSpiceJpegImgCompr,            PyValueEx "")
          , (hvKvmSpiceZlibGlzImgCompr,         PyValueEx "")
          , (hvKvmSpiceStreamingVideoDetection, PyValueEx "")
          , (hvKvmSpiceAudioCompr,              PyValueEx True)
          , (hvKvmSpiceUseTls,                  PyValueEx False)
          , (hvKvmSpiceTlsCiphers,              PyValueEx opensslCiphers)
          , (hvKvmSpiceUseVdagent,              PyValueEx True)
          , (hvKvmFloppyImagePath,              PyValueEx "")
          , (hvCdromImagePath,                  PyValueEx "")
          , (hvKvmCdrom2ImagePath,              PyValueEx "")
          , (hvBootOrder,                       PyValueEx htBoDisk)
          , (hvNicType,                         PyValueEx htNicParavirtual)
          , (hvDiskType,                        PyValueEx htDiskParavirtual)
          , (hvKvmCdromDiskType,                PyValueEx "")
          , (hvKvmDiskAio,                      PyValueEx htKvmAioThreads)
          , (hvUsbMouse,                        PyValueEx "")
          , (hvKeymap,                          PyValueEx "")
          , (hvMigrationPort,                   PyValueEx (8102 :: Int))
          , (hvMigrationBandwidth,              PyValueEx (32 :: Int))
          , (hvMigrationDowntime,               PyValueEx (30 :: Int))
          , (hvMigrationMode,                   PyValueEx htMigrationLive)
          , (hvUseGuestAgent,                   PyValueEx False)
          , (hvUseLocaltime,                    PyValueEx False)
          , (hvDiskCache,                       PyValueEx htCacheDefault)
          , (hvDiskDiscard,                     PyValueEx htDiscardDefault)
          , (hvSecurityModel,                   PyValueEx htSmNone)
          , (hvSecurityDomain,                  PyValueEx "")
          , (hvKvmFlag,                         PyValueEx "")
          , (hvVhostNet,                        PyValueEx False)
          , (hvVirtioNetQueues,                 PyValueEx (1 :: Int))
          , (hvKvmUseChroot,                    PyValueEx False)
          , (hvKvmUserShutdown,                 PyValueEx False)
          , (hvMemPath,                         PyValueEx "")
          , (hvRebootBehavior,                  PyValueEx instanceRebootAllowed)
          , (hvCpuMask,                         PyValueEx cpuPinningAll)
          , (hvCpuType,                         PyValueEx "")
          , (hvCpuCores,                        PyValueEx (0 :: Int))
          , (hvCpuThreads,                      PyValueEx (0 :: Int))
          , (hvCpuSockets,                      PyValueEx (0 :: Int))
          , (hvSoundhw,                         PyValueEx "")
          , (hvUsbDevices,                      PyValueEx "")
          , (hvVga,                             PyValueEx "")
          , (hvKvmExtra,                        PyValueEx "")
          , (hvKvmMachineVersion,               PyValueEx "")
          , (hvKvmMigrationCaps,                PyValueEx "")
          , (hvVnetHdr,                         PyValueEx True)])
  , (Fake, Map.fromList [(hvMigrationMode, PyValueEx htMigrationLive)])
  , (Chroot, Map.fromList [(hvInitScript, PyValueEx "/ganeti-chroot")])
  , (Lxc, Map.fromList
          [ (hvCpuMask,             PyValueEx "")
          , (hvLxcDevices,          PyValueEx lxcDevicesDefault)
          , (hvLxcDropCapabilities, PyValueEx lxcDropCapabilitiesDefault)
          , (hvLxcExtraCgroups,     PyValueEx "")
          , (hvLxcExtraConfig,      PyValueEx "")
          , (hvLxcNumTtys,          PyValueEx (6 :: Int))
          , (hvLxcStartupTimeout,   PyValueEx (30 :: Int))
          ])
  ]

hvcGlobals :: FrozenSet String
hvcGlobals =
  ConstantUtils.mkSet [hvMigrationBandwidth,
                       hvMigrationMode,
                       hvMigrationPort,
                       hvXenCmd]

becDefaults :: Map String PyValueEx
becDefaults =
  Map.fromList
  [ (beMinmem, PyValueEx (128 :: Int))
  , (beMaxmem, PyValueEx (128 :: Int))
  , (beVcpus, PyValueEx (1 :: Int))
  , (beAutoBalance, PyValueEx True)
  , (beAlwaysFailover, PyValueEx False)
  , (beSpindleUse, PyValueEx (1 :: Int))
  ]

ndcDefaults :: Map String PyValueEx
ndcDefaults =
  Map.fromList
  [ (ndOobProgram,       PyValueEx "")
  , (ndSpindleCount,     PyValueEx (1 :: Int))
  , (ndExclusiveStorage, PyValueEx False)
  , (ndOvs,              PyValueEx False)
  , (ndOvsName,          PyValueEx defaultOvs)
  , (ndOvsLink,          PyValueEx "")
  , (ndSshPort,          PyValueEx (22 :: Int))
  , (ndCpuSpeed,         PyValueEx (1 :: Double))
  ]

ndcGlobals :: FrozenSet String
ndcGlobals = ConstantUtils.mkSet [ndExclusiveStorage]

-- | Default delay target measured in sectors
defaultDelayTarget :: Int
defaultDelayTarget = 1

defaultDiskCustom :: String
defaultDiskCustom = ""

defaultDiskResync :: Bool
defaultDiskResync = False

-- | Default fill target measured in sectors
defaultFillTarget :: Int
defaultFillTarget = 0

-- | Default mininum rate measured in KiB/s
defaultMinRate :: Int
defaultMinRate = 4 * 1024

defaultNetCustom :: String
defaultNetCustom = ""

-- | Default plan ahead measured in sectors
--
-- The default values for the DRBD dynamic resync speed algorithm are
-- taken from the drbsetup 8.3.11 man page, except for c-plan-ahead
-- (that we don't need to set to 0, because we have a separate option
-- to enable it) and for c-max-rate, that we cap to the default value
-- for the static resync rate.
defaultPlanAhead :: Int
defaultPlanAhead = 20

defaultRbdPool :: String
defaultRbdPool = "rbd"

diskLdDefaults :: Map DiskTemplate (Map String PyValueEx)
diskLdDefaults =
  Map.fromList
  [ (DTBlock, Map.empty)
  , (DTDrbd8, Map.fromList
              [ (ldpBarriers,      PyValueEx drbdBarriers)
              , (ldpDefaultMetavg, PyValueEx defaultVg)
              , (ldpDelayTarget,   PyValueEx defaultDelayTarget)
              , (ldpDiskCustom,    PyValueEx defaultDiskCustom)
              , (ldpDynamicResync, PyValueEx defaultDiskResync)
              , (ldpFillTarget,    PyValueEx defaultFillTarget)
              , (ldpMaxRate,       PyValueEx classicDrbdSyncSpeed)
              , (ldpMinRate,       PyValueEx defaultMinRate)
              , (ldpNetCustom,     PyValueEx defaultNetCustom)
              , (ldpNoMetaFlush,   PyValueEx drbdNoMetaFlush)
              , (ldpPlanAhead,     PyValueEx defaultPlanAhead)
              , (ldpProtocol,      PyValueEx drbdDefaultNetProtocol)
              , (ldpResyncRate,    PyValueEx classicDrbdSyncSpeed)
              ])
  , (DTExt, Map.fromList
            [ (ldpAccess, PyValueEx diskKernelspace)
            ])
  , (DTFile, Map.empty)
  , (DTPlain, Map.fromList [(ldpStripes, PyValueEx lvmStripecount)])
  , (DTRbd, Map.fromList
            [ (ldpPool, PyValueEx defaultRbdPool)
            , (ldpAccess, PyValueEx diskKernelspace)
            ])
  , (DTSharedFile, Map.empty)
  , (DTGluster, Map.fromList
                [ (rbdAccess, PyValueEx diskKernelspace)
                , (glusterHost, PyValueEx glusterHostDefault)
                , (glusterVolume, PyValueEx glusterVolumeDefault)
                , (glusterPort, PyValueEx glusterPortDefault)
                ])
  ]

diskDtDefaults :: Map DiskTemplate (Map String PyValueEx)
diskDtDefaults =
  Map.fromList
  [ (DTBlock,      Map.empty)
  , (DTDiskless,   Map.empty)
  , (DTDrbd8,      Map.fromList
                   [ (drbdDataStripes,   PyValueEx lvmStripecount)
                   , (drbdDefaultMetavg, PyValueEx defaultVg)
                   , (drbdDelayTarget,   PyValueEx defaultDelayTarget)
                   , (drbdDiskBarriers,  PyValueEx drbdBarriers)
                   , (drbdDiskCustom,    PyValueEx defaultDiskCustom)
                   , (drbdDynamicResync, PyValueEx defaultDiskResync)
                   , (drbdFillTarget,    PyValueEx defaultFillTarget)
                   , (drbdMaxRate,       PyValueEx classicDrbdSyncSpeed)
                   , (drbdMetaBarriers,  PyValueEx drbdNoMetaFlush)
                   , (drbdMetaStripes,   PyValueEx lvmStripecount)
                   , (drbdMinRate,       PyValueEx defaultMinRate)
                   , (drbdNetCustom,     PyValueEx defaultNetCustom)
                   , (drbdPlanAhead,     PyValueEx defaultPlanAhead)
                   , (drbdProtocol,      PyValueEx drbdDefaultNetProtocol)
                   , (drbdResyncRate,    PyValueEx classicDrbdSyncSpeed)
                   ])
  , (DTExt,        Map.fromList
                   [ (rbdAccess, PyValueEx diskKernelspace)
                   ])
  , (DTFile,       Map.empty)
  , (DTPlain,      Map.fromList [(lvStripes, PyValueEx lvmStripecount)])
  , (DTRbd,        Map.fromList
                   [ (rbdPool, PyValueEx defaultRbdPool)
                   , (rbdAccess, PyValueEx diskKernelspace)
                   ])
  , (DTSharedFile, Map.empty)
  , (DTGluster, Map.fromList
                [ (rbdAccess, PyValueEx diskKernelspace)
                , (glusterHost, PyValueEx glusterHostDefault)
                , (glusterVolume, PyValueEx glusterVolumeDefault)
                , (glusterPort, PyValueEx glusterPortDefault)
                ])
  ]

niccDefaults :: Map String PyValueEx
niccDefaults =
  Map.fromList
  [ (nicMode, PyValueEx nicModeBridged)
  , (nicLink, PyValueEx defaultBridge)
  , (nicVlan, PyValueEx "")
  ]

-- | All of the following values are quite arbitrary - there are no
-- "good" defaults, these must be customised per-site
ispecsMinmaxDefaults :: Map String (Map String Int)
ispecsMinmaxDefaults =
  Map.fromList
  [(ispecsMin,
    Map.fromList
    [(ConstantUtils.ispecMemSize, Types.iSpecMemorySize Types.defMinISpec),
     (ConstantUtils.ispecCpuCount, Types.iSpecCpuCount Types.defMinISpec),
     (ConstantUtils.ispecDiskCount, Types.iSpecDiskCount Types.defMinISpec),
     (ConstantUtils.ispecDiskSize, Types.iSpecDiskSize Types.defMinISpec),
     (ConstantUtils.ispecNicCount, Types.iSpecNicCount Types.defMinISpec),
     (ConstantUtils.ispecSpindleUse, Types.iSpecSpindleUse Types.defMinISpec)]),
   (ispecsMax,
    Map.fromList
    [(ConstantUtils.ispecMemSize, Types.iSpecMemorySize Types.defMaxISpec),
     (ConstantUtils.ispecCpuCount, Types.iSpecCpuCount Types.defMaxISpec),
     (ConstantUtils.ispecDiskCount, Types.iSpecDiskCount Types.defMaxISpec),
     (ConstantUtils.ispecDiskSize, Types.iSpecDiskSize Types.defMaxISpec),
     (ConstantUtils.ispecNicCount, Types.iSpecNicCount Types.defMaxISpec),
     (ConstantUtils.ispecSpindleUse, Types.iSpecSpindleUse Types.defMaxISpec)])]

ipolicyDefaults :: Map String PyValueEx
ipolicyDefaults =
  Map.fromList
  [ (ispecsMinmax,        PyValueEx [ispecsMinmaxDefaults])
  , (ispecsStd,           PyValueEx (Map.fromList
                                     [ (ispecMemSize,    128)
                                     , (ispecCpuCount,   1)
                                     , (ispecDiskCount,  1)
                                     , (ispecDiskSize,   1024)
                                     , (ispecNicCount,   1)
                                     , (ispecSpindleUse, 1)
                                     ] :: Map String Int))
  , (ipolicyDts,          PyValueEx (ConstantUtils.toList diskTemplates))
  , (ipolicyVcpuRatio,    PyValueEx (4.0 :: Double))
  , (ipolicySpindleRatio, PyValueEx (32.0 :: Double))
  ]

masterPoolSizeDefault :: Int
masterPoolSizeDefault = 10

-- * Exclusive storage

-- | Error margin used to compare physical disks
partMargin :: Double
partMargin = 0.01

-- | Space reserved when creating instance disks
partReserved :: Double
partReserved = 0.02

-- * Luxid job scheduling

-- | Time intervall in seconds for polling updates on the job queue. This
-- intervall is only relevant if the number of running jobs reaches the maximal
-- allowed number, as otherwise new jobs will be started immediately anyway.
-- Also, as jobs are watched via inotify, scheduling usually works independent
-- of polling. Therefore we chose a sufficiently large interval, in the order of
-- 5 minutes. As with the interval for reloading the configuration, we chose a
-- prime number to avoid accidental 'same wakeup' with other processes.
luxidJobqueuePollInterval :: Int
luxidJobqueuePollInterval = 307

-- | The default value for the maximal number of jobs to be running at the same
-- time. Once the maximal number is reached, new jobs will just be queued and
-- only started, once some of the other jobs have finished.
luxidMaximalRunningJobsDefault :: Int
luxidMaximalRunningJobsDefault = 20

-- | The default value for the maximal number of jobs that luxid tracks via
-- inotify. If the number of running jobs exceeds this limit (which only happens
-- if the user increases the default value of maximal running jobs), new forked
-- jobs are no longer tracked by inotify; progress will still be noticed on the
-- regular polls.
luxidMaximalTrackedJobsDefault :: Int
luxidMaximalTrackedJobsDefault = 25

-- | The number of retries when trying to @fork@ a new job.
-- Due to a bug in GHC, this can fail even though we synchronize all forks
-- and restrain from other @IO@ operations in the thread.
luxidRetryForkCount :: Int
luxidRetryForkCount = 5

-- | The average time period (in /us/) to wait between two @fork@ attempts.
-- The forking thread wait a random time period between @0@ and twice the
-- number, and with each attempt it doubles the step.
-- See 'luxidRetryForkCount'.
luxidRetryForkStepUS :: Int
luxidRetryForkStepUS = 500000

-- * Luxid job death testing

-- | The number of attempts to prove that a job is dead after sending it a
-- KILL signal.
luxidJobDeathDetectionRetries :: Int
luxidJobDeathDetectionRetries = 3

-- | Time to delay (in /us/) after unsucessfully verifying the death of a
-- job we believe to be dead. This is best choosen to be the average time
-- sending a SIGKILL to take effect.
luxidJobDeathDelay :: Int
luxidJobDeathDelay = 100000

-- * WConfD

-- | Time itnervall in seconds between checks that all lock owners are still
-- alive, and cleaning up the resources for the dead ones. As jobs dying without
-- releasing resources is the exception, not the rule, we don't want this task
-- to take up too many cycles itself. Hence we choose a sufficiently large
-- intervall, in the order of 5 minutes. To avoid accidental 'same wakeup'
-- with other tasks, we choose the next unused prime number.
wconfdDeathdetectionIntervall :: Int
wconfdDeathdetectionIntervall = 311

wconfdDefCtmo :: Int
wconfdDefCtmo = 10

wconfdDefRwto :: Int
wconfdDefRwto = 60

-- | The prefix of the WConfD livelock file name.
wconfLivelockPrefix :: String
wconfLivelockPrefix = "wconf-daemon"

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

confdReqInstanceDisks :: Int
confdReqInstanceDisks = Types.confdRequestTypeToRaw ReqInstanceDisks

confdReqConfigQuery :: Int
confdReqConfigQuery = Types.confdRequestTypeToRaw ReqConfigQuery

confdReqDataCollectors :: Int
confdReqDataCollectors = Types.confdRequestTypeToRaw ReqDataCollectors

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

-- | Maximum UDP datagram size.
--
-- On IPv4: 64K - 20 (ip header size) - 8 (udp header size) = 65507
-- On IPv6: 64K - 40 (ip6 header size) - 8 (udp header size) = 65487
--   (assuming we can't use jumbo frames)
-- We just set this to 60K, which should be enough
maxUdpDataSize :: Int
maxUdpDataSize = 61440

-- * User-id pool minimum/maximum acceptable user-ids

uidpoolUidMin :: Int
uidpoolUidMin = 0

-- | Assuming 32 bit user-ids
uidpoolUidMax :: Integer
uidpoolUidMax = 2 ^ 32 - 1

-- | Name or path of the pgrep command
pgrep :: String
pgrep = "pgrep"

-- | Name of the node group that gets created at cluster init or
-- upgrade
initialNodeGroupName :: String
initialNodeGroupName = "default"

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

-- | The hail iallocator
iallocHail :: String
iallocHail = "hail"

-- * Fake opcodes for functions that have hooks attached to them via
-- backend.RunLocalHooks

fakeOpMasterTurndown :: String
fakeOpMasterTurndown = "OP_CLUSTER_IP_TURNDOWN"

fakeOpMasterTurnup :: String
fakeOpMasterTurnup = "OP_CLUSTER_IP_TURNUP"


-- * Crypto Types
-- Types of cryptographic tokens used in node communication

cryptoTypeSslDigest :: String
cryptoTypeSslDigest = "ssl"

cryptoTypeSsh :: String
cryptoTypeSsh = "ssh"

-- So far only ssl keys are used in the context of this constant
cryptoTypes :: FrozenSet String
cryptoTypes = ConstantUtils.mkSet [cryptoTypeSslDigest]

-- * Crypto Actions
-- Actions that can be performed on crypto tokens

cryptoActionGet :: String
cryptoActionGet = "get"

cryptoActionCreate :: String
cryptoActionCreate = "create"

cryptoActionDelete :: String
cryptoActionDelete = "delete"

cryptoActions :: FrozenSet String
cryptoActions =
  ConstantUtils.mkSet [ cryptoActionCreate
                      , cryptoActionGet
                      , cryptoActionDelete]

-- Key word for master candidate cert list for bootstrapping.

cryptoBootstrap :: String
cryptoBootstrap = "bootstrap"

-- * Options for CryptoActions

-- Filename of the certificate
cryptoOptionCertFile :: String
cryptoOptionCertFile = "cert_file"

-- Serial number of the certificate
cryptoOptionSerialNo :: String
cryptoOptionSerialNo = "serial_no"

-- * SSH key types

sshkDsa :: String
sshkDsa = Types.sshKeyTypeToRaw DSA

sshkEcdsa :: String
sshkEcdsa = Types.sshKeyTypeToRaw ECDSA

sshkRsa :: String
sshkRsa = Types.sshKeyTypeToRaw RSA

sshkAll :: FrozenSet String
sshkAll = ConstantUtils.mkSet [sshkRsa, sshkDsa, sshkEcdsa]

-- * SSH authorized key types

sshakDss :: String
sshakDss = "ssh-dss"

sshakRsa :: String
sshakRsa = "ssh-rsa"

sshakAll :: FrozenSet String
sshakAll = ConstantUtils.mkSet [sshakDss, sshakRsa]

-- * SSH key default values
-- Document the change in gnt-cluster.rst when changing these

sshDefaultKeyType :: String
sshDefaultKeyType = sshkRsa

sshDefaultKeyBits :: Int
sshDefaultKeyBits = 2048

-- * SSH setup

sshsClusterName :: String
sshsClusterName = "cluster_name"

sshsSshHostKey :: String
sshsSshHostKey = "ssh_host_key"

sshsSshRootKey :: String
sshsSshRootKey = "ssh_root_key"

sshsSshAuthorizedKeys :: String
sshsSshAuthorizedKeys = "authorized_keys"

sshsSshPublicKeys :: String
sshsSshPublicKeys = "public_keys"

sshsNodeDaemonCertificate :: String
sshsNodeDaemonCertificate = "node_daemon_certificate"

sshsSshKeyType :: String
sshsSshKeyType = "ssh_key_type"

sshsSshKeyBits :: String
sshsSshKeyBits = "ssh_key_bits"

-- Number of maximum retries when contacting nodes per SSH
-- during SSH update operations.
sshsMaxRetries :: Integer
sshsMaxRetries = 3

sshsAdd :: String
sshsAdd = "add"

sshsReplaceOrAdd :: String
sshsReplaceOrAdd = "replace_or_add"

sshsRemove :: String
sshsRemove = "remove"

sshsOverride :: String
sshsOverride = "override"

sshsClear :: String
sshsClear = "clear"

sshsGenerate :: String
sshsGenerate = "generate"

sshsSuffix :: String
sshsSuffix = "suffix"

sshsMasterSuffix :: String
sshsMasterSuffix = "_master_tmp"

sshsActions :: FrozenSet String
sshsActions = ConstantUtils.mkSet [ sshsAdd
                                  , sshsRemove
                                  , sshsOverride
                                  , sshsClear
                                  , sshsReplaceOrAdd]

-- * Key files for SSH daemon

sshHostDsaPriv :: String
sshHostDsaPriv = sshConfigDir ++ "/ssh_host_dsa_key"

sshHostDsaPub :: String
sshHostDsaPub = sshHostDsaPriv ++ ".pub"

sshHostEcdsaPriv :: String
sshHostEcdsaPriv = sshConfigDir ++ "/ssh_host_ecdsa_key"

sshHostEcdsaPub :: String
sshHostEcdsaPub = sshHostEcdsaPriv ++ ".pub"

sshHostRsaPriv :: String
sshHostRsaPriv = sshConfigDir ++ "/ssh_host_rsa_key"

sshHostRsaPub :: String
sshHostRsaPub = sshHostRsaPriv ++ ".pub"

sshDaemonKeyfiles :: Map String (String, String)
sshDaemonKeyfiles =
  Map.fromList [ (sshkRsa, (sshHostRsaPriv, sshHostRsaPub))
               , (sshkDsa, (sshHostDsaPriv, sshHostDsaPub))
               , (sshkEcdsa, (sshHostEcdsaPriv, sshHostEcdsaPub))
               ]

-- * Node daemon setup

ndsClusterName :: String
ndsClusterName = "cluster_name"

ndsNodeDaemonCertificate :: String
ndsNodeDaemonCertificate = "node_daemon_certificate"

ndsSsconf :: String
ndsSsconf = "ssconf"

ndsStartNodeDaemon :: String
ndsStartNodeDaemon = "start_node_daemon"

ndsNodeName :: String
ndsNodeName = "node_name"

ndsAction :: String
ndsAction = "action"

-- * VCluster related constants

vClusterEtcHosts :: String
vClusterEtcHosts = "/etc/hosts"

vClusterVirtPathPrefix :: String
vClusterVirtPathPrefix = "/###-VIRTUAL-PATH-###,"

vClusterRootdirEnvname :: String
vClusterRootdirEnvname = "GANETI_ROOTDIR"

vClusterHostnameEnvname :: String
vClusterHostnameEnvname = "GANETI_HOSTNAME"

vClusterVpathWhitelist :: FrozenSet String
vClusterVpathWhitelist = ConstantUtils.mkSet [ vClusterEtcHosts ]

-- * The source reasons for the execution of an OpCode

opcodeReasonSrcClient :: String
opcodeReasonSrcClient = "gnt:client"

_opcodeReasonSrcDaemon :: String
_opcodeReasonSrcDaemon = "gnt:daemon"

_opcodeReasonSrcMasterd :: String
_opcodeReasonSrcMasterd = _opcodeReasonSrcDaemon ++ ":masterd"

opcodeReasonSrcNoded :: String
opcodeReasonSrcNoded = _opcodeReasonSrcDaemon ++ ":noded"

opcodeReasonSrcOpcode :: String
opcodeReasonSrcOpcode = "gnt:opcode"

opcodeReasonSrcPickup :: String
opcodeReasonSrcPickup = _opcodeReasonSrcMasterd ++ ":pickup"

opcodeReasonSrcWatcher :: String
opcodeReasonSrcWatcher = "gnt:watcher"

opcodeReasonSrcRlib2 :: String
opcodeReasonSrcRlib2 = "gnt:library:rlib2"

opcodeReasonSrcUser :: String
opcodeReasonSrcUser = "gnt:user"

opcodeReasonSources :: FrozenSet String
opcodeReasonSources =
  ConstantUtils.mkSet [opcodeReasonSrcClient,
                       opcodeReasonSrcNoded,
                       opcodeReasonSrcOpcode,
                       opcodeReasonSrcPickup,
                       opcodeReasonSrcWatcher,
                       opcodeReasonSrcRlib2,
                       opcodeReasonSrcUser]

-- | Path generating random UUID
randomUuidFile :: String
randomUuidFile = ConstantUtils.randomUuidFile


-- * Auto-repair levels

autoRepairFailover :: String
autoRepairFailover = Types.autoRepairTypeToRaw ArFailover

autoRepairFixStorage :: String
autoRepairFixStorage = Types.autoRepairTypeToRaw ArFixStorage

autoRepairMigrate :: String
autoRepairMigrate = Types.autoRepairTypeToRaw ArMigrate

autoRepairReinstall :: String
autoRepairReinstall = Types.autoRepairTypeToRaw ArReinstall

autoRepairAllTypes :: FrozenSet String
autoRepairAllTypes =
  ConstantUtils.mkSet [autoRepairFailover,
                       autoRepairFixStorage,
                       autoRepairMigrate,
                       autoRepairReinstall]

-- * Auto-repair results

autoRepairEnoperm :: String
autoRepairEnoperm = Types.autoRepairResultToRaw ArEnoperm

autoRepairFailure :: String
autoRepairFailure = Types.autoRepairResultToRaw ArFailure

autoRepairSuccess :: String
autoRepairSuccess = Types.autoRepairResultToRaw ArSuccess

autoRepairAllResults :: FrozenSet String
autoRepairAllResults =
  ConstantUtils.mkSet [autoRepairEnoperm, autoRepairFailure, autoRepairSuccess]



-- | The version identifier for builtin data collectors
builtinDataCollectorVersion :: String
builtinDataCollectorVersion = "B"

-- | The reason trail opcode parameter name
opcodeReason :: String
opcodeReason = "reason"

-- | The reason trail opcode parameter name
opcodeSequential :: String
opcodeSequential = "sequential"

diskstatsFile :: String
diskstatsFile = "/proc/diskstats"

-- *  CPU load collector

statFile :: String
statFile = "/proc/stat"

cpuavgloadBufferSize :: Int
cpuavgloadBufferSize = 150

-- | Window size for averaging in seconds.
cpuavgloadWindowSize :: Int
cpuavgloadWindowSize = 600

-- * Xen cpu load collector

xentopCommand :: String
xentopCommand = "xentop"

-- | Minimal observation time in seconds, the xen cpu load collector
-- can report load averages for the first time.
xentopAverageThreshold :: Int
xentopAverageThreshold = 100

-- * Monitoring daemon

-- | Mond's variable for periodical data collection
mondTimeInterval :: Int
mondTimeInterval = 5

-- | Mond's waiting time for requesting the current configuration.
mondConfigTimeInterval :: Int
mondConfigTimeInterval = 15

-- | Mond's latest API version
mondLatestApiVersion :: Int
mondLatestApiVersion = 1

mondDefaultCategory :: String
mondDefaultCategory = "default"

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

-- * Hotplug Actions

hotplugActionAdd :: String
hotplugActionAdd = Types.hotplugActionToRaw HAAdd

hotplugActionRemove :: String
hotplugActionRemove = Types.hotplugActionToRaw HARemove

hotplugActionModify :: String
hotplugActionModify = Types.hotplugActionToRaw HAMod

hotplugAllActions :: FrozenSet String
hotplugAllActions =
  ConstantUtils.mkSet $ map Types.hotplugActionToRaw [minBound..]

-- * Hotplug Device Targets

hotplugTargetNic :: String
hotplugTargetNic = Types.hotplugTargetToRaw HTNic

hotplugTargetDisk :: String
hotplugTargetDisk = Types.hotplugTargetToRaw HTDisk

hotplugAllTargets :: FrozenSet String
hotplugAllTargets =
  ConstantUtils.mkSet $ map Types.hotplugTargetToRaw [minBound..]

-- | Timeout for disk removal (seconds)
diskRemoveRetryTimeout :: Int
diskRemoveRetryTimeout = 30

-- | Interval between disk removal retries (seconds)
diskRemoveRetryInterval :: Int
diskRemoveRetryInterval  = 3

-- * UUID regex

uuidRegex :: String
uuidRegex = "^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"

-- * Luxi constants

luxiSocketPerms :: Int
luxiSocketPerms = 0o660

luxiKeyMethod :: String
luxiKeyMethod = "method"

luxiKeyArgs :: String
luxiKeyArgs = "args"

luxiKeySuccess :: String
luxiKeySuccess = "success"

luxiKeyResult :: String
luxiKeyResult = "result"

luxiKeyVersion :: String
luxiKeyVersion = "version"

luxiReqSubmitJob :: String
luxiReqSubmitJob = "SubmitJob"

luxiReqSubmitJobToDrainedQueue :: String
luxiReqSubmitJobToDrainedQueue = "SubmitJobToDrainedQueue"

luxiReqSubmitManyJobs :: String
luxiReqSubmitManyJobs = "SubmitManyJobs"

luxiReqWaitForJobChange :: String
luxiReqWaitForJobChange = "WaitForJobChange"

luxiReqPickupJob :: String
luxiReqPickupJob = "PickupJob"

luxiReqCancelJob :: String
luxiReqCancelJob = "CancelJob"

luxiReqArchiveJob :: String
luxiReqArchiveJob = "ArchiveJob"

luxiReqChangeJobPriority :: String
luxiReqChangeJobPriority = "ChangeJobPriority"

luxiReqAutoArchiveJobs :: String
luxiReqAutoArchiveJobs = "AutoArchiveJobs"

luxiReqQuery :: String
luxiReqQuery = "Query"

luxiReqQueryFields :: String
luxiReqQueryFields = "QueryFields"

luxiReqQueryJobs :: String
luxiReqQueryJobs = "QueryJobs"

luxiReqQueryFilters :: String
luxiReqQueryFilters = "QueryFilters"

luxiReqReplaceFilter :: String
luxiReqReplaceFilter = "ReplaceFilter"

luxiReqDeleteFilter :: String
luxiReqDeleteFilter = "DeleteFilter"

luxiReqQueryInstances :: String
luxiReqQueryInstances = "QueryInstances"

luxiReqQueryNodes :: String
luxiReqQueryNodes = "QueryNodes"

luxiReqQueryGroups :: String
luxiReqQueryGroups = "QueryGroups"

luxiReqQueryNetworks :: String
luxiReqQueryNetworks = "QueryNetworks"

luxiReqQueryExports :: String
luxiReqQueryExports = "QueryExports"

luxiReqQueryConfigValues :: String
luxiReqQueryConfigValues = "QueryConfigValues"

luxiReqQueryClusterInfo :: String
luxiReqQueryClusterInfo = "QueryClusterInfo"

luxiReqQueryTags :: String
luxiReqQueryTags = "QueryTags"

luxiReqSetDrainFlag :: String
luxiReqSetDrainFlag = "SetDrainFlag"

luxiReqSetWatcherPause :: String
luxiReqSetWatcherPause = "SetWatcherPause"

luxiReqAll :: FrozenSet String
luxiReqAll =
  ConstantUtils.mkSet
  [ luxiReqArchiveJob
  , luxiReqAutoArchiveJobs
  , luxiReqCancelJob
  , luxiReqChangeJobPriority
  , luxiReqQuery
  , luxiReqQueryClusterInfo
  , luxiReqQueryConfigValues
  , luxiReqQueryExports
  , luxiReqQueryFields
  , luxiReqQueryGroups
  , luxiReqQueryInstances
  , luxiReqQueryJobs
  , luxiReqQueryNodes
  , luxiReqQueryNetworks
  , luxiReqQueryTags
  , luxiReqSetDrainFlag
  , luxiReqSetWatcherPause
  , luxiReqSubmitJob
  , luxiReqSubmitJobToDrainedQueue
  , luxiReqSubmitManyJobs
  , luxiReqWaitForJobChange
  , luxiReqPickupJob
  , luxiReqQueryFilters
  , luxiReqReplaceFilter
  , luxiReqDeleteFilter
  ]

luxiDefCtmo :: Int
luxiDefCtmo = 30

luxiDefRwto :: Int
luxiDefRwto = 180

-- | Luxi 'WaitForJobChange' timeout
luxiWfjcTimeout :: Int
luxiWfjcTimeout = (luxiDefRwto - 1) `div` 2

-- | The prefix of the LUXI livelock file name
luxiLivelockPrefix :: String
luxiLivelockPrefix = "luxi-daemon"

-- | The LUXI daemon waits this number of seconds for ensuring that a canceled
-- job terminates before giving up.
luxiCancelJobTimeout :: Int
luxiCancelJobTimeout = (luxiDefRwto - 1) `div` 4

-- * Master voting constants

-- | Number of retries to carry out if nodes do not answer
masterVotingRetries :: Int
masterVotingRetries = 6

-- | Retry interval (in seconds) in master voting, if not enough answers
-- could be gathered.
masterVotingRetryIntervall :: Int
masterVotingRetryIntervall = 10

-- * Query language constants

-- ** Logic operators with one or more operands, each of which is a
-- filter on its own

qlangOpAnd :: String
qlangOpAnd = "&"

qlangOpOr :: String
qlangOpOr = "|"

-- ** Unary operators with exactly one operand

qlangOpNot :: String
qlangOpNot = "!"

qlangOpTrue :: String
qlangOpTrue = "?"

-- ** Binary operators with exactly two operands, the field name and
-- an operator-specific value

qlangOpContains :: String
qlangOpContains = "=[]"

qlangOpEqual :: String
qlangOpEqual = "=="

qlangOpEqualLegacy :: String
qlangOpEqualLegacy = "="

qlangOpGe :: String
qlangOpGe = ">="

qlangOpGt :: String
qlangOpGt = ">"

qlangOpLe :: String
qlangOpLe = "<="

qlangOpLt :: String
qlangOpLt = "<"

qlangOpNotEqual :: String
qlangOpNotEqual = "!="

qlangOpRegexp :: String
qlangOpRegexp = "=~"

-- | Characters used for detecting user-written filters (see
-- L{_CheckFilter})

qlangFilterDetectionChars :: FrozenSet String
qlangFilterDetectionChars =
  ConstantUtils.mkSet ["!", " ", "\"", "\'",
                       ")", "(", "\x0b", "\n",
                       "\r", "\x0c", "/", "<",
                       "\t", ">", "=", "\\", "~"]

-- | Characters used to detect globbing filters
qlangGlobDetectionChars :: FrozenSet String
qlangGlobDetectionChars = ConstantUtils.mkSet ["*", "?"]

-- * Error related constants
--
-- 'OpPrereqError' failure types

-- | Environment error (e.g. node disk error)
errorsEcodeEnviron :: String
errorsEcodeEnviron = "environment_error"

-- | Entity already exists
errorsEcodeExists :: String
errorsEcodeExists = "already_exists"

-- | Internal cluster error
errorsEcodeFault :: String
errorsEcodeFault = "internal_error"

-- | Wrong arguments (at syntax level)
errorsEcodeInval :: String
errorsEcodeInval = "wrong_input"

-- | Entity not found
errorsEcodeNoent :: String
errorsEcodeNoent = "unknown_entity"

-- | Not enough resources (iallocator failure, disk space, memory, etc)
errorsEcodeNores :: String
errorsEcodeNores = "insufficient_resources"

-- | Resource not unique (e.g. MAC or IP duplication)
errorsEcodeNotunique :: String
errorsEcodeNotunique = "resource_not_unique"

-- | Resolver errors
errorsEcodeResolver :: String
errorsEcodeResolver = "resolver_error"

-- | Wrong entity state
errorsEcodeState :: String
errorsEcodeState = "wrong_state"

-- | Temporarily out of resources; operation can be tried again
errorsEcodeTempNores :: String
errorsEcodeTempNores = "temp_insufficient_resources"

errorsEcodeAll :: FrozenSet String
errorsEcodeAll =
  ConstantUtils.mkSet [ errorsEcodeNores
                      , errorsEcodeExists
                      , errorsEcodeState
                      , errorsEcodeNotunique
                      , errorsEcodeTempNores
                      , errorsEcodeNoent
                      , errorsEcodeFault
                      , errorsEcodeResolver
                      , errorsEcodeInval
                      , errorsEcodeEnviron
                      ]

-- * Jstore related constants

jstoreJobsPerArchiveDirectory :: Int
jstoreJobsPerArchiveDirectory = 10000

-- * Gluster settings

-- | Name of the Gluster host setting
glusterHost :: String
glusterHost = "host"

-- | Default value of the Gluster host setting
glusterHostDefault :: String
glusterHostDefault = "127.0.0.1"

-- | Name of the Gluster volume setting
glusterVolume :: String
glusterVolume = "volume"

-- | Default value of the Gluster volume setting
glusterVolumeDefault :: String
glusterVolumeDefault = "gv0"

-- | Name of the Gluster port setting
glusterPort :: String
glusterPort = "port"

-- | Default value of the Gluster port setting
glusterPortDefault :: Int
glusterPortDefault = 24007

-- * Instance communication
--
-- The instance communication attaches an additional NIC, named
-- @instanceCommunicationNicPrefix@:@instanceName@ with MAC address
-- prefixed by @instanceCommunicationMacPrefix@, to the instances that
-- have instance communication enabled.  This NIC is part of the
-- instance communication network which is supplied by the user via
--
--   gnt-cluster modify --instance-communication=mynetwork
--
-- This network is defined as @instanceCommunicationNetwork4@ for IPv4
-- and @instanceCommunicationNetwork6@ for IPv6.

instanceCommunicationDoc :: String
instanceCommunicationDoc =
  "Enable or disable the communication mechanism for an instance"

instanceCommunicationMacPrefix :: String
instanceCommunicationMacPrefix = "52:54:00"

-- | The instance communication network is a link-local IPv4/IPv6
-- network because the communication is meant to be exclusive between
-- the host and the guest and not routed outside the node.
instanceCommunicationNetwork4 :: String
instanceCommunicationNetwork4 = "169.254.0.0/16"

-- | See 'instanceCommunicationNetwork4'.
instanceCommunicationNetwork6 :: String
instanceCommunicationNetwork6 = "fe80::/10"

instanceCommunicationNetworkLink :: String
instanceCommunicationNetworkLink = "communication_rt"

instanceCommunicationNetworkMode :: String
instanceCommunicationNetworkMode = nicModeRouted

instanceCommunicationNicPrefix :: String
instanceCommunicationNicPrefix = "ganeti:communication:"

-- | Parameters that should be protected
--
-- Python does not have a type system and can't automatically infer what should
-- be the resulting type of a JSON request. As a result, it must rely on this
-- list of parameter names to protect values correctly.
--
-- Names ending in _cluster will be treated as dicts of dicts of private values.
-- Otherwise they are considered dicts of private values.
privateParametersBlacklist :: [String]
privateParametersBlacklist = [ "osparams_private"
                             , "osparams_secret"
                             , "osparams_private_cluster"
                             ]

-- | Warn the user that the logging level is too low for production use.
debugModeConfidentialityWarning :: String
debugModeConfidentialityWarning =
  "ALERT: %s started in debug mode.\n\
  \ Private and secret parameters WILL be logged!\n"

-- | Use to hide secret parameter value
redacted :: String
redacted = Types.redacted

-- * Stat dictionary entries
--
-- The get_file_info RPC returns a number of values as a dictionary, and the
-- following constants are both descriptions and means of accessing them.

-- | The size of the file
statSize :: String
statSize = "size"


-- * Helper VM-related timeouts

-- | The default fixed timeout needed to startup the helper VM.
helperVmStartup :: Int
helperVmStartup = 5 * 60

-- | The default fixed timeout needed until the helper VM is finally
-- shutdown, for example, after installing the OS.
helperVmShutdown :: Int
helperVmShutdown = 2 * 60 * 60

-- | The zeroing timeout per MiB of disks to zero
--
-- Determined by estimating that a disk writes at a relatively slow
-- speed of 1/5 of the max speed of current drives.
zeroingTimeoutPerMib :: Double
zeroingTimeoutPerMib = 1.0 / (100.0 / 5.0)

-- * Networking

-- The minimum size of a network.
ipv4NetworkMinSize :: Int
ipv4NetworkMinSize = 30

-- The maximum size of a network.
--
-- FIXME: This limit is for performance reasons. Remove when refactoring
-- for performance tuning was successful.
ipv4NetworkMaxSize :: Int
ipv4NetworkMaxSize = 30

-- * Data Collectors

dataCollectorCPULoad    :: String
dataCollectorCPULoad    = "cpu-avg-load"

dataCollectorXenCpuLoad :: String
dataCollectorXenCpuLoad = "xen-cpu-avg-load"

dataCollectorDiskStats  :: String
dataCollectorDiskStats  = "diskstats"

dataCollectorDrbd       :: String
dataCollectorDrbd       = "drbd"

dataCollectorLv         :: String
dataCollectorLv         = "lv"

dataCollectorInstStatus :: String
dataCollectorInstStatus = "inst-status-xen"

dataCollectorParameterInterval :: String
dataCollectorParameterInterval = "interval"

dataCollectorNames :: FrozenSet String
dataCollectorNames =
  ConstantUtils.mkSet [ dataCollectorCPULoad
                      , dataCollectorDiskStats
                      , dataCollectorDrbd
                      , dataCollectorLv
                      , dataCollectorInstStatus
                      , dataCollectorXenCpuLoad
                      ]

dataCollectorStateActive :: String
dataCollectorStateActive = "active"

dataCollectorsEnabledName :: String
dataCollectorsEnabledName = "enabled_data_collectors"

dataCollectorsIntervalName :: String
dataCollectorsIntervalName = "data_collector_interval"

-- * HTools tag prefixes

exTagsPrefix :: String
exTagsPrefix = Tags.exTagsPrefix

-- | The polling frequency to wait for a job status change
cliWfjcFrequency :: Int
cliWfjcFrequency = 20

-- | Default 'WaitForJobChange' timeout in seconds
defaultWfjcTimeout :: Int
defaultWfjcTimeout = 60

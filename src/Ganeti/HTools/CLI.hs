{-| Implementation of command-line functions.

This module holds the common command-line related functions for the
binaries, separated into this module since "Ganeti.Utils" is
used in many other places and this is more IO oriented.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Ganeti.HTools.CLI
  ( Options(..)
  , OptType
  , defaultOptions
  , Ganeti.HTools.CLI.parseOpts
  , parseOptsInner
  , parseYesNo
  , parseISpecString
  , shTemplate
  , maybeSaveCommands
  , maybePrintNodes
  , maybePrintInsts
  , maybeShowWarnings
  , printKeys
  , printFinal
  , setNodeStatus
  -- * The options
  , oDataFile
  , oDiskMoves
  , oDiskTemplate
  , oDryRun
  , oSpindleUse
  , oDynuFile
  , oMonD
  , oMonDDataFile
  , oMonDXen
  , oEvacMode
  , oMonDExitMissing
  , oFirstJobGroup
  , oRestrictedMigrate
  , oExInst
  , oExTags
  , oExecJobs
  , oForce
  , oFullEvacuation
  , oGroup
  , oIAllocSrc
  , oIgnoreDyn
  , oIgnoreNonRedundant
  , oIgnoreSoftErrors
  , oIndependentGroups
  , oAcceptExisting
  , oInstMoves
  , oJobDelay
  , genOLuxiSocket
  , oLuxiSocket
  , oMachineReadable
  , oMaxCpu
  , oMaxSolLength
  , oMinDisk
  , oMinGain
  , oMinGainLim
  , oMinResources
  , oMinScore
  , oNoHeaders
  , oNoSimulation
  , oNodeSim
  , oNodeTags
  , oOfflineMaintenance
  , oOfflineNode
  , oOneStepOnly
  , oOutputDir
  , oPrintCommands
  , oPrintInsts
  , oPrintMoves
  , oPrintNodes
  , oQuiet
  , oRapiMaster
  , oReason
  , oRestrictToNodes
  , oSaveCluster
  , oSelInst
  , oShowHelp
  , oShowVer
  , oShowComp
  , oSkipNonRedundant
  , oStdSpec
  , oTargetResources
  , oTieredSpec
  , oVerbose
  , oPriority
  , oNoCapacityChecks
  , genericOpts
  ) where

import Control.Monad
import Data.Char (toUpper)
import Data.Maybe (fromMaybe)
import System.Console.GetOpt
import System.IO
import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.Path as Path
import Ganeti.HTools.Types
import Ganeti.BasicTypes
import Ganeti.Common as Common
import Ganeti.Types
import Ganeti.Utils

-- * Data types

-- | Command line options structure.
data Options = Options
  { optDataFile    :: Maybe FilePath -- ^ Path to the cluster data file
  , optDiskMoves   :: Bool           -- ^ Allow disk moves
  , optInstMoves   :: Bool           -- ^ Allow instance moves
  , optDiskTemplate :: Maybe DiskTemplate  -- ^ Override for the disk template
  , optSpindleUse  :: Maybe Int      -- ^ Override for the spindle usage
  , optDynuFile    :: Maybe FilePath -- ^ Optional file with dynamic use data
  , optIgnoreDynu  :: Bool           -- ^ Do not use dynamic use data
  , optIgnoreSoftErrors :: Bool      -- ^ Ignore soft errors in balancing moves
  , optIndependentGroups :: Bool     -- ^ consider groups independently
  , optAcceptExisting :: Bool        -- ^ accept existing N+1 violations
  , optMonD        :: Bool           -- ^ Query MonDs
  , optMonDFile    :: Maybe FilePath -- ^ Optional file with data provided
                                     -- by MonDs
  , optMonDXen     :: Bool           -- ^ Should Xen-specific collectors be
                                     -- considered (only if MonD is queried)
  , optMonDExitMissing :: Bool       -- ^ If the program should exit on missing
                                     -- MonD data
  , optEvacMode    :: Bool           -- ^ Enable evacuation mode
  , optRestrictedMigrate :: Bool     -- ^ Disallow replace-primary moves
  , optExInst      :: [String]       -- ^ Instances to be excluded
  , optExTags      :: Maybe [String] -- ^ Tags to use for exclusion
  , optExecJobs    :: Bool           -- ^ Execute the commands via Luxi
  , optDryRun      :: Bool           -- ^ Only do a dry run
  , optFirstJobGroup :: Bool         -- ^ Only execute the first group of jobs
  , optForce       :: Bool           -- ^ Force the execution
  , optFullEvacuation :: Bool        -- ^ Fully evacuate nodes to be rebooted
  , optGroup       :: Maybe GroupID  -- ^ The UUID of the group to process
  , optIAllocSrc   :: Maybe FilePath -- ^ The iallocation spec
  , optIgnoreNonRedundant :: Bool    -- ^ Ignore non-redundant instances
  , optSelInst     :: [String]       -- ^ Instances to be excluded
  , optLuxi        :: Maybe FilePath -- ^ Collect data from Luxi
  , optJobDelay    :: Double         -- ^ Delay before executing first job
  , optMachineReadable :: Bool       -- ^ Output machine-readable format
  , optMaster      :: String         -- ^ Collect data from RAPI
  , optMaxLength   :: Int            -- ^ Stop after this many steps
  , optMcpu        :: Maybe Double   -- ^ Override max cpu ratio for nodes
  , optMdsk        :: Double         -- ^ Max disk usage ratio for nodes
  , optMinGain     :: Score          -- ^ Min gain we aim for in a step
  , optMinGainLim  :: Score          -- ^ Limit below which we apply mingain
  , optMinResources :: Double        -- ^ Minimal resources for hsqueeze
  , optMinScore    :: Score          -- ^ The minimum score we aim for
  , optNoHeaders   :: Bool           -- ^ Do not show a header line
  , optNoSimulation :: Bool          -- ^ Skip the rebalancing dry-run
  , optNodeSim     :: [String]       -- ^ Cluster simulation mode
  , optNodeTags    :: Maybe [String] -- ^ List of node tags to restrict to 
  , optOffline     :: [String]       -- ^ Names of offline nodes
  , optRestrictToNodes :: Maybe [String] -- ^ if not Nothing, restrict
                                     -- allocation to those nodes
  , optOfflineMaintenance :: Bool    -- ^ Pretend all instances are offline
  , optOneStepOnly :: Bool           -- ^ Only do the first step
  , optOutPath     :: FilePath       -- ^ Path to the output directory
  , optPrintMoves  :: Bool           -- ^ Whether to show the instance moves
  , optReason      :: Maybe String   -- ^ The reason to be passed when
                                     -- submitting jobs
  , optSaveCluster :: Maybe FilePath -- ^ Save cluster state to this file
  , optShowCmds    :: Maybe FilePath -- ^ Whether to show the command list
  , optShowHelp    :: Bool           -- ^ Just show the help
  , optShowComp    :: Bool           -- ^ Just show the completion info
  , optShowInsts   :: Bool           -- ^ Whether to show the instance map
  , optShowNodes   :: Maybe [String] -- ^ Whether to show node status
  , optShowVer     :: Bool           -- ^ Just show the program version
  , optSkipNonRedundant :: Bool      -- ^ Skip nodes with non-redundant instance
  , optStdSpec     :: Maybe RSpec    -- ^ Requested standard specs
  , optTargetResources :: Double     -- ^ Target resources for squeezing
  , optTestCount   :: Maybe Int      -- ^ Optional test count override
  , optTieredSpec  :: Maybe RSpec    -- ^ Requested specs for tiered mode
  , optReplay      :: Maybe String   -- ^ Unittests: RNG state
  , optVerbose     :: Int            -- ^ Verbosity level
  , optPriority    :: Maybe OpSubmitPriority -- ^ OpCode submit priority
  , optCapacity    :: Bool           -- ^ Also do capacity-related checks
  } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
  { optDataFile    = Nothing
  , optDiskMoves   = True
  , optInstMoves   = True
  , optIndependentGroups = False
  , optAcceptExisting = False
  , optDiskTemplate = Nothing
  , optSpindleUse  = Nothing
  , optIgnoreDynu  = False
  , optIgnoreSoftErrors = False
  , optDynuFile    = Nothing
  , optMonD        = False
  , optMonDFile = Nothing
  , optMonDXen     = False
  , optMonDExitMissing = False
  , optEvacMode    = False
  , optRestrictedMigrate = False
  , optExInst      = []
  , optExTags      = Nothing
  , optExecJobs    = False
  , optDryRun      = False
  , optFirstJobGroup = False
  , optForce       = False
  , optFullEvacuation = False
  , optGroup       = Nothing
  , optIAllocSrc   = Nothing
  , optIgnoreNonRedundant = False
  , optSelInst     = []
  , optLuxi        = Nothing
  , optJobDelay    = 10
  , optMachineReadable = False
  , optMaster      = ""
  , optMaxLength   = -1
  , optMcpu        = Nothing
  , optMdsk        = defReservedDiskRatio
  , optMinGain     = 1e-2
  , optMinGainLim  = 1e-1
  , optMinResources = 2.0
  , optMinScore    = 1e-9
  , optNoHeaders   = False
  , optNoSimulation = False
  , optNodeSim     = []
  , optNodeTags    = Nothing
  , optSkipNonRedundant = False
  , optOffline     = []
  , optRestrictToNodes = Nothing
  , optOfflineMaintenance = False
  , optOneStepOnly = False
  , optOutPath     = "."
  , optPrintMoves  = False
  , optReason      = Nothing
  , optSaveCluster = Nothing
  , optShowCmds    = Nothing
  , optShowHelp    = False
  , optShowComp    = False
  , optShowInsts   = False
  , optShowNodes   = Nothing
  , optShowVer     = False
  , optStdSpec     = Nothing
  , optTargetResources = 2.0
  , optTestCount   = Nothing
  , optTieredSpec  = Nothing
  , optReplay      = Nothing
  , optVerbose     = 1
  , optPriority    = Nothing
  , optCapacity    = True
  }

-- | Abbreviation for the option type.
type OptType = GenericOptType Options

instance StandardOptions Options where
  helpRequested = optShowHelp
  verRequested  = optShowVer
  compRequested = optShowComp
  requestHelp o = o { optShowHelp = True }
  requestVer  o = o { optShowVer  = True }
  requestComp o = o { optShowComp = True }

-- * Helper functions

parseISpecString :: String -> String -> Result RSpec
parseISpecString descr inp = do
  let sp = sepSplit ',' inp
      err = Bad ("Invalid " ++ descr ++ " specification: '" ++ inp ++
                 "', expected disk,ram,cpu")
  when (length sp < 3 || length sp > 4) err
  prs <- mapM (\(fn, val) -> fn val) $
         zip [ annotateResult (descr ++ " specs disk") . parseUnit
             , annotateResult (descr ++ " specs memory") . parseUnit
             , tryRead (descr ++ " specs cpus")
             , tryRead (descr ++ " specs spindles")
             ] sp
  case prs of
    {- Spindles are optional, so that they are not needed when exclusive storage
       is disabled. When exclusive storage is disabled, spindles are ignored,
       so the actual value doesn't matter. We use 1 as a default so that in
       case someone forgets and exclusive storage is enabled, we don't run into
       weird situations. -}
    [dsk, ram, cpu] -> return $ RSpec cpu ram dsk 1
    [dsk, ram, cpu, spn] -> return $ RSpec cpu ram dsk spn
    _ -> err

-- | Disk template choices.
optComplDiskTemplate :: OptCompletion
optComplDiskTemplate = OptComplChoices $
                       map diskTemplateToRaw [minBound..maxBound]

-- * Command line options

oDataFile :: OptType
oDataFile =
  (Option "t" ["text-data"]
   (ReqArg (\ f o -> Ok o { optDataFile = Just f }) "FILE")
   "the cluster data FILE",
   OptComplFile)

oDiskMoves :: OptType
oDiskMoves =
  (Option "" ["no-disk-moves"]
   (NoArg (\ opts -> Ok opts { optDiskMoves = False}))
   "disallow disk moves from the list of allowed instance changes,\
   \ thus allowing only the 'cheap' failover/migrate operations",
   OptComplNone)

oMonD :: OptType
oMonD =
  (Option "" ["mond"]
   (OptArg (\ f opts -> do
              flag <- parseYesNo True f
              return $ opts { optMonD = flag }) "CHOICE")
   "pass either 'yes' or 'no' to query all monDs",
   optComplYesNo)

oMonDDataFile :: OptType
oMonDDataFile =
  (Option "" ["mond-data"]
   (ReqArg (\ f opts -> Ok opts { optMonDFile = Just f }) "FILE")
   "Import data provided by MonDs from the given FILE",
   OptComplFile)

oMonDXen :: OptType
oMonDXen =
  (Option "" ["mond-xen"]
    (NoArg (\ opts -> Ok opts { optMonDXen = True }))
    "also consider xen-specific collectors in MonD queries",
    OptComplNone)

oMonDExitMissing :: OptType
oMonDExitMissing =
  (Option "" ["exit-on-missing-mond-data"]
    (NoArg (\ opts -> Ok opts { optMonDExitMissing = True }))
    "abort if the data available from the monitoring daemons is incomplete",
    OptComplNone)

oDiskTemplate :: OptType
oDiskTemplate =
  (Option "" ["disk-template"]
   (reqWithConversion diskTemplateFromRaw
    (\dt opts -> Ok opts { optDiskTemplate = Just dt })
    "TEMPLATE") "select the desired disk template",
   optComplDiskTemplate)

oSpindleUse :: OptType
oSpindleUse =
  (Option "" ["spindle-use"]
   (reqWithConversion (tryRead "parsing spindle-use")
    (\su opts -> do
       when (su < 0) $
            fail "Invalid value of the spindle-use (expected >= 0)"
       return $ opts { optSpindleUse = Just su })
    "SPINDLES") "select how many virtual spindle instances use\
                \ [default read from cluster]",
   OptComplFloat)

oSelInst :: OptType
oSelInst =
  (Option "" ["select-instances"]
   (ReqArg (\ f opts -> Ok opts { optSelInst = sepSplit ',' f }) "INSTS")
   "only select given instances for any moves",
   OptComplManyInstances)

oInstMoves :: OptType
oInstMoves =
  (Option "" ["no-instance-moves"]
   (NoArg (\ opts -> Ok opts { optInstMoves = False}))
   "disallow instance (primary node) moves from the list of allowed,\
   \ instance changes, thus allowing only slower, but sometimes\
   \ safer, drbd secondary changes",
   OptComplNone)

oDynuFile :: OptType
oDynuFile =
  (Option "U" ["dynu-file"]
   (ReqArg (\ f opts -> Ok opts { optDynuFile = Just f }) "FILE")
   "Import dynamic utilisation data from the given FILE",
   OptComplFile)

oIgnoreDyn :: OptType
oIgnoreDyn =
  (Option "" ["ignore-dynu"]
   (NoArg (\ opts -> Ok opts {optIgnoreDynu = True}))
   "Ignore any dynamic utilisation information",
   OptComplNone)

oIgnoreSoftErrors :: OptType
oIgnoreSoftErrors =
  (Option "" ["ignore-soft-errors"]
   (NoArg (\ opts -> Ok opts {optIgnoreSoftErrors = True}))
   "Ignore any soft restrictions in balancing",
   OptComplNone)

oIndependentGroups :: OptType
oIndependentGroups =
  (Option "" ["independent-groups"]
   (NoArg (\ opts -> Ok opts {optIndependentGroups = True}))
   "Consider groups independently",
   OptComplNone)

oAcceptExisting :: OptType
oAcceptExisting =
  (Option "" ["accept-existing-errors"]
   (NoArg (\ opts -> Ok opts {optAcceptExisting = True}))
   "Accept existing N+1 violations; just don't add new ones",
   OptComplNone)

oEvacMode :: OptType
oEvacMode =
  (Option "E" ["evac-mode"]
   (NoArg (\opts -> Ok opts { optEvacMode = True }))
   "enable evacuation mode, where the algorithm only moves\
   \ instances away from offline and drained nodes",
   OptComplNone)

oRestrictedMigrate :: OptType
oRestrictedMigrate =
  (Option "" ["restricted-migration"]
   (NoArg (\opts -> Ok opts { optRestrictedMigrate =  True }))
   "disallow replace-primary moves (aka frf-moves); in evacuation mode, this\
   \ will ensure that the only migrations are off the drained nodes",
   OptComplNone)

oExInst :: OptType
oExInst =
  (Option "" ["exclude-instances"]
   (ReqArg (\ f opts -> Ok opts { optExInst = sepSplit ',' f }) "INSTS")
   "exclude given instances from any moves",
   OptComplManyInstances)

oExTags :: OptType
oExTags =
  (Option "" ["exclusion-tags"]
   (ReqArg (\ f opts -> Ok opts { optExTags = Just $ sepSplit ',' f })
    "TAG,...") "Enable instance exclusion based on given tag prefix",
   OptComplString)

oExecJobs :: OptType
oExecJobs =
  (Option "X" ["exec"]
   (NoArg (\ opts -> Ok opts { optExecJobs = True}))
   "execute the suggested moves via Luxi (only available when using\
   \ it for data gathering)",
   OptComplNone)

oDryRun :: OptType
oDryRun =
  (Option "" ["dry-run"]
   (NoArg (\ opts -> Ok opts { optDryRun = True}))
   "do not execute any commands and just report what would be done",
   OptComplNone)

oReason :: OptType
oReason =
  (Option "" ["reason"]
   (ReqArg (\ f opts -> Ok opts { optReason = Just f }) "REASON")
   "The reason to pass to the submitted jobs",
   OptComplNone)

oFirstJobGroup :: OptType
oFirstJobGroup =
  (Option "" ["first-job-group"]
   (NoArg (\ opts -> Ok opts {optFirstJobGroup = True}))
   "only execute the first group of jobs",
   OptComplNone)

oForce :: OptType
oForce =
  (Option "f" ["force"]
   (NoArg (\ opts -> Ok opts {optForce = True}))
   "force the execution of this program, even if warnings would\
   \ otherwise prevent it",
   OptComplNone)

oFullEvacuation :: OptType
oFullEvacuation =
  (Option "" ["full-evacuation"]
   (NoArg (\ opts -> Ok opts { optFullEvacuation = True}))
   "fully evacuate the nodes to be rebooted",
   OptComplNone)

oGroup :: OptType
oGroup =
  (Option "G" ["group"]
   (ReqArg (\ f o -> Ok o { optGroup = Just f }) "ID")
   "the target node group (name or UUID)",
   OptComplOneGroup)

oIAllocSrc :: OptType
oIAllocSrc =
  (Option "I" ["ialloc-src"]
   (ReqArg (\ f opts -> Ok opts { optIAllocSrc = Just f }) "FILE")
   "Specify an iallocator spec as the cluster data source",
   OptComplFile)

oIgnoreNonRedundant :: OptType
oIgnoreNonRedundant =
  (Option "" ["ignore-non-redundant"]
   (NoArg (\ opts -> Ok opts { optIgnoreNonRedundant = True }))
    "Pretend that there are no non-redundant instances in the cluster",
    OptComplNone)

oJobDelay :: OptType
oJobDelay =
  (Option "" ["job-delay"]
   (reqWithConversion (tryRead "job delay")
    (\d opts -> Ok opts { optJobDelay = d }) "SECONDS")
   "insert this much delay before the execution of repair jobs\
   \ to allow the tool to continue processing instances",
   OptComplFloat)

genOLuxiSocket :: String -> OptType
genOLuxiSocket defSocket =
  (Option "L" ["luxi"]
   (OptArg ((\ f opts -> Ok opts { optLuxi = Just f }) .
            fromMaybe defSocket) "SOCKET")
   ("collect data via Luxi, optionally using the given SOCKET path [" ++
    defSocket ++ "]"),
   OptComplFile)

oLuxiSocket :: IO OptType
oLuxiSocket = liftM genOLuxiSocket Path.defaultQuerySocket

oMachineReadable :: OptType
oMachineReadable =
  (Option "" ["machine-readable"]
   (OptArg (\ f opts -> do
              flag <- parseYesNo True f
              return $ opts { optMachineReadable = flag }) "CHOICE")
   "enable machine readable output (pass either 'yes' or 'no' to\
   \ explicitly control the flag, or without an argument defaults to\
   \ yes)",
   optComplYesNo)

oMaxCpu :: OptType
oMaxCpu =
  (Option "" ["max-cpu"]
   (reqWithConversion (tryRead "parsing max-cpu")
    (\mcpu opts -> do
       when (mcpu <= 0) $
            fail "Invalid value of the max-cpu ratio, expected >0"
       return $ opts { optMcpu = Just mcpu }) "RATIO")
   "maximum virtual-to-physical cpu ratio for nodes (from 0\
   \ upwards) [default read from cluster]",
   OptComplFloat)

oMaxSolLength :: OptType
oMaxSolLength =
  (Option "l" ["max-length"]
   (reqWithConversion (tryRead "max solution length")
    (\i opts -> Ok opts { optMaxLength = i }) "N")
   "cap the solution at this many balancing or allocation\
   \ rounds (useful for very unbalanced clusters or empty\
   \ clusters)",
   OptComplInteger)

oMinDisk :: OptType
oMinDisk =
  (Option "" ["min-disk"]
   (reqWithConversion (tryRead "min free disk space")
    (\n opts -> Ok opts { optMdsk = n }) "RATIO")
   "minimum free disk space for nodes (between 0 and 1) [0]",
   OptComplFloat)

oMinGain :: OptType
oMinGain =
  (Option "g" ["min-gain"]
   (reqWithConversion (tryRead "min gain")
    (\g opts -> Ok opts { optMinGain = g }) "DELTA")
   "minimum gain to aim for in a balancing step before giving up",
   OptComplFloat)

oMinGainLim :: OptType
oMinGainLim =
  (Option "" ["min-gain-limit"]
   (reqWithConversion (tryRead "min gain limit")
    (\g opts -> Ok opts { optMinGainLim = g }) "SCORE")
   "minimum cluster score for which we start checking the min-gain",
   OptComplFloat)

oMinResources :: OptType
oMinResources =
  (Option "" ["minimal-resources"]
   (reqWithConversion (tryRead "minimal resources")
    (\d opts -> Ok opts { optMinResources = d}) "FACTOR")
   "minimal resources to be present on each in multiples of\ 
   \ the standard allocation for not onlining standby nodes",
   OptComplFloat)

oMinScore :: OptType
oMinScore =
  (Option "e" ["min-score"]
   (reqWithConversion (tryRead "min score")
    (\e opts -> Ok opts { optMinScore = e }) "EPSILON")
   "mininum excess to the N+1 limit to aim for",
   OptComplFloat)

oNoHeaders :: OptType
oNoHeaders =
  (Option "" ["no-headers"]
   (NoArg (\ opts -> Ok opts { optNoHeaders = True }))
   "do not show a header line",
   OptComplNone)

oNoSimulation :: OptType
oNoSimulation =
  (Option "" ["no-simulation"]
   (NoArg (\opts -> Ok opts {optNoSimulation = True}))
   "do not perform rebalancing simulation",
   OptComplNone)

oNodeSim :: OptType
oNodeSim =
  (Option "" ["simulate"]
   (ReqArg (\ f o -> Ok o { optNodeSim = f:optNodeSim o }) "SPEC")
   "simulate an empty cluster, given as\
   \ 'alloc_policy,num_nodes,disk,ram,cpu'",
   OptComplString)

oNodeTags :: OptType
oNodeTags =
  (Option "" ["node-tags"]
   (ReqArg (\ f opts -> Ok opts { optNodeTags = Just $ sepSplit ',' f })
    "TAG,...") "Restrict to nodes with the given tags",
   OptComplString)
     
oOfflineMaintenance :: OptType
oOfflineMaintenance =
  (Option "" ["offline-maintenance"]
   (NoArg (\ opts -> Ok opts {optOfflineMaintenance = True}))
   "Schedule offline maintenance, i.e., pretend that all instance are\
   \ offline.",
   OptComplNone)

oOfflineNode :: OptType
oOfflineNode =
  (Option "O" ["offline"]
   (ReqArg (\ n o -> Ok o { optOffline = n:optOffline o }) "NODE")
   "set node as offline",
   OptComplOneNode)

oRestrictToNodes :: OptType
oRestrictToNodes =
  (Option "" ["restrict-allocation-to"]
    (ReqArg (\ ns o -> Ok o { optRestrictToNodes = Just $ sepSplit ',' ns })
     "NODE,...") "Restrict allocations to the given set of nodes",
   OptComplManyNodes)

oOneStepOnly :: OptType
oOneStepOnly =
  (Option "" ["one-step-only"]
   (NoArg (\ opts -> Ok opts {optOneStepOnly = True}))
   "Only do the first step",
   OptComplNone)

oOutputDir :: OptType
oOutputDir =
  (Option "d" ["output-dir"]
   (ReqArg (\ d opts -> Ok opts { optOutPath = d }) "PATH")
   "directory in which to write output files",
   OptComplDir)

oPrintCommands :: OptType
oPrintCommands =
  (Option "C" ["print-commands"]
   (OptArg ((\ f opts -> Ok opts { optShowCmds = Just f }) .
            fromMaybe "-")
    "FILE")
   "print the ganeti command list for reaching the solution,\
   \ if an argument is passed then write the commands to a\
   \ file named as such",
   OptComplNone)

oPrintInsts :: OptType
oPrintInsts =
  (Option "" ["print-instances"]
   (NoArg (\ opts -> Ok opts { optShowInsts = True }))
   "print the final instance map",
   OptComplNone)

oPrintMoves :: OptType
oPrintMoves =
  (Option "" ["print-moves"]
   (NoArg (\ opts -> Ok opts { optPrintMoves = True }))
   "print the moves of the instances",
   OptComplNone)

oPrintNodes :: OptType
oPrintNodes =
  (Option "p" ["print-nodes"]
   (OptArg ((\ f opts ->
               let (prefix, realf) = case f of
                                       '+':rest -> (["+"], rest)
                                       _ -> ([], f)
                   splitted = prefix ++ sepSplit ',' realf
               in Ok opts { optShowNodes = Just splitted }) .
            fromMaybe []) "FIELDS")
   "print the final node list",
   OptComplNone)

oQuiet :: OptType
oQuiet =
  (Option "q" ["quiet"]
   (NoArg (\ opts -> Ok opts { optVerbose = optVerbose opts - 1 }))
   "decrease the verbosity level",
   OptComplNone)

oRapiMaster :: OptType
oRapiMaster =
  (Option "m" ["master"]
   (ReqArg (\ m opts -> Ok opts { optMaster = m }) "ADDRESS")
   "collect data via RAPI at the given ADDRESS",
   OptComplHost)

oSaveCluster :: OptType
oSaveCluster =
  (Option "S" ["save"]
   (ReqArg (\ f opts -> Ok opts { optSaveCluster = Just f }) "FILE")
   "Save cluster state at the end of the processing to FILE",
   OptComplNone)

oSkipNonRedundant :: OptType
oSkipNonRedundant =
  (Option "" ["skip-non-redundant"]
   (NoArg (\ opts -> Ok opts { optSkipNonRedundant = True }))
    "Skip nodes that host a non-redundant instance",
    OptComplNone)

oStdSpec :: OptType
oStdSpec =
  (Option "" ["standard-alloc"]
   (ReqArg (\ inp opts -> do
              tspec <- parseISpecString "standard" inp
              return $ opts { optStdSpec = Just tspec } )
    "STDSPEC")
   "enable standard specs allocation, given as 'disk,ram,cpu'",
   OptComplString)

oTargetResources :: OptType
oTargetResources =
  (Option "" ["target-resources"]
   (reqWithConversion (tryRead "target resources")
    (\d opts -> Ok opts { optTargetResources = d}) "FACTOR")
   "target resources to be left on each node after squeezing in\
   \ multiples of the standard allocation",
   OptComplFloat)

oTieredSpec :: OptType
oTieredSpec =
  (Option "" ["tiered-alloc"]
   (ReqArg (\ inp opts -> do
              tspec <- parseISpecString "tiered" inp
              return $ opts { optTieredSpec = Just tspec } )
    "TSPEC")
   "enable tiered specs allocation, given as 'disk,ram,cpu'",
   OptComplString)

oVerbose :: OptType
oVerbose =
  (Option "v" ["verbose"]
   (NoArg (\ opts -> Ok opts { optVerbose = optVerbose opts + 1 }))
   "increase the verbosity level",
   OptComplNone)

oPriority :: OptType
oPriority =
  (Option "" ["priority"]
   (ReqArg (\ inp opts -> do
              prio <- parseSubmitPriority inp
              Ok opts { optPriority = Just prio }) "PRIO")
   "set the priority of submitted jobs",
    OptComplChoices (map fmtSubmitPriority [minBound..maxBound]))

oNoCapacityChecks :: OptType
oNoCapacityChecks =
  (Option "" ["no-capacity-checks"]
   (NoArg (\ opts -> Ok opts { optCapacity = False}))
   "disable capacity checks (like global N+1 redundancy)",
   OptComplNone)

-- | Generic options.
genericOpts :: [GenericOptType Options]
genericOpts =  [ oShowVer
               , oShowHelp
               , oShowComp
               ]

-- * Functions

-- | Wrapper over 'Common.parseOpts' with our custom options.
parseOpts :: [String]               -- ^ The command line arguments
          -> String                 -- ^ The program name
          -> [OptType]              -- ^ The supported command line options
          -> [ArgCompletion]        -- ^ The supported command line arguments
          -> IO (Options, [String]) -- ^ The resulting options and leftover
                                    -- arguments
parseOpts = Common.parseOpts defaultOptions


-- | A shell script template for autogenerated scripts.
shTemplate :: String
shTemplate =
  printf "#!/bin/sh\n\n\
         \# Auto-generated script for executing cluster rebalancing\n\n\
         \# To stop, touch the file /tmp/stop-htools\n\n\
         \set -e\n\n\
         \check() {\n\
         \  if [ -f /tmp/stop-htools ]; then\n\
         \    echo 'Stop requested, exiting'\n\
         \    exit 0\n\
         \  fi\n\
         \}\n\n"

-- | Optionally show or save a list of commands
maybeSaveCommands :: String -- ^ Informal description
                  -> Options
                  -> String -- ^ commands
                  -> IO ()
maybeSaveCommands msg opts cmds =
  case optShowCmds opts of
    Nothing -> return ()
    Just "-" -> do
      putStrLn ""
      putStrLn msg
      putStr . unlines .  map ("  " ++) . filter (/= "  check") . lines $ cmds
    Just out_path -> do
      writeFile out_path (shTemplate ++ cmds)
      printf "The commands have been written to file '%s'\n" out_path

-- | Optionally print the node list.
maybePrintNodes :: Maybe [String]       -- ^ The field list
                -> String               -- ^ Informational message
                -> ([String] -> String) -- ^ Function to generate the listing
                -> IO ()
maybePrintNodes Nothing _ _ = return ()
maybePrintNodes (Just fields) msg fn = do
  hPutStrLn stderr ""
  hPutStrLn stderr (msg ++ " status:")
  hPutStrLn stderr $ fn fields

-- | Optionally print the instance list.
maybePrintInsts :: Bool   -- ^ Whether to print the instance list
                -> String -- ^ Type of the instance map (e.g. initial)
                -> String -- ^ The instance data
                -> IO ()
maybePrintInsts do_print msg instdata =
  when do_print $ do
    hPutStrLn stderr ""
    hPutStrLn stderr $ msg ++ " instance map:"
    hPutStr stderr instdata

-- | Function to display warning messages from parsing the cluster
-- state.
maybeShowWarnings :: [String] -- ^ The warning messages
                  -> IO ()
maybeShowWarnings fix_msgs =
  unless (null fix_msgs) $ do
    hPutStrLn stderr "Warning: cluster has inconsistent data:"
    hPutStrLn stderr . unlines . map (printf "  - %s") $ fix_msgs

-- | Format a list of key, value as a shell fragment.
printKeys :: String              -- ^ Prefix to printed variables
          -> [(String, String)]  -- ^ List of (key, value) pairs to be printed
          -> IO ()
printKeys prefix =
  mapM_ (\(k, v) ->
           printf "%s_%s=%s\n" prefix (map toUpper k) (ensureQuoted v))

-- | Prints the final @OK@ marker in machine readable output.
printFinal :: String    -- ^ Prefix to printed variable
           -> Bool      -- ^ Whether output should be machine readable;
                        -- note: if not, there is nothing to print
           -> IO ()
printFinal prefix True =
  -- this should be the final entry
  printKeys prefix [("OK", "1")]

printFinal _ False = return ()

-- | Potentially set the node as offline based on passed offline list.
setNodeOffline :: [Ndx] -> Node.Node -> Node.Node
setNodeOffline offline_indices n =
  if Node.idx n `elem` offline_indices
    then Node.setOffline n True
    else n

-- | Set node properties based on command line options.
setNodeStatus :: Options -> Node.List -> IO Node.List
setNodeStatus opts fixed_nl = do
  let offline_passed = optOffline opts
      all_nodes = Container.elems fixed_nl
      offline_lkp = map (lookupName (map Node.name all_nodes)) offline_passed
      offline_wrong = filter (not . goodLookupResult) offline_lkp
      offline_names = map lrContent offline_lkp
      offline_indices = map Node.idx $
                        filter (\n -> Node.name n `elem` offline_names)
                               all_nodes
      m_cpu = optMcpu opts
      m_dsk = optMdsk opts

  unless (null offline_wrong) .
         exitErr $ printf "wrong node name(s) set as offline: %s\n"
                   (commaJoin (map lrContent offline_wrong))
  let setMCpuFn = case m_cpu of
                    Nothing -> id
                    Just new_mcpu -> flip Node.setMcpu new_mcpu
  let nm = Container.map (setNodeOffline offline_indices .
                          flip Node.setMdsk m_dsk .
                          setMCpuFn) fixed_nl
  return nm

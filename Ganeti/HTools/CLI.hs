{-| Implementation of command-line functions.

This module holds the common cli-related functions for the binaries,
separated into this module since Utils.hs is used in many other places
and this is more IO oriented.

-}

{-

Copyright (C) 2009 Google Inc.

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

module Ganeti.HTools.CLI
    ( Options(..)
    , OptType
    , parseOpts
    , shTemplate
    -- * The options
    , oPrintNodes
    , oPrintInsts
    , oPrintCommands
    , oOneline
    , oNoHeaders
    , oOutputDir
    , oNodeFile
    , oInstFile
    , oNodeSim
    , oRapiMaster
    , oLuxiSocket
    , oExecJobs
    , oMaxSolLength
    , oVerbose
    , oQuiet
    , oOfflineNode
    , oMinScore
    , oIMem
    , oIDisk
    , oIVcpus
    , oINodes
    , oMaxCpu
    , oMinDisk
    , oDiskMoves
    , oDynuFile
    , oTieredSpec
    , oExTags
    , oShowVer
    , oShowHelp
    ) where

import Data.Maybe (fromMaybe)
import qualified Data.Version
import Monad
import System.Console.GetOpt
import System.IO
import System.Info
import System
import Text.Printf (printf)

import qualified Ganeti.HTools.Version as Version(version)
import Ganeti.HTools.Types
import Ganeti.HTools.Utils

-- | The default value for the luxi socket
defaultLuxiSocket :: FilePath
defaultLuxiSocket = "/var/run/ganeti/socket/ganeti-master"

-- | Command line options structure.
data Options = Options
    { optShowNodes   :: Maybe [String] -- ^ Whether to show node status
    , optShowInsts   :: Bool           -- ^ Whether to show the instance map
    , optShowCmds    :: Maybe FilePath -- ^ Whether to show the command list
    , optOneline     :: Bool           -- ^ Switch output to a single line
    , optOutPath     :: FilePath       -- ^ Path to the output directory
    , optNoHeaders   :: Bool           -- ^ Do not show a header line
    , optNodeFile    :: FilePath       -- ^ Path to the nodes file
    , optNodeSet     :: Bool           -- ^ The nodes have been set by options
    , optInstFile    :: FilePath       -- ^ Path to the instances file
    , optInstSet     :: Bool           -- ^ The insts have been set by options
    , optNodeSim     :: Maybe String   -- ^ Cluster simulation mode
    , optMaxLength   :: Int            -- ^ Stop after this many steps
    , optMaster      :: String         -- ^ Collect data from RAPI
    , optLuxi        :: Maybe FilePath -- ^ Collect data from Luxi
    , optExecJobs    :: Bool           -- ^ Execute the commands via Luxi
    , optOffline     :: [String]       -- ^ Names of offline nodes
    , optINodes      :: Int            -- ^ Nodes required for an instance
    , optISpec       :: RSpec          -- ^ Requested instance specs
    , optTieredSpec  :: Maybe RSpec    -- ^ Requested specs for tiered mode
    , optMinScore    :: Score          -- ^ The minimum score we aim for
    , optMcpu        :: Double         -- ^ Max cpu ratio for nodes
    , optMdsk        :: Double         -- ^ Max disk usage ratio for nodes
    , optDiskMoves   :: Bool           -- ^ Allow disk moves
    , optDynuFile    :: Maybe FilePath -- ^ Optional file with dynamic use data
    , optExTags      :: Maybe [String] -- ^ Tags to use for exclusion
    , optVerbose     :: Int            -- ^ Verbosity level
    , optShowVer     :: Bool           -- ^ Just show the program version
    , optShowHelp    :: Bool           -- ^ Just show the help
    } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowNodes   = Nothing
 , optShowInsts   = False
 , optShowCmds    = Nothing
 , optOneline     = False
 , optNoHeaders   = False
 , optOutPath     = "."
 , optNodeFile    = "nodes"
 , optNodeSet     = False
 , optInstFile    = "instances"
 , optInstSet     = False
 , optNodeSim     = Nothing
 , optMaxLength   = -1
 , optMaster      = ""
 , optLuxi        = Nothing
 , optExecJobs    = False
 , optOffline     = []
 , optINodes      = 2
 , optISpec       = RSpec 1 4096 102400
 , optTieredSpec  = Nothing
 , optMinScore    = 1e-9
 , optMcpu        = -1
 , optMdsk        = -1
 , optDiskMoves   = True
 , optDynuFile    = Nothing
 , optExTags      = Nothing
 , optVerbose     = 1
 , optShowVer     = False
 , optShowHelp    = False
 }

-- | Abrreviation for the option type
type OptType = OptDescr (Options -> Result Options)

oPrintNodes :: OptType
oPrintNodes = Option "p" ["print-nodes"]
              (OptArg ((\ f opts ->
                            let splitted = sepSplit ',' f
                            in Ok opts { optShowNodes = Just splitted }) .
                       fromMaybe []) "FIELDS")
              "print the final node list"

oPrintInsts :: OptType
oPrintInsts = Option "" ["print-instances"]
              (NoArg (\ opts -> Ok opts { optShowInsts = True }))
              "print the final instance map"

oPrintCommands :: OptType
oPrintCommands = Option "C" ["print-commands"]
                 (OptArg ((\ f opts -> Ok opts { optShowCmds = Just f }) .
                          fromMaybe "-")
                  "FILE")
                 "print the ganeti command list for reaching the solution,\
                 \ if an argument is passed then write the commands to a\
                 \ file named as such"

oOneline :: OptType
oOneline = Option "o" ["oneline"]
           (NoArg (\ opts -> Ok opts { optOneline = True }))
           "print the ganeti command list for reaching the solution"

oNoHeaders :: OptType
oNoHeaders = Option "" ["no-headers"]
             (NoArg (\ opts -> Ok opts { optNoHeaders = True }))
             "do not show a header line"

oOutputDir :: OptType
oOutputDir = Option "d" ["output-dir"]
             (ReqArg (\ d opts -> Ok opts { optOutPath = d }) "PATH")
             "directory in which to write output files"

oNodeFile :: OptType
oNodeFile = Option "n" ["nodes"]
            (ReqArg (\ f o -> Ok o { optNodeFile = f,
                                     optNodeSet = True }) "FILE")
            "the node list FILE"

oInstFile :: OptType
oInstFile = Option "i" ["instances"]
            (ReqArg (\ f o -> Ok o { optInstFile = f,
                                     optInstSet = True }) "FILE")
            "the instance list FILE"

oNodeSim :: OptType
oNodeSim = Option "" ["simulate"]
            (ReqArg (\ f o -> Ok o { optNodeSim = Just f }) "SPEC")
            "simulate an empty cluster, given as 'num_nodes,disk,ram,cpu'"

oRapiMaster :: OptType
oRapiMaster = Option "m" ["master"]
              (ReqArg (\ m opts -> Ok opts { optMaster = m }) "ADDRESS")
              "collect data via RAPI at the given ADDRESS"

oLuxiSocket :: OptType
oLuxiSocket = Option "L" ["luxi"]
              (OptArg ((\ f opts -> Ok opts { optLuxi = Just f }) .
                       fromMaybe defaultLuxiSocket) "SOCKET")
              "collect data via Luxi, optionally using the given SOCKET path"

oExecJobs :: OptType
oExecJobs = Option "X" ["exec"]
             (NoArg (\ opts -> Ok opts { optExecJobs = True}))
             "execute the suggested moves via Luxi (only available when using\
             \ it for data gathering"

oVerbose :: OptType
oVerbose = Option "v" ["verbose"]
           (NoArg (\ opts -> Ok opts { optVerbose = optVerbose opts + 1 }))
           "increase the verbosity level"

oQuiet :: OptType
oQuiet = Option "q" ["quiet"]
         (NoArg (\ opts -> Ok opts { optVerbose = optVerbose opts - 1 }))
         "decrease the verbosity level"

oOfflineNode :: OptType
oOfflineNode = Option "O" ["offline"]
               (ReqArg (\ n o -> Ok o { optOffline = n:optOffline o }) "NODE")
               "set node as offline"

oMaxSolLength :: OptType
oMaxSolLength = Option "l" ["max-length"]
                (ReqArg (\ i opts -> Ok opts { optMaxLength = read i }) "N")
                "cap the solution at this many moves (useful for very\
                \ unbalanced clusters)"

oMinScore :: OptType
oMinScore = Option "e" ["min-score"]
            (ReqArg (\ e opts -> Ok opts { optMinScore = read e }) "EPSILON")
            " mininum score to aim for"

oIMem :: OptType
oIMem = Option "" ["memory"]
        (ReqArg (\ m opts ->
                     let ospec = optISpec opts
                         nspec = ospec { rspecMem = read m }
                     in Ok opts { optISpec = nspec }) "MEMORY")
        "memory size for instances"

oIDisk :: OptType
oIDisk = Option "" ["disk"]
         (ReqArg (\ d opts ->
                     let ospec = optISpec opts
                         nspec = ospec { rspecDsk = read d }
                     in Ok opts { optISpec = nspec }) "DISK")
         "disk size for instances"

oIVcpus :: OptType
oIVcpus = Option "" ["vcpus"]
          (ReqArg (\ p opts ->
                       let ospec = optISpec opts
                           nspec = ospec { rspecCpu = read p }
                       in Ok opts { optISpec = nspec }) "NUM")
          "number of virtual cpus for instances"

oINodes :: OptType
oINodes = Option "" ["req-nodes"]
          (ReqArg (\ n opts -> Ok opts { optINodes = read n }) "NODES")
          "number of nodes for the new instances (1=plain, 2=mirrored)"

oMaxCpu :: OptType
oMaxCpu = Option "" ["max-cpu"]
          (ReqArg (\ n opts -> Ok opts { optMcpu = read n }) "RATIO")
          "maximum virtual-to-physical cpu ratio for nodes"

oMinDisk :: OptType
oMinDisk = Option "" ["min-disk"]
           (ReqArg (\ n opts -> Ok opts { optMdsk = read n }) "RATIO")
           "minimum free disk space for nodes (between 0 and 1)"

oDiskMoves :: OptType
oDiskMoves = Option "" ["no-disk-moves"]
             (NoArg (\ opts -> Ok opts { optDiskMoves = False}))
             "disallow disk moves from the list of allowed instance changes,\
             \ thus allowing only the 'cheap' failover/migrate operations"

oDynuFile :: OptType
oDynuFile = Option "U" ["dynu-file"]
            (ReqArg (\ f opts -> Ok opts { optDynuFile = Just f }) "FILE")
            "Import dynamic utilisation data from the given FILE"

oExTags :: OptType
oExTags = Option "" ["exclusion-tags"]
            (ReqArg (\ f opts -> Ok opts { optExTags = Just $ sepSplit ',' f })
             "TAG,...") "Enable instance exclusion based on given tag prefix"

oTieredSpec :: OptType
oTieredSpec = Option "" ["tiered-alloc"]
             (ReqArg (\ inp opts -> do
                          let sp = sepSplit ',' inp
                          prs <- mapM (tryRead "tiered specs") sp
                          tspec <-
                              case prs of
                                [dsk, ram, cpu] -> return $ RSpec cpu ram dsk
                                _ -> Bad $ "Invalid specification: " ++ inp
                          return $ opts { optTieredSpec = Just tspec } )
              "TSPEC")
             "enable tiered specs allocation, given as 'disk,ram,cpu'"

oShowVer :: OptType
oShowVer = Option "V" ["version"]
           (NoArg (\ opts -> Ok opts { optShowVer = True}))
           "show the version of the program"

oShowHelp :: OptType
oShowHelp = Option "h" ["help"]
            (NoArg (\ opts -> Ok opts { optShowHelp = True}))
            "show help"

-- | Usage info
usageHelp :: String -> [OptType] -> String
usageHelp progname =
    usageInfo (printf "%s %s\nUsage: %s [OPTION...]"
               progname Version.version progname)

-- | Command line parser, using the 'options' structure.
parseOpts :: [String]               -- ^ The command line arguments
          -> String                 -- ^ The program name
          -> [OptType]              -- ^ The supported command line options
          -> IO (Options, [String]) -- ^ The resulting options and leftover
                                    -- arguments
parseOpts argv progname options =
    case getOpt Permute options argv of
      (o, n, []) ->
          do
            let (pr, args) = (foldM (flip id) defaultOptions o, n)
            po <- (case pr of
                     Bad msg -> do
                       hPutStrLn stderr "Error while parsing command\
                                        \line arguments:"
                       hPutStrLn stderr msg
                       exitWith $ ExitFailure 1
                     Ok val -> return val)
            when (optShowHelp po) $ do
              putStr $ usageHelp progname options
              exitWith ExitSuccess
            when (optShowVer po) $ do
              printf "%s %s\ncompiled with %s %s\nrunning on %s %s\n"
                     progname Version.version
                     compilerName (Data.Version.showVersion compilerVersion)
                     os arch
              exitWith ExitSuccess
            return (po, args)
      (_, _, errs) -> do
        hPutStrLn stderr $ "Command line error: "  ++ concat errs
        hPutStrLn stderr $ usageHelp progname options
        exitWith $ ExitFailure 2

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

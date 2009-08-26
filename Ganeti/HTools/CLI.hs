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
    , parseEnv
    , shTemplate
    , loadExternalData
    , defaultLuxiSocket
    -- * The options
    , oPrintNodes
    , oPrintCommands
    , oOneline
    , oNoHeaders
    , oOutputDir
    , oNodeFile
    , oInstFile
    , oNodeSim
    , oRapiMaster
    , oLuxiSocket
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
    , oShowVer
    , oShowHelp
    ) where

import Control.Exception
import Data.Maybe (isJust, fromJust, fromMaybe)
import qualified Data.Version
import Monad
import System.Console.GetOpt
import System.Posix.Env
import System.IO
import System.Info
import System
import Text.Printf (printf, hPrintf)

import qualified Ganeti.HTools.Version as Version(version)
import qualified Ganeti.HTools.Luxi as Luxi
import qualified Ganeti.HTools.Rapi as Rapi
import qualified Ganeti.HTools.Simu as Simu
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Cluster as Cluster

import Ganeti.HTools.Types

-- | The default value for the luxi socket
defaultLuxiSocket :: FilePath
defaultLuxiSocket = "/var/run/ganeti/socket/ganeti-master"

-- | Command line options structure.
data Options = Options
    { optShowNodes :: Bool           -- ^ Whether to show node status
    , optShowCmds  :: Maybe FilePath -- ^ Whether to show the command list
    , optOneline   :: Bool           -- ^ Switch output to a single line
    , optOutPath   :: FilePath       -- ^ Path to the output directory
    , optNoHeaders :: Bool           -- ^ Do not show a header line
    , optNodeFile  :: FilePath       -- ^ Path to the nodes file
    , optNodeSet   :: Bool           -- ^ The nodes have been set by options
    , optInstFile  :: FilePath       -- ^ Path to the instances file
    , optInstSet   :: Bool           -- ^ The insts have been set by options
    , optNodeSim   :: Maybe String   -- ^ Cluster simulation mode
    , optMaxLength :: Int            -- ^ Stop after this many steps
    , optMaster    :: String         -- ^ Collect data from RAPI
    , optLuxi      :: Maybe FilePath -- ^ Collect data from Luxi
    , optOffline   :: [String]       -- ^ Names of offline nodes
    , optIMem      :: Int            -- ^ Instance memory
    , optIDsk      :: Int            -- ^ Instance disk
    , optIVCPUs    :: Int            -- ^ Instance VCPUs
    , optINodes    :: Int            -- ^ Nodes required for an instance
    , optMinScore  :: Cluster.Score  -- ^ The minimum score we aim for
    , optMcpu      :: Double         -- ^ Max cpu ratio for nodes
    , optMdsk      :: Double         -- ^ Max disk usage ratio for nodes
    , optDiskMoves :: Bool           -- ^ Allow disk moves
    , optVerbose   :: Int            -- ^ Verbosity level
    , optShowVer   :: Bool           -- ^ Just show the program version
    , optShowHelp  :: Bool           -- ^ Just show the help
    } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowNodes = False
 , optShowCmds  = Nothing
 , optOneline   = False
 , optNoHeaders = False
 , optOutPath   = "."
 , optNodeFile  = "nodes"
 , optNodeSet   = False
 , optInstFile  = "instances"
 , optInstSet   = False
 , optNodeSim   = Nothing
 , optMaxLength = -1
 , optMaster    = ""
 , optLuxi      = Nothing
 , optOffline   = []
 , optIMem      = 4096
 , optIDsk      = 102400
 , optIVCPUs    = 1
 , optINodes    = 2
 , optMinScore  = 1e-9
 , optMcpu      = -1
 , optMdsk      = -1
 , optDiskMoves = True
 , optVerbose   = 1
 , optShowVer   = False
 , optShowHelp  = False
 }

-- | Abrreviation for the option type
type OptType = OptDescr (Options -> Options)

oPrintNodes :: OptType
oPrintNodes = Option "p" ["print-nodes"]
              (NoArg (\ opts -> opts { optShowNodes = True }))
              "print the final node list"

oPrintCommands :: OptType
oPrintCommands = Option "C" ["print-commands"]
                 (OptArg ((\ f opts -> opts { optShowCmds = Just f }) .
                          fromMaybe "-")
                  "FILE")
                 "print the ganeti command list for reaching the solution,\
                 \ if an argument is passed then write the commands to a\
                 \ file named as such"

oOneline :: OptType
oOneline = Option "o" ["oneline"]
           (NoArg (\ opts -> opts { optOneline = True }))
           "print the ganeti command list for reaching the solution"

oNoHeaders :: OptType
oNoHeaders = Option "" ["no-headers"]
             (NoArg (\ opts -> opts { optNoHeaders = True }))
             "do not show a header line"

oOutputDir :: OptType
oOutputDir = Option "d" ["output-dir"]
             (ReqArg (\ d opts -> opts { optOutPath = d }) "PATH")
             "directory in which to write output files"

oNodeFile :: OptType
oNodeFile = Option "n" ["nodes"]
            (ReqArg (\ f o -> o { optNodeFile = f, optNodeSet = True }) "FILE")
            "the node list FILE"

oInstFile :: OptType
oInstFile = Option "i" ["instances"]
            (ReqArg (\ f o -> o { optInstFile = f, optInstSet = True }) "FILE")
            "the instance list FILE"

oNodeSim :: OptType
oNodeSim = Option "" ["simulate"]
            (ReqArg (\ f o -> o { optNodeSim = Just f }) "SPEC")
            "simulate an empty cluster, given as 'num_nodes,disk,memory,cpus'"

oRapiMaster :: OptType
oRapiMaster = Option "m" ["master"]
              (ReqArg (\ m opts -> opts { optMaster = m }) "ADDRESS")
              "collect data via RAPI at the given ADDRESS"

oLuxiSocket :: OptType
oLuxiSocket = Option "L" ["luxi"]
              (OptArg ((\ f opts -> opts { optLuxi = Just f }) .
                       fromMaybe defaultLuxiSocket) "SOCKET")
              "collect data via Luxi, optionally using the given SOCKET path"

oVerbose :: OptType
oVerbose = Option "v" ["verbose"]
           (NoArg (\ opts -> opts { optVerbose = optVerbose opts + 1 }))
           "increase the verbosity level"

oQuiet :: OptType
oQuiet = Option "q" ["quiet"]
         (NoArg (\ opts -> opts { optVerbose = optVerbose opts - 1 }))
         "decrease the verbosity level"

oOfflineNode :: OptType
oOfflineNode = Option "O" ["offline"]
               (ReqArg (\ n o -> o { optOffline = n:optOffline o }) "NODE")
               "set node as offline"

oMaxSolLength :: OptType
oMaxSolLength = Option "l" ["max-length"]
                (ReqArg (\ i opts -> opts { optMaxLength =  read i::Int }) "N")
                "cap the solution at this many moves (useful for very\
                \ unbalanced clusters)"

oMinScore :: OptType
oMinScore = Option "e" ["min-score"]
            (ReqArg (\ e opts -> opts { optMinScore = read e }) "EPSILON")
            " mininum score to aim for"

oIMem :: OptType
oIMem = Option "" ["memory"]
        (ReqArg (\ m opts -> opts { optIMem = read m }) "MEMORY")
        "memory size for instances"

oIDisk :: OptType
oIDisk = Option "" ["disk"]
         (ReqArg (\ d opts -> opts { optIDsk = read d }) "DISK")
         "disk size for instances"

oIVcpus :: OptType
oIVcpus = Option "" ["vcpus"]
          (ReqArg (\ p opts -> opts { optIVCPUs = read p }) "NUM")
          "number of virtual cpus for instances"

oINodes :: OptType
oINodes = Option "" ["req-nodes"]
          (ReqArg (\ n opts -> opts { optINodes = read n }) "NODES")
          "number of nodes for the new instances (1=plain, 2=mirrored)"

oMaxCpu :: OptType
oMaxCpu = Option "" ["max-cpu"]
          (ReqArg (\ n opts -> opts { optMcpu = read n }) "RATIO")
          "maximum virtual-to-physical cpu ratio for nodes"

oMinDisk :: OptType
oMinDisk = Option "" ["min-disk"]
           (ReqArg (\ n opts -> opts { optMdsk = read n }) "RATIO")
           "minimum free disk space for nodes (between 0 and 1)"

oDiskMoves :: OptType
oDiskMoves = Option "" ["no-disk-moves"]
             (NoArg (\ opts -> opts { optDiskMoves = False}))
             "disallow disk moves from the list of allowed instance changes,\
             \ thus allowing only the 'cheap' failover/migrate operations"

oShowVer :: OptType
oShowVer = Option "V" ["version"]
           (NoArg (\ opts -> opts { optShowVer = True}))
           "show the version of the program"

oShowHelp :: OptType
oShowHelp = Option "h" ["help"]
            (NoArg (\ opts -> opts { optShowHelp = True}))
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
            let resu@(po, _) = (foldl (flip id) defaultOptions o, n)
            when (optShowHelp po) $ do
              putStr $ usageHelp progname options
              exitWith ExitSuccess
            when (optShowVer po) $ do
              printf "%s %s\ncompiled with %s %s\nrunning on %s %s\n"
                     progname Version.version
                     compilerName (Data.Version.showVersion compilerVersion)
                     os arch
              exitWith ExitSuccess
            return resu
      (_, _, errs) -> do
        hPutStrLn stderr $ "Command line error: "  ++ concat errs
        hPutStrLn stderr $ usageHelp progname options
        exitWith $ ExitFailure 2

-- | Parse the environment and return the node\/instance names.
--
-- This also hardcodes here the default node\/instance file names.
parseEnv :: () -> IO (String, String)
parseEnv () = do
  a <- getEnvDefault "HTOOLS_NODES" "nodes"
  b <- getEnvDefault "HTOOLS_INSTANCES" "instances"
  return (a, b)

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

-- | Error beautifier
wrapIO :: IO (Result a) -> IO (Result a)
wrapIO = handle (return . Bad . show)

-- | External tool data loader from a variety of sources.
loadExternalData :: Options
                 -> IO (Node.List, Instance.List, String)
loadExternalData opts = do
  (env_node, env_inst) <- parseEnv ()
  let nodef = if optNodeSet opts then optNodeFile opts
              else env_node
      instf = if optInstSet opts then optInstFile opts
              else env_inst
      mhost = optMaster opts
      lsock = optLuxi opts
      simdata = optNodeSim opts
      setRapi = mhost /= ""
      setLuxi = isJust lsock
      setSim = isJust simdata
      setFiles = optNodeSet opts || optInstSet opts
      allSet = filter id [setRapi, setLuxi, setFiles]
  when (length allSet > 1) $
       do
         hPutStrLn stderr "Error: Only one of the rapi, luxi, and data\
                          \ files options should be given."
         exitWith $ ExitFailure 1

  input_data <-
      case () of
        _ | setRapi -> wrapIO $ Rapi.loadData mhost
          | setLuxi -> wrapIO $ Luxi.loadData $ fromJust lsock
          | setSim -> Simu.loadData $ fromJust simdata
          | otherwise -> wrapIO $ Text.loadData nodef instf

  let ldresult = input_data >>= Loader.mergeData
  (loaded_nl, il, csf) <-
      (case ldresult of
         Ok x -> return x
         Bad s -> do
           hPrintf stderr "Error: failed to load data. Details:\n%s\n" s
           exitWith $ ExitFailure 1
      )
  let (fix_msgs, fixed_nl) = Loader.checkData loaded_nl il

  unless (null fix_msgs || optVerbose opts == 0) $ do
         hPutStrLn stderr "Warning: cluster has inconsistent data:"
         hPutStrLn stderr . unlines . map (printf "  - %s") $ fix_msgs

  return (fixed_nl, il, csf)

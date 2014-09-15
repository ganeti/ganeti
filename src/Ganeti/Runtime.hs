{-| Implementation of the runtime configuration details.

-}

{-

Copyright (C) 2011, 2012, 2013, 2014 Google Inc.
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

module Ganeti.Runtime
  ( GanetiDaemon(..)
  , MiscGroup(..)
  , GanetiGroup(..)
  , RuntimeEnts(..)
  , daemonName
  , daemonOnlyOnMaster
  , daemonLogBase
  , daemonUser
  , daemonGroup
  , ExtraLogReason(..)
  , daemonLogFile
  , daemonsExtraLogbase
  , daemonsExtraLogFile
  , daemonPidFile
  , getEnts
  , verifyDaemonUser
  ) where

import Control.Monad
import Control.Monad.Error
import qualified Data.Map as M
import System.Exit
import System.FilePath
import System.IO
import System.Posix.Types
import System.Posix.User
import Text.Printf

import qualified Ganeti.ConstantUtils as ConstantUtils
import qualified Ganeti.Path as Path
import Ganeti.BasicTypes

import AutoConf

data GanetiDaemon = GanetiMasterd
                  | GanetiMetad
                  | GanetiNoded
                  | GanetiRapi
                  | GanetiConfd
                  | GanetiWConfd
                  | GanetiKvmd
                  | GanetiLuxid
                  | GanetiMond
                    deriving (Show, Enum, Bounded, Eq, Ord)

data MiscGroup = DaemonsGroup
               | AdminGroup
                 deriving (Show, Enum, Bounded, Eq, Ord)

data GanetiGroup = DaemonGroup GanetiDaemon
                 | ExtraGroup MiscGroup
                   deriving (Show, Eq, Ord)

data RuntimeEnts = RuntimeEnts
  { reUserToUid :: M.Map GanetiDaemon UserID
  , reUidToUser :: M.Map UserID String
  , reGroupToGid :: M.Map GanetiGroup GroupID
  , reGidToGroup :: M.Map GroupID String
  }

-- | Returns the daemon name for a given daemon.
daemonName :: GanetiDaemon -> String
daemonName GanetiMasterd = "ganeti-masterd"
daemonName GanetiMetad   = "ganeti-metad"
daemonName GanetiNoded   = "ganeti-noded"
daemonName GanetiRapi    = "ganeti-rapi"
daemonName GanetiConfd   = "ganeti-confd"
daemonName GanetiWConfd  = "ganeti-wconfd"
daemonName GanetiKvmd    = "ganeti-kvmd"
daemonName GanetiLuxid   = "ganeti-luxid"
daemonName GanetiMond    = "ganeti-mond"

-- | Returns whether the daemon only runs on the master node.
daemonOnlyOnMaster :: GanetiDaemon -> Bool
daemonOnlyOnMaster GanetiMasterd = True
daemonOnlyOnMaster GanetiMetad   = False
daemonOnlyOnMaster GanetiNoded   = False
daemonOnlyOnMaster GanetiRapi    = False
daemonOnlyOnMaster GanetiConfd   = False
daemonOnlyOnMaster GanetiWConfd  = True
daemonOnlyOnMaster GanetiKvmd    = False
daemonOnlyOnMaster GanetiLuxid   = True
daemonOnlyOnMaster GanetiMond    = False

-- | Returns the log file base for a daemon.
daemonLogBase :: GanetiDaemon -> String
daemonLogBase GanetiMasterd = "master-daemon"
daemonLogBase GanetiMetad   = "meta-daemon"
daemonLogBase GanetiNoded   = "node-daemon"
daemonLogBase GanetiRapi    = "rapi-daemon"
daemonLogBase GanetiConfd   = "conf-daemon"
daemonLogBase GanetiWConfd  = "wconf-daemon"
daemonLogBase GanetiKvmd    = "kvm-daemon"
daemonLogBase GanetiLuxid   = "luxi-daemon"
daemonLogBase GanetiMond    = "monitoring-daemon"

-- | Returns the configured user name for a daemon.
daemonUser :: GanetiDaemon -> String
daemonUser GanetiMasterd = AutoConf.masterdUser
daemonUser GanetiMetad   = AutoConf.metadUser
daemonUser GanetiNoded   = AutoConf.nodedUser
daemonUser GanetiRapi    = AutoConf.rapiUser
daemonUser GanetiConfd   = AutoConf.confdUser
daemonUser GanetiWConfd  = AutoConf.wconfdUser
daemonUser GanetiKvmd    = AutoConf.kvmdUser
daemonUser GanetiLuxid   = AutoConf.luxidUser
daemonUser GanetiMond    = AutoConf.mondUser

-- | Returns the configured group for a daemon.
daemonGroup :: GanetiGroup -> String
daemonGroup (DaemonGroup GanetiMasterd) = AutoConf.masterdGroup
daemonGroup (DaemonGroup GanetiMetad)   = AutoConf.metadGroup
daemonGroup (DaemonGroup GanetiNoded)   = AutoConf.nodedGroup
daemonGroup (DaemonGroup GanetiRapi)    = AutoConf.rapiGroup
daemonGroup (DaemonGroup GanetiConfd)   = AutoConf.confdGroup
daemonGroup (DaemonGroup GanetiWConfd)  = AutoConf.wconfdGroup
daemonGroup (DaemonGroup GanetiLuxid)   = AutoConf.luxidGroup
daemonGroup (DaemonGroup GanetiKvmd)    = AutoConf.kvmdGroup
daemonGroup (DaemonGroup GanetiMond)    = AutoConf.mondGroup
daemonGroup (ExtraGroup  DaemonsGroup)  = AutoConf.daemonsGroup
daemonGroup (ExtraGroup  AdminGroup)    = AutoConf.adminGroup

data ExtraLogReason = AccessLog | ErrorLog

-- | Some daemons might require more than one logfile.  Specifically,
-- right now only the Haskell http library "snap", used by the
-- monitoring daemon, requires multiple log files.
daemonsExtraLogbase :: GanetiDaemon -> ExtraLogReason -> String
daemonsExtraLogbase daemon AccessLog = daemonLogBase daemon ++ "-access"
daemonsExtraLogbase daemon ErrorLog = daemonLogBase daemon ++ "-error"

-- | Returns the log file for a daemon.
daemonLogFile :: GanetiDaemon -> IO FilePath
daemonLogFile daemon = do
  logDir <- Path.logDir
  return $ logDir </> daemonLogBase daemon <.> "log"

-- | Returns the extra log files for a daemon.
daemonsExtraLogFile :: GanetiDaemon -> ExtraLogReason -> IO FilePath
daemonsExtraLogFile daemon logreason = do
  logDir <- Path.logDir
  return $ logDir </> daemonsExtraLogbase daemon logreason <.> "log"

-- | Returns the pid file name for a daemon.
daemonPidFile :: GanetiDaemon -> IO FilePath
daemonPidFile daemon = do
  runDir <- Path.runDir
  return $ runDir </> daemonName daemon <.> "pid"

-- | All groups list. A bit hacking, as we can't enforce it's complete
-- at compile time.
allGroups :: [GanetiGroup]
allGroups = map DaemonGroup [minBound..maxBound] ++
            map ExtraGroup  [minBound..maxBound]

-- | Computes the group/user maps.
getEnts :: (Error e) => ResultT e IO RuntimeEnts
getEnts = do
  let userOf = liftM userID . liftIO . getUserEntryForName . daemonUser
  let groupOf = liftM groupID . liftIO . getGroupEntryForName . daemonGroup
  let allDaemons = [minBound..maxBound] :: [GanetiDaemon]
  users <- mapM userOf allDaemons
  groups <- mapM groupOf allGroups
  return $ RuntimeEnts
            (M.fromList $ zip allDaemons users)
            (M.fromList $ zip users (map daemonUser allDaemons))
            (M.fromList $ zip allGroups groups)
            (M.fromList $ zip groups (map daemonGroup allGroups))

-- | Checks whether a daemon runs as the right user.
verifyDaemonUser :: GanetiDaemon -> RuntimeEnts -> IO ()
verifyDaemonUser daemon ents = do
  myuid <- getEffectiveUserID
  -- note: we use directly ! as lookup failues shouldn't happen, due
  -- to the above map construction
  checkUidMatch (daemonName daemon) ((M.!) (reUserToUid ents) daemon) myuid

-- | Check that two UIDs are matching or otherwise exit.
checkUidMatch :: String -> UserID -> UserID -> IO ()
checkUidMatch name expected actual =
  when (expected /= actual) $ do
    hPrintf stderr "%s started using wrong user ID (%d), \
                   \expected %d\n" name
              (fromIntegral actual::Int)
              (fromIntegral expected::Int) :: IO ()
    exitWith $ ExitFailure ConstantUtils.exitFailure

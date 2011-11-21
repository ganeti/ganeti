{-| Implementation of the runtime configuration details.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.Runtime
  ( GanetiDaemon(..)
  , MiscGroup(..)
  , GanetiGroup(..)
  , RuntimeEnts
  , daemonName
  , daemonUser
  , daemonGroup
  , daemonLogFile
  , daemonPidFile
  , getEnts
  , verifyDaemonUser
  ) where

import Control.Exception
import Control.Monad
import qualified Data.Map as M
import System.Exit
import System.FilePath
import System.IO
import System.IO.Error
import System.Posix.Types
import System.Posix.User
import Text.Printf

import qualified Ganeti.Constants as C
import Ganeti.BasicTypes

data GanetiDaemon = GanetiMasterd
                  | GanetiNoded
                  | GanetiRapi
                  | GanetiConfd
                    deriving (Show, Enum, Bounded, Eq, Ord)

data MiscGroup = DaemonsGroup
               | AdminGroup
                 deriving (Show, Enum, Bounded, Eq, Ord)

data GanetiGroup = DaemonGroup GanetiDaemon
                 | ExtraGroup MiscGroup
                   deriving (Show, Eq, Ord)

type RuntimeEnts = (M.Map GanetiDaemon UserID, M.Map GanetiGroup GroupID)

-- | Returns the daemon name for a given daemon.
daemonName :: GanetiDaemon -> String
daemonName GanetiMasterd = C.masterd
daemonName GanetiNoded   = C.noded
daemonName GanetiRapi    = C.rapi
daemonName GanetiConfd   = C.confd

-- | Returns the configured user name for a daemon.
daemonUser :: GanetiDaemon -> String
daemonUser GanetiMasterd = C.masterdUser
daemonUser GanetiNoded   = C.nodedUser
daemonUser GanetiRapi    = C.rapiUser
daemonUser GanetiConfd   = C.confdUser

-- | Returns the configured group for a daemon.
daemonGroup :: GanetiGroup -> String
daemonGroup (DaemonGroup GanetiMasterd) = C.masterdGroup
daemonGroup (DaemonGroup GanetiNoded)   = C.nodedGroup
daemonGroup (DaemonGroup GanetiRapi)    = C.rapiGroup
daemonGroup (DaemonGroup GanetiConfd)   = C.confdGroup
daemonGroup (ExtraGroup  DaemonsGroup)  = C.daemonsGroup
daemonGroup (ExtraGroup  AdminGroup)    = C.adminGroup

-- | Returns the log file for a daemon.
daemonLogFile :: GanetiDaemon -> FilePath
daemonLogFile GanetiConfd = C.daemonsLogfilesGanetiConfd
daemonLogFile _           = error "Unimplemented"

-- | Returns the pid file name for a daemon.
daemonPidFile :: GanetiDaemon -> FilePath
daemonPidFile daemon = C.runGanetiDir </> daemonName daemon <.> "pid"

-- | All groups list. A bit hacking, as we can't enforce it's complete
-- at compile time.
allGroups :: [GanetiGroup]
allGroups = map DaemonGroup [minBound..maxBound] ++
            map ExtraGroup  [minBound..maxBound]

ignoreDoesNotExistErrors :: IO a -> IO (Result a)
ignoreDoesNotExistErrors value = do
  result <- tryJust (\e -> if isDoesNotExistError e
                             then Just (show e)
                             else Nothing) value
  return $ eitherToResult result

-- | Computes the group/user maps.
getEnts :: IO (Result RuntimeEnts)
getEnts = do
  users <- mapM (\daemon -> do
                   entry <- ignoreDoesNotExistErrors .
                            getUserEntryForName .
                            daemonUser $ daemon
                   return (entry >>= \e -> return (daemon, userID e))
                ) [minBound..maxBound]
  groups <- mapM (\group -> do
                    entry <- ignoreDoesNotExistErrors .
                             getGroupEntryForName .
                             daemonGroup $ group
                    return (entry >>= \e -> return (group, groupID e))
                 ) allGroups
  return $ do -- 'Result' monad
    users'  <- sequence users
    groups' <- sequence groups
    let usermap = M.fromList users'
        groupmap = M.fromList groups'
    return (usermap, groupmap)


-- | Checks whether a daemon runs as the right user.
verifyDaemonUser :: GanetiDaemon -> RuntimeEnts -> IO ()
verifyDaemonUser daemon ents = do
  myuid <- getEffectiveUserID
  -- note: we use directly ! as lookup failues shouldn't happen, due
  -- to the above map construction
  checkUidMatch (daemonName daemon) ((M.!) (fst ents) daemon) myuid

-- | Check that two UIDs are matching or otherwise exit.
checkUidMatch :: String -> UserID -> UserID -> IO ()
checkUidMatch name expected actual =
  when (expected /= actual) $ do
    hPrintf stderr "%s started using wrong user ID (%d), \
                   \expected %d\n" name
              (fromIntegral actual::Int)
              (fromIntegral expected::Int) :: IO ()
    exitWith $ ExitFailure C.exitFailure

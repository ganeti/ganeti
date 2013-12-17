{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti Ssconf interface.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.Ssconf
  ( SSKey(..)
  , sSKeyToRaw
  , sSKeyFromRaw
  , getPrimaryIPFamily
  , getMasterCandidatesIps
  , getMasterNode
  , keyToFilename
  , sSFilePrefix
  ) where

import Control.Exception
import Control.Monad (liftM)
import Data.Maybe (fromMaybe)
import qualified Network.Socket as Socket
import System.FilePath ((</>))
import System.IO.Error (isDoesNotExistError)

import qualified AutoConf
import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import qualified Ganeti.Path as Path
import Ganeti.THH
import Ganeti.Utils

-- | Maximum ssconf file size we support.
maxFileSize :: Int
maxFileSize = 131072

-- | ssconf file prefix, re-exported from Constants.
sSFilePrefix :: FilePath
sSFilePrefix = C.ssconfFileprefix

$(declareSADT "SSKey"
  [ ("SSClusterName",          'C.ssClusterName)
  , ("SSClusterTags",          'C.ssClusterTags)
  , ("SSFileStorageDir",       'C.ssFileStorageDir)
  , ("SSSharedFileStorageDir", 'C.ssSharedFileStorageDir)
  , ("SSGlusterStorageDir",    'C.ssGlusterStorageDir)
  , ("SSMasterCandidates",     'C.ssMasterCandidates)
  , ("SSMasterCandidatesIps",  'C.ssMasterCandidatesIps)
  , ("SSMasterIp",             'C.ssMasterIp)
  , ("SSMasterNetdev",         'C.ssMasterNetdev)
  , ("SSMasterNetmask",        'C.ssMasterNetmask)
  , ("SSMasterNode",           'C.ssMasterNode)
  , ("SSNodeList",             'C.ssNodeList)
  , ("SSNodePrimaryIps",       'C.ssNodePrimaryIps)
  , ("SSNodeSecondaryIps",     'C.ssNodeSecondaryIps)
  , ("SSOfflineNodes",         'C.ssOfflineNodes)
  , ("SSOnlineNodes",          'C.ssOnlineNodes)
  , ("SSPrimaryIpFamily",      'C.ssPrimaryIpFamily)
  , ("SSInstanceList",         'C.ssInstanceList)
  , ("SSReleaseVersion",       'C.ssReleaseVersion)
  , ("SSHypervisorList",       'C.ssHypervisorList)
  , ("SSMaintainNodeHealth",   'C.ssMaintainNodeHealth)
  , ("SSUidPool",              'C.ssUidPool)
  , ("SSNodegroups",           'C.ssNodegroups)
  ])

-- | Convert a ssconf key into a (full) file path.
keyToFilename :: FilePath     -- ^ Config path root
              -> SSKey        -- ^ Ssconf key
              -> FilePath     -- ^ Full file name
keyToFilename cfgpath key =
  cfgpath </> sSFilePrefix ++ sSKeyToRaw key

-- | Runs an IO action while transforming any error into 'Bad'
-- values. It also accepts an optional value to use in case the error
-- is just does not exist.
catchIOErrors :: Maybe a         -- ^ Optional default
              -> IO a            -- ^ Action to run
              -> IO (Result a)
catchIOErrors def action =
  Control.Exception.catch
        (do
          result <- action
          return (Ok result)
        ) (\err -> let bad_result = Bad (show err)
                   in return $ if isDoesNotExistError err
                                 then maybe bad_result Ok def
                                 else bad_result)

-- | Read an ssconf file.
readSSConfFile :: Maybe FilePath            -- ^ Optional config path override
               -> Maybe String              -- ^ Optional default value
               -> SSKey                     -- ^ Desired ssconf key
               -> IO (Result String)
readSSConfFile optpath def key = do
  dpath <- Path.dataDir
  result <- catchIOErrors def . readFile .
            keyToFilename (fromMaybe dpath optpath) $ key
  return (liftM (take maxFileSize) result)

-- | Parses a string containing an IP family
parseIPFamily :: Int -> Result Socket.Family
parseIPFamily fam | fam == AutoConf.pyAfInet4 = Ok Socket.AF_INET
                  | fam == AutoConf.pyAfInet6 = Ok Socket.AF_INET6
                  | otherwise = Bad $ "Unknown af_family value: " ++ show fam

-- | Read the primary IP family.
getPrimaryIPFamily :: Maybe FilePath -> IO (Result Socket.Family)
getPrimaryIPFamily optpath = do
  result <- readSSConfFile optpath
                           (Just (show AutoConf.pyAfInet4))
                           SSPrimaryIpFamily
  return (liftM rStripSpace result >>=
          tryRead "Parsing af_family" >>= parseIPFamily)

-- | Read the list of IP addresses of the master candidates of the cluster.
getMasterCandidatesIps :: Maybe FilePath -> IO (Result [String])
getMasterCandidatesIps optPath = do
  result <- readSSConfFile optPath Nothing SSMasterCandidatesIps
  return $ liftM lines result

-- | Read the name of the master node.
getMasterNode :: Maybe FilePath -> IO (Result String)
getMasterNode optPath = do
  result <- readSSConfFile optPath Nothing SSMasterNode
  return (liftM rStripSpace result)

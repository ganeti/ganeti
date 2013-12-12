{-| Implementation of the Ganeti Query2 cluster queries.

 -}

{-

Copyright (C) 2012, 2013 Google Inc.

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

module Ganeti.Query.Cluster
  ( clusterMasterNodeName
  , isWatcherPaused
  ) where

import Control.Exception (try)
import Control.Monad (liftM)
import Data.Char (isSpace)
import Numeric (readDec)

import Ganeti.Config
import Ganeti.Errors
import Ganeti.Logging
import Ganeti.Objects
import Ganeti.Path
import Ganeti.Utils (getCurrentTime)

-- | Get master node name.
clusterMasterNodeName :: ConfigData -> ErrorResult String
clusterMasterNodeName cfg =
  let cluster = configCluster cfg
      masterNodeUuid = clusterMasterNode cluster
  in liftM nodeName $ getNode cfg masterNodeUuid

isWatcherPaused :: IO (Maybe Integer)
isWatcherPaused = do
  logDebug "Checking if the watcher is paused"
  wfile <- watcherPauseFile
  contents <- try $ readFile wfile :: IO (Either IOError String)
  case contents of
    Left _ -> return Nothing
    Right s -> case readDec (dropWhile isSpace s) of
                 [(n, rest)] | all isSpace rest -> do
                   now <- getCurrentTime
                   return $ if n > now then Just n else Nothing
                 _ -> do
                   logWarning $ "Watcher pause file contents '" ++ s
                                 ++ "' not parsable as int"
                   return Nothing

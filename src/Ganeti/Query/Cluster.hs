{-| Implementation of the Ganeti Query2 cluster queries.

 -}

{-

Copyright (C) 2012, 2013 Google Inc.
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

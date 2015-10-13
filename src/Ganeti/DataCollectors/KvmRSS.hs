{-| kvm resident set size collector

It collects the resident set size (RSS) for all kvm
processes managed by Ganeti, i.e., the number of pages
the process has in RAM. The value is obtained
by taking the corresponding value from /proc/$pid/memstat.

-}

{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.DataCollectors.KvmRSS
  ( dcName
  , dcVersion
  , dcFormatVersion
  , dcCategory
  , dcKind
  , dcReport
  ) where

import Control.Monad (liftM)
import Data.Char (isSpace)
import Data.Maybe (mapMaybe)
import Network.BSD (getHostName)
import System.FilePath ((</>))
import qualified Text.JSON as J
import Text.Printf (printf)

import Ganeti.BasicTypes
import Ganeti.Confd.ClientFunctions (getInstances)
import qualified Ganeti.Constants as C
import Ganeti.DataCollectors.Types
import Ganeti.Objects
import Ganeti.Path (kvmPidDir)

-- | The name of this data collector for the resident set size (RSS).
dcName :: String
dcName = C.dataCollectorKvmRSS

-- | The version number for the data format of this data collector.
dcFormatVersion :: Int
dcFormatVersion = 1

-- | The version of this data collector.
dcVersion :: DCVersion
dcVersion = DCVerBuiltin

-- | The category of this data collector.
dcCategory :: Maybe DCCategory
dcCategory = Nothing

-- | The kind of this data collector.
dcKind :: DCKind
dcKind = DCKPerf

-- | Parse the contents of a pid file.
parsePid :: Monad m => String -> m Int
parsePid s = case reads s of
  [(pid, r)] | all isSpace r -> return pid
  _ -> fail $ "Couldn't parse pid " ++ s

-- | From the contents of a memstat file get the resident set size,
-- in pages.
parseRss :: Monad m => String -> m Int
parseRss s =
  let drop1 = dropWhile isSpace . dropWhile (not . isSpace) . dropWhile isSpace
  in case reads (drop1 s) of
    [(n, _)] -> return n
    _ -> fail $ "Failed to parse memstat " ++ s

-- | For an instance, collect the resident set size, if available.
collectInstanceRSS :: String -> IO (Result (String, J.JSValue))
collectInstanceRSS inst = runResultT $ do
  piddir <- liftIO kvmPidDir
  let pidfile = piddir </> inst
  pidstring <- liftIO $ readFile pidfile
  pid <- parsePid pidstring
  let procfspath = printf "/proc/%d/statm" pid
  memstat <- liftIO $ readFile procfspath
  rss <- parseRss memstat
  return (inst, J.showJSON rss)

-- | The data exported by the data collector.
dcReport :: IO DCReport
dcReport = do
  node <- getHostName
  instances <- liftM (genericResult (const []) (mapMaybe instName . fst))
               . runResultT $ getInstances node Nothing Nothing
  reports <- liftM justOk $ mapM collectInstanceRSS instances
  buildReport dcName dcVersion dcFormatVersion dcCategory dcKind
           . J.JSObject $ J.toJSObject reports

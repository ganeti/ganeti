{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans -fno-warn-unused-imports #-}

-- FIXME: should remove the no-warn-unused-imports option, once we get
-- around to testing function from all modules; until then, we keep
-- the (unused) imports here to generate correct coverage (0 for
-- modules we don't use)

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Ganeti.HTools.QC
  () where

import qualified Test.HUnit as HUnit
import Test.QuickCheck
import Test.QuickCheck.Monadic (assert, monadicIO, run, stop)
import Text.Printf (printf)
import Data.List (intercalate, nub, isPrefixOf, sort, (\\))
import Data.Maybe
import qualified Data.Set as Set
import Control.Monad
import Control.Applicative
import qualified System.Console.GetOpt as GetOpt
import qualified Text.JSON as J
import qualified Data.Map as Map
import qualified Data.IntMap as IntMap
import Control.Concurrent (forkIO)
import Control.Exception (bracket, catchJust)
import System.Directory (getTemporaryDirectory, removeFile)
import System.Environment (getEnv)
import System.Exit (ExitCode(..))
import System.IO (hClose, openTempFile)
import System.IO.Error (isEOFErrorType, ioeGetErrorType, isDoesNotExistError)
import System.Process (readProcessWithExitCode)

import qualified Ganeti.Confd as Confd
import qualified Ganeti.Confd.Server as Confd.Server
import qualified Ganeti.Confd.Utils as Confd.Utils
import qualified Ganeti.Config as Config
import qualified Ganeti.Daemon as Daemon
import qualified Ganeti.Hash as Hash
import qualified Ganeti.BasicTypes as BasicTypes
import qualified Ganeti.Jobs as Jobs
import qualified Ganeti.Logging as Logging
import qualified Ganeti.Luxi as Luxi
import qualified Ganeti.Objects as Objects
import qualified Ganeti.OpCodes as OpCodes
import qualified Ganeti.Query.Language as Qlang
import qualified Ganeti.Runtime as Runtime
import qualified Ganeti.HTools.CLI as CLI
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.ExtLoader
import qualified Ganeti.HTools.Group as Group
import qualified Ganeti.HTools.IAlloc as IAlloc
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.JSON as JSON
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Luxi as HTools.Luxi
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.PeerMap as PeerMap
import qualified Ganeti.HTools.Rapi
import qualified Ganeti.HTools.Simu as Simu
import qualified Ganeti.HTools.Text as Text
import qualified Ganeti.HTools.Types as Types
import qualified Ganeti.HTools.Utils as Utils
import qualified Ganeti.HTools.Version
import qualified Ganeti.Constants as C

import qualified Ganeti.HTools.Program as Program
import qualified Ganeti.HTools.Program.Hail
import qualified Ganeti.HTools.Program.Hbal
import qualified Ganeti.HTools.Program.Hscan
import qualified Ganeti.HTools.Program.Hspace

import Test.Ganeti.TestHelper (testSuite)
import Test.Ganeti.TestCommon

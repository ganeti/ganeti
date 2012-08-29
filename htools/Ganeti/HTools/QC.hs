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
  ( testJobs
  , testJSON
  ) where

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

-- * Helper functions


instance Arbitrary Jobs.OpStatus where
  arbitrary = elements [minBound..maxBound]

instance Arbitrary Jobs.JobStatus where
  arbitrary = elements [minBound..maxBound]

-- * Actual tests


-- ** Jobs tests

-- | Check that (queued) job\/opcode status serialization is idempotent.
prop_Jobs_OpStatus_serialization :: Jobs.OpStatus -> Property
prop_Jobs_OpStatus_serialization os =
  case J.readJSON (J.showJSON os) of
    J.Error e -> failTest $ "Cannot deserialise: " ++ e
    J.Ok os' -> os ==? os'

prop_Jobs_JobStatus_serialization :: Jobs.JobStatus -> Property
prop_Jobs_JobStatus_serialization js =
  case J.readJSON (J.showJSON js) of
    J.Error e -> failTest $ "Cannot deserialise: " ++ e
    J.Ok js' -> js ==? js'

testSuite "Jobs"
            [ 'prop_Jobs_OpStatus_serialization
            , 'prop_Jobs_JobStatus_serialization
            ]

-- * JSON tests

prop_JSON_toArray :: [Int] -> Property
prop_JSON_toArray intarr =
  let arr = map J.showJSON intarr in
  case JSON.toArray (J.JSArray arr) of
    Types.Ok arr' -> arr ==? arr'
    Types.Bad err -> failTest $ "Failed to parse array: " ++ err

prop_JSON_toArrayFail :: Int -> String -> Bool -> Property
prop_JSON_toArrayFail i s b =
  -- poor man's instance Arbitrary JSValue
  forAll (elements [J.showJSON i, J.showJSON s, J.showJSON b]) $ \item ->
  case JSON.toArray item of
    Types.Bad _ -> property True
    Types.Ok result -> failTest $ "Unexpected parse, got " ++ show result

testSuite "JSON"
          [ 'prop_JSON_toArray
          , 'prop_JSON_toArrayFail
          ]

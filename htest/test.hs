{-| Unittest runner for ganeti-htools.

-}

{-

Copyright (C) 2009, 2011, 2012 Google Inc.

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

module Main(main) where

import Data.Monoid (mappend)
import Test.Framework
import System.Environment (getArgs)

import Test.Ganeti.TestImports ()
import Test.Ganeti.Attoparsec
import Test.Ganeti.BasicTypes
import Test.Ganeti.Block.Drbd.Parser
import Test.Ganeti.Block.Drbd.Types
import Test.Ganeti.Common
import Test.Ganeti.Confd.Utils
import Test.Ganeti.Daemon
import Test.Ganeti.Errors
import Test.Ganeti.HTools.Backend.Simu
import Test.Ganeti.HTools.Backend.Text
import Test.Ganeti.HTools.CLI
import Test.Ganeti.HTools.Cluster
import Test.Ganeti.HTools.Container
import Test.Ganeti.HTools.Graph
import Test.Ganeti.HTools.Instance
import Test.Ganeti.HTools.Loader
import Test.Ganeti.HTools.Node
import Test.Ganeti.HTools.PeerMap
import Test.Ganeti.HTools.Types
import Test.Ganeti.JSON
import Test.Ganeti.Jobs
import Test.Ganeti.Luxi
import Test.Ganeti.Objects
import Test.Ganeti.OpCodes
import Test.Ganeti.Query.Filter
import Test.Ganeti.Query.Language
import Test.Ganeti.Query.Query
import Test.Ganeti.Rpc
import Test.Ganeti.Ssconf
import Test.Ganeti.THH
import Test.Ganeti.Types
import Test.Ganeti.Utils

-- | Our default test options, overring the built-in test-framework
-- ones (but not the supplied command line parameters).
defOpts :: TestOptions
defOpts = TestOptions
       { topt_seed                               = Nothing
       , topt_maximum_generated_tests            = Just 500
       , topt_maximum_unsuitable_generated_tests = Just 5000
       , topt_maximum_test_size                  = Nothing
       , topt_maximum_test_depth                 = Nothing
       , topt_timeout                            = Nothing
       }

-- | All our defined tests.
allTests :: [Test]
allTests =
  [ testBasicTypes
  , testAttoparsec
  , testCommon
  , testConfd_Utils
  , testDaemon
  , testBlock_Drbd_Parser
  , testBlock_Drbd_Types
  , testErrors
  , testHTools_Backend_Simu
  , testHTools_Backend_Text
  , testHTools_CLI
  , testHTools_Cluster
  , testHTools_Container
  , testHTools_Graph
  , testHTools_Instance
  , testHTools_Loader
  , testHTools_Node
  , testHTools_PeerMap
  , testHTools_Types
  , testJSON
  , testJobs
  , testLuxi
  , testObjects
  , testOpCodes
  , testQuery_Filter
  , testQuery_Language
  , testQuery_Query
  , testRpc
  , testSsconf
  , testTHH
  , testTypes
  , testUtils
  ]

-- | Main function. Note we don't use defaultMain since we want to
-- control explicitly our test sizes (and override the default).
main :: IO ()
main = do
  ropts <- getArgs >>= interpretArgsOrExit
  let opts = maybe defOpts (defOpts `mappend`) $ ropt_test_options ropts
  defaultMainWithOpts allTests (ropts { ropt_test_options = Just opts })

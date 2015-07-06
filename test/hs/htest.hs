{-| Unittest runner for ganeti-htools.

-}

{-

Copyright (C) 2009, 2011, 2012, 2013 Google Inc.
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

module Main(main) where

import Data.Monoid (mappend)
import Test.Framework
import System.Environment (getArgs)
import System.Log.Logger

import Test.AutoConf
import Test.Ganeti.TestImports ()
import Test.Ganeti.Attoparsec
import Test.Ganeti.BasicTypes
import Test.Ganeti.Common
import Test.Ganeti.Constants
import Test.Ganeti.Confd.Utils
import Test.Ganeti.Confd.Types
import Test.Ganeti.Daemon
import Test.Ganeti.Errors
import Test.Ganeti.HTools.Backend.MonD
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
import Test.Ganeti.Hypervisor.Xen.XmParser
import Test.Ganeti.JSON
import Test.Ganeti.Jobs
import Test.Ganeti.JQueue
import Test.Ganeti.JQScheduler
import Test.Ganeti.Kvmd
import Test.Ganeti.Locking.Allocation
import Test.Ganeti.Locking.Locks
import Test.Ganeti.Locking.Waiting
import Test.Ganeti.Luxi
import Test.Ganeti.Network
import Test.Ganeti.Objects
import Test.Ganeti.Objects.BitArray
import Test.Ganeti.OpCodes
import Test.Ganeti.Query.Aliases
import Test.Ganeti.Query.Filter
import Test.Ganeti.Query.Instance
import Test.Ganeti.Query.Language
import Test.Ganeti.Query.Network
import Test.Ganeti.Query.Query
import Test.Ganeti.Rpc
import Test.Ganeti.Runtime
import Test.Ganeti.SlotMap
import Test.Ganeti.Ssconf
import Test.Ganeti.Storage.Diskstats.Parser
import Test.Ganeti.Storage.Drbd.Parser
import Test.Ganeti.Storage.Drbd.Types
import Test.Ganeti.Storage.Lvm.LVParser
import Test.Ganeti.THH
import Test.Ganeti.THH.Types
import Test.Ganeti.Types
import Test.Ganeti.Utils
import Test.Ganeti.Utils.MultiMap
import Test.Ganeti.Utils.Statistics
import Test.Ganeti.WConfd.Ssconf
import Test.Ganeti.WConfd.TempRes

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
  [ testAutoConf
  , testBasicTypes
  , testAttoparsec
  , testCommon
  , testConstants
  , testConfd_Types
  , testConfd_Utils
  , testDaemon
  , testBlock_Diskstats_Parser
  , testBlock_Drbd_Parser
  , testBlock_Drbd_Types
  , testErrors
  , testHTools_Backend_MonD
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
  , testHypervisor_Xen_XmParser
  , testJSON
  , testJobs
  , testJQueue
  , testJQScheduler
  , testKvmd
  , testLocking_Allocation
  , testLocking_Locks
  , testLocking_Waiting
  , testLuxi
  , testNetwork
  , testObjects
  , testObjects_BitArray
  , testOpCodes
  , testQuery_Aliases
  , testQuery_Filter
  , testQuery_Instance
  , testQuery_Language
  , testQuery_Network
  , testQuery_Query
  , testRpc
  , testRuntime
  , testSlotMap
  , testSsconf
  , testStorage_Lvm_LVParser
  , testTHH
  , testTHH_Types
  , testTypes
  , testUtils
  , testUtils_MultiMap
  , testUtils_Statistics
  , testWConfd_Ssconf
  , testWConfd_TempRes
  ]

-- | Main function. Note we don't use defaultMain since we want to
-- control explicitly our test sizes (and override the default).
main :: IO ()
main = do
  ropts <- getArgs >>= interpretArgsOrExit
  let opts = maybe defOpts (defOpts `mappend`) $ ropt_test_options ropts
  -- silence the logging system, so that tests can execute I/O actions
  -- which create logs without polluting stderr
  -- FIXME: improve this by allowing tests to use logging if needed
  updateGlobalLogger rootLoggerName (setLevel EMERGENCY)
  defaultMainWithOpts allTests (ropts { ropt_test_options = Just opts })

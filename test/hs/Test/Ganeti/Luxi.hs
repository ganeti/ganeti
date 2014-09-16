{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

module Test.Ganeti.Luxi (testLuxi) where

import Test.HUnit
import Test.QuickCheck
import Test.QuickCheck.Monadic (monadicIO, run, stop)

import Data.List
import Control.Applicative
import Control.Concurrent (forkIO)
import Control.Exception (bracket)
import qualified Text.JSON as J

import Test.Ganeti.OpCodes ()
import Test.Ganeti.Query.Language (genFilter)
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper
import Test.Ganeti.Types (genReasonTrail)

import Ganeti.BasicTypes
import qualified Ganeti.Luxi as Luxi
import qualified Ganeti.UDSServer as US

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Luxi tests

$(genArbitrary ''Luxi.LuxiReq)

instance Arbitrary Luxi.LuxiOp where
  arbitrary = do
    lreq <- arbitrary
    case lreq of
      Luxi.ReqQuery -> Luxi.Query <$> arbitrary <*> genFields <*> genFilter
      Luxi.ReqQueryFields -> Luxi.QueryFields <$> arbitrary <*> genFields
      Luxi.ReqQueryNodes -> Luxi.QueryNodes <$> listOf genFQDN <*>
                            genFields <*> arbitrary
      Luxi.ReqQueryGroups -> Luxi.QueryGroups <$> arbitrary <*>
                             arbitrary <*> arbitrary
      Luxi.ReqQueryNetworks -> Luxi.QueryNetworks <$> arbitrary <*>
                             arbitrary <*> arbitrary
      Luxi.ReqQueryInstances -> Luxi.QueryInstances <$> listOf genFQDN <*>
                                genFields <*> arbitrary
      Luxi.ReqQueryFilters -> Luxi.QueryFilters <$> arbitrary <*> genFields
      Luxi.ReqReplaceFilter -> Luxi.ReplaceFilter <$> genMaybe genUUID <*>
                               arbitrary <*> arbitrary <*> arbitrary <*>
                               genReasonTrail
      Luxi.ReqDeleteFilter -> Luxi.DeleteFilter <$> genUUID
      Luxi.ReqQueryJobs -> Luxi.QueryJobs <$> arbitrary <*> genFields
      Luxi.ReqQueryExports -> Luxi.QueryExports <$>
                              listOf genFQDN <*> arbitrary
      Luxi.ReqQueryConfigValues -> Luxi.QueryConfigValues <$> genFields
      Luxi.ReqQueryClusterInfo -> pure Luxi.QueryClusterInfo
      Luxi.ReqQueryTags -> do
        kind <- arbitrary
        Luxi.QueryTags kind <$> genLuxiTagName kind
      Luxi.ReqSubmitJob -> Luxi.SubmitJob <$> resize maxOpCodes arbitrary
      Luxi.ReqSubmitJobToDrainedQueue -> Luxi.SubmitJobToDrainedQueue <$>
                                         resize maxOpCodes arbitrary
      Luxi.ReqSubmitManyJobs -> Luxi.SubmitManyJobs <$>
                                resize maxOpCodes arbitrary
      Luxi.ReqWaitForJobChange -> Luxi.WaitForJobChange <$> arbitrary <*>
                                  genFields <*> pure J.JSNull <*>
                                  pure J.JSNull <*> arbitrary
      Luxi.ReqPickupJob -> Luxi.PickupJob <$> arbitrary
      Luxi.ReqArchiveJob -> Luxi.ArchiveJob <$> arbitrary
      Luxi.ReqAutoArchiveJobs -> Luxi.AutoArchiveJobs <$> arbitrary <*>
                                 arbitrary
      Luxi.ReqCancelJob -> Luxi.CancelJob <$> arbitrary <*> arbitrary
      Luxi.ReqChangeJobPriority -> Luxi.ChangeJobPriority <$> arbitrary <*>
                                   arbitrary
      Luxi.ReqSetDrainFlag -> Luxi.SetDrainFlag <$> arbitrary
      Luxi.ReqSetWatcherPause -> Luxi.SetWatcherPause <$> arbitrary

-- | Simple check that encoding/decoding of LuxiOp works.
prop_CallEncoding :: Luxi.LuxiOp -> Property
prop_CallEncoding op =
  (US.parseCall (US.buildCall (Luxi.strOfOp op) (Luxi.opToArgs op))
    >>= uncurry Luxi.decodeLuxiCall) ==? Ok op

-- | Server ping-pong helper.
luxiServerPong :: Luxi.Client -> IO ()
luxiServerPong c = do
  msg <- Luxi.recvMsgExt c
  case msg of
    Luxi.RecvOk m -> Luxi.sendMsg c m >> luxiServerPong c
    _ -> return ()

-- | Client ping-pong helper.
luxiClientPong :: Luxi.Client -> [String] -> IO [String]
luxiClientPong c =
  mapM (\m -> Luxi.sendMsg c m >> Luxi.recvMsg c)

-- | Monadic check that, given a server socket, we can connect via a
-- client to it, and that we can send a list of arbitrary messages and
-- get back what we sent.
prop_ClientServer :: [[DNSChar]] -> Property
prop_ClientServer dnschars = monadicIO $ do
  let msgs = map (map dnsGetChar) dnschars
  fpath <- run $ getTempFileName "luxitest"
  -- we need to create the server first, otherwise (if we do it in the
  -- forked thread) the client could try to connect to it before it's
  -- ready
  server <- run $ Luxi.getLuxiServer False fpath
  -- fork the server responder
  _ <- run . forkIO $
    bracket
      (Luxi.acceptClient server)
      (\c -> Luxi.closeClient c >> Luxi.closeServer server)
      luxiServerPong
  replies <- run $
    bracket
      (Luxi.getLuxiClient fpath)
      Luxi.closeClient
      (`luxiClientPong` msgs)
  stop $ replies ==? msgs

-- | Check that Python and Haskell define the same Luxi requests list.
case_AllDefined :: Assertion
case_AllDefined = do
  py_stdout <- runPython "from ganeti import luxi\n\
                         \print '\\n'.join(luxi.REQ_ALL)" "" >>=
               checkPythonResult
  let py_ops = sort $ lines py_stdout
      hs_ops = Luxi.allLuxiCalls
      extra_py = py_ops \\ hs_ops
      extra_hs = hs_ops \\ py_ops
  assertBool ("Luxi calls missing from Haskell code:\n" ++
              unlines extra_py) (null extra_py)
  assertBool ("Extra Luxi calls in the Haskell code:\n" ++
              unlines extra_hs) (null extra_hs)


testSuite "Luxi"
          [ 'prop_CallEncoding
          , 'prop_ClientServer
          , 'case_AllDefined
          ]

{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

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

module Test.Ganeti.Luxi (testLuxi) where

import Test.QuickCheck
import Test.QuickCheck.Monadic (monadicIO, run, stop)

import Control.Applicative
import Control.Concurrent (forkIO)
import Control.Exception (bracket)
import System.Directory (getTemporaryDirectory, removeFile)
import System.IO (hClose, openTempFile)
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Query.Language (genFilter)
import Test.Ganeti.OpCodes ()

import Ganeti.BasicTypes
import qualified Ganeti.Luxi as Luxi

-- * Luxi tests

$(genArbitrary ''Luxi.TagObject)

$(genArbitrary ''Luxi.LuxiReq)

instance Arbitrary Luxi.LuxiOp where
  arbitrary = do
    lreq <- arbitrary
    case lreq of
      Luxi.ReqQuery -> Luxi.Query <$> arbitrary <*> getFields <*> genFilter
      Luxi.ReqQueryFields -> Luxi.QueryFields <$> arbitrary <*> getFields
      Luxi.ReqQueryNodes -> Luxi.QueryNodes <$> listOf getFQDN <*>
                            getFields <*> arbitrary
      Luxi.ReqQueryGroups -> Luxi.QueryGroups <$> arbitrary <*>
                             arbitrary <*> arbitrary
      Luxi.ReqQueryInstances -> Luxi.QueryInstances <$> listOf getFQDN <*>
                                getFields <*> arbitrary
      Luxi.ReqQueryJobs -> Luxi.QueryJobs <$> arbitrary <*> getFields
      Luxi.ReqQueryExports -> Luxi.QueryExports <$>
                              listOf getFQDN <*> arbitrary
      Luxi.ReqQueryConfigValues -> Luxi.QueryConfigValues <$> getFields
      Luxi.ReqQueryClusterInfo -> pure Luxi.QueryClusterInfo
      Luxi.ReqQueryTags -> Luxi.QueryTags <$> arbitrary <*> getFQDN
      Luxi.ReqSubmitJob -> Luxi.SubmitJob <$> resize maxOpCodes arbitrary
      Luxi.ReqSubmitManyJobs -> Luxi.SubmitManyJobs <$>
                                resize maxOpCodes arbitrary
      Luxi.ReqWaitForJobChange -> Luxi.WaitForJobChange <$> arbitrary <*>
                                  getFields <*> pure J.JSNull <*>
                                  pure J.JSNull <*> arbitrary
      Luxi.ReqArchiveJob -> Luxi.ArchiveJob <$> arbitrary
      Luxi.ReqAutoArchiveJobs -> Luxi.AutoArchiveJobs <$> arbitrary <*>
                                 arbitrary
      Luxi.ReqCancelJob -> Luxi.CancelJob <$> arbitrary
      Luxi.ReqSetDrainFlag -> Luxi.SetDrainFlag <$> arbitrary
      Luxi.ReqSetWatcherPause -> Luxi.SetWatcherPause <$> arbitrary

-- | Simple check that encoding/decoding of LuxiOp works.
prop_CallEncoding :: Luxi.LuxiOp -> Property
prop_CallEncoding op =
  (Luxi.validateCall (Luxi.buildCall op) >>= Luxi.decodeCall) ==? Ok op

-- | Helper to a get a temporary file name.
getTempFileName :: IO FilePath
getTempFileName = do
  tempdir <- getTemporaryDirectory
  (fpath, handle) <- openTempFile tempdir "luxitest"
  _ <- hClose handle
  removeFile fpath
  return fpath

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
  fpath <- run getTempFileName
  -- we need to create the server first, otherwise (if we do it in the
  -- forked thread) the client could try to connect to it before it's
  -- ready
  server <- run $ Luxi.getServer fpath
  -- fork the server responder
  _ <- run . forkIO $
    bracket
      (Luxi.acceptClient server)
      (\c -> Luxi.closeClient c >> Luxi.closeServer fpath server)
      luxiServerPong
  replies <- run $
    bracket
      (Luxi.getClient fpath)
      Luxi.closeClient
      (`luxiClientPong` msgs)
  stop $ replies ==? msgs

testSuite "Luxi"
          [ 'prop_CallEncoding
          , 'prop_ClientServer
          ]

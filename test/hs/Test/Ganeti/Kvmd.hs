{-# LANGUAGE TemplateHaskell #-}
{-| Unittests for the KVM daemon.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Test.Ganeti.Kvmd (testKvmd) where

import Control.Concurrent
import Control.Exception (try)
import qualified Network.Socket as Socket
import System.Directory
import System.FilePath
import System.IO

import qualified Ganeti.Kvmd as Kvmd
import qualified Ganeti.UDSServer as UDSServer
import Test.HUnit as HUnit

import qualified Test.Ganeti.TestHelper as TestHelper (testSuite)
import qualified Test.Ganeti.TestCommon as TestCommon (getTempFileName)

import qualified Ganeti.Logging as Logging

{-# ANN module "HLint: ignore Use camelCase" #-}

startKvmd :: FilePath -> IO ThreadId
startKvmd dir =
  forkIO (do Logging.setupLogging Nothing "ganeti-kvmd" False False
               False Logging.SyslogNo
             Kvmd.startWith dir)

stopKvmd :: ThreadId -> IO ()
stopKvmd = killThread

delayKvmd :: IO ()
delayKvmd = threadDelay 1000000

detectShutdown :: (Handle -> IO ()) -> IO Bool
detectShutdown putFn =
  do monitorDir <- TestCommon.getTempFileName "ganeti"
     let monitor = "instance" <.> Kvmd.monitorExtension
         monitorFile = monitorDir </> monitor
         shutdownFile = Kvmd.shutdownPath monitorFile
     -- ensure the KVM directory exists
     createDirectoryIfMissing True monitorDir
     -- ensure the shutdown file does not exist
     (try (removeFile shutdownFile) :: IO (Either IOError ())) >> return ()
     -- start KVM daemon
     threadId <- startKvmd monitorDir
     threadDelay 1000
     -- create a Unix socket
     sock <- UDSServer.openServerSocket monitorFile
     Socket.listen sock 1
     handle <- UDSServer.acceptSocket sock
     -- read 'qmp_capabilities' message
     res <- try . hGetLine $ handle :: IO (Either IOError String)
     case res of
       Left err ->
         assertFailure $ "Expecting " ++ show Kvmd.monitorGreeting ++
                         ", received " ++ show err
       Right str -> Kvmd.monitorGreeting @=? str
     -- send Qmp messages
     putFn handle
     hFlush handle
     -- close the Unix socket
     UDSServer.closeClientSocket handle
     UDSServer.closeServerSocket sock monitorFile
     -- KVM needs time to create the shutdown file
     delayKvmd
     -- stop the KVM daemon
     stopKvmd threadId
     -- check for shutdown file
     doesFileExist shutdownFile

case_DetectAdminShutdown :: Assertion
case_DetectAdminShutdown =
  do res <- detectShutdown putMessage
     assertBool "Detected user shutdown instead of administrator shutdown" $
       not res
  where putMessage handle =
          do hPrint handle "POWERDOWN"
             hPrint handle "SHUTDOWN"

case_DetectUserShutdown :: Assertion
case_DetectUserShutdown =
  do res <- detectShutdown putMessage
     assertBool "Detected administrator shutdown instead of user shutdown" res
  where putMessage handle =
          hPrint handle "SHUTDOWN"

TestHelper.testSuite "Kvmd"
  [ 'case_DetectAdminShutdown
  , 'case_DetectUserShutdown
  ]

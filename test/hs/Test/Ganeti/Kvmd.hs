{-# LANGUAGE TemplateHaskell #-}
{-| Unittests for the KVM daemon.

-}

{-

Copyright (C) 2013 Google Inc.

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

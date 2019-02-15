{-| KVM daemon

The KVM daemon is responsible for determining whether a given KVM
instance was shutdown by an administrator or a user.  For more
information read the design document on the KVM daemon.

The KVM daemon design is split in 2 parts, namely, monitors for Qmp
sockets and directory/file watching.

The monitors are spawned in lightweight Haskell threads and are
reponsible for handling the communication between the KVM daemon and
the KVM instance using the Qmp protocol.  During the communcation, the
monitor parses the Qmp messages and if powerdown or shutdown is
received, then the shutdown file is written in the KVM control
directory.  Otherwise, when the communication terminates, that same
file is removed.  The communication terminates when the KVM instance
stops or crashes.

The directory and file watching uses inotify to track down events on
the KVM control directory and its parents.  There is a directory
crawler that will try to add a watch to the KVM control directory if
available or its parents, thus replacing watches until the KVM control
directory becomes available.  When this happens, a monitor for the Qmp
socket is spawned.  Given that the KVM daemon might stop or crash, the
directory watching also simulates events for the Qmp sockets that
already exist in the KVM control directory when the KVM daemon starts.

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

module Ganeti.Kvmd where

import Prelude hiding (rem)

import Control.Applicative ((<$>))
import Control.Exception (try)
import Control.Concurrent
import Control.Monad (unless, when)
import Data.List
import Data.Set (Set)
import qualified Data.Set as Set (delete, empty, insert, member)
import System.Directory
import System.FilePath
import System.IO
import System.IO.Error (isEOFError)
import System.INotify

import qualified AutoConf
import qualified Ganeti.BasicTypes as BasicTypes
import qualified Ganeti.Constants as Constants
import qualified Ganeti.Daemon as Daemon (getFQDN)
import qualified Ganeti.Logging as Logging
import qualified Ganeti.UDSServer as UDSServer
import qualified Ganeti.Ssconf as Ssconf
import qualified Ganeti.Types as Types

type Lock = MVar ()
type Monitors = MVar (Set FilePath)

-- * Utils

-- | @isPrefixPath x y@ determines whether @x@ is a 'FilePath' prefix
-- of 'FilePath' @y@.
isPrefixPath :: FilePath -> FilePath -> Bool
isPrefixPath x y =
  (splitPath x `isPrefixOf` splitPath y) ||
  (splitPath (x ++ "/") `isPrefixOf` splitPath y)

monitorGreeting :: String
monitorGreeting = "{\"execute\": \"qmp_capabilities\"}"

-- | KVM control directory containing the Qmp sockets.
monitorDir :: String
monitorDir = AutoConf.localstatedir </> "run/ganeti/kvm-hypervisor/ctrl/"

monitorExtension :: String
monitorExtension = ".kvmd"

isMonitorPath :: FilePath -> Bool
isMonitorPath = (== monitorExtension) . takeExtension

shutdownExtension :: String
shutdownExtension = ".shutdown"

shutdownPath :: String -> String
shutdownPath = (`replaceExtension` shutdownExtension)

touchFile :: FilePath -> IO ()
touchFile file = withFile file WriteMode (const . return $ ())

-- * Monitors for Qmp sockets

-- | @parseQmp isPowerdown isShutdown isStop str@ parses the packet
-- @str@ and returns whether a powerdown, shutdown, or stop event is
-- contained in that packet, defaulting to the values @isPowerdown@,
-- @isShutdown@, and @isStop@, otherwise.
parseQmp :: Bool -> Bool -> Bool -> String -> (Bool, Bool, Bool)
parseQmp isPowerdown isShutdown isStop str =
  let
    isPowerdown'
      | "\"POWERDOWN\"" `isInfixOf` str = True
      | otherwise = isPowerdown
    isShutdown'
      | "\"SHUTDOWN\"" `isInfixOf` str = True
      | otherwise = isShutdown
    isStop'
      | "\"STOP\"" `isInfixOf` str = True
      | otherwise = isStop
  in
   (isPowerdown', isShutdown', isStop')

-- | @receiveQmp handle@ listens for Qmp events on @handle@ and, when
-- @handle@ is closed, it returns 'True' if a user shutdown event was
-- received, and 'False' otherwise.
receiveQmp :: Handle -> IO Bool
receiveQmp handle = isUserShutdown <$> receive False False False
  where -- | A user shutdown consists of a shutdown event with no
        -- prior powerdown event and no stop event.
        isUserShutdown (isShutdown, isPowerdown, isStop)
          = isPowerdown && not isShutdown && not isStop

        receive isPowerdown isShutdown isStop =
          do res <- try $ hGetLine handle
             case res of
               Left err -> do
                 unless (isEOFError err) $
                   hPrint stderr err
                 return (isPowerdown, isShutdown, isStop)
               Right str -> do
                 let (isPowerdown', isShutdown', isStop') =
                       parseQmp isPowerdown isShutdown isStop str
                 Logging.logDebug $ "Receive QMP message: " ++ str
                 receive isPowerdown' isShutdown' isStop'

-- | @detectMonitor monitorFile handle@ listens for Qmp events on
-- @handle@ for Qmp socket @monitorFile@ and, when communcation
-- terminates, it either creates the shutdown file, if a user shutdown
-- was detected, or it deletes that same file, if an administrator
-- shutdown was detected.
detectMonitor :: FilePath -> Handle -> IO ()
detectMonitor monitorFile handle =
  do let shutdownFile = shutdownPath monitorFile
     res <- receiveQmp handle
     if res
       then do
         Logging.logInfo $ "Detect user shutdown, creating file " ++
           show shutdownFile
         touchFile shutdownFile
       else do
         Logging.logInfo $ "Detect admin shutdown, removing file " ++
           show shutdownFile
         (try (removeFile shutdownFile) :: IO (Either IOError ())) >> return ()

-- | @runMonitor monitorFile@ creates a monitor for the Qmp socket
-- @monitorFile@ and calls 'detectMonitor'.
runMonitor :: FilePath -> IO ()
runMonitor monitorFile =
  do handle <- UDSServer.openClientSocket Constants.luxiDefRwto monitorFile
     hPutStrLn handle monitorGreeting
     hFlush handle
     detectMonitor monitorFile handle
     UDSServer.closeClientSocket handle

-- | @ensureMonitor monitors monitorFile@ ensures that there is
-- exactly one monitor running for the Qmp socket @monitorFile@, given
-- the existing set of monitors @monitors@.
ensureMonitor :: Monitors -> FilePath -> IO ()
ensureMonitor monitors monitorFile =
  modifyMVar_ monitors $
    \files ->
      if monitorFile `Set.member` files
      then return files
      else do
        forkIO tryMonitor >> return ()
        return $ monitorFile `Set.insert` files
  where tryMonitor =
          do Logging.logInfo $ "Start monitor " ++ show monitorFile
             res <- try (runMonitor monitorFile) :: IO (Either IOError ())
             case res of
               Left err ->
                 Logging.logError $ "Catch monitor exception: " ++ show err
               _ ->
                 return ()
             Logging.logInfo $ "Stop monitor " ++ show monitorFile
             modifyMVar_ monitors (return . Set.delete monitorFile)

-- * Directory and file watching

-- | Handles an inotify event outside the target directory.
--
-- Tracks events on the parent directory of the KVM control directory
-- until one of its parents becomes available.
handleGenericEvent :: Lock -> String -> String -> Event -> IO ()
handleGenericEvent lock curDir tarDir ev@Created {}
  | isDirectory ev && curDir /= tarDir &&
    (curDir </> filePath ev) `isPrefixPath` tarDir = putMVar lock ()
handleGenericEvent lock _ _ event
  | event == DeletedSelf || event == Unmounted = putMVar lock ()
handleGenericEvent _ _ _ _ = return ()

-- | Handles an inotify event in the target directory.
--
-- Upon a create or open event inside the KVM control directory, it
-- ensures that there is a monitor running for the new Qmp socket.
handleTargetEvent :: Lock -> Monitors -> String -> Event -> IO ()
handleTargetEvent _ monitors tarDir ev@Created {}
  | not (isDirectory ev) && isMonitorPath (filePath ev) =
    ensureMonitor monitors $ tarDir </> filePath ev
handleTargetEvent lock monitors tarDir ev@Opened {}
  | not (isDirectory ev) =
    case maybeFilePath ev of
      Just p | isMonitorPath p ->
        ensureMonitor monitors $ tarDir </> filePath ev
      _ ->
        handleGenericEvent lock tarDir tarDir ev
handleTargetEvent _ _ tarDir ev@Created {}
  | not (isDirectory ev) && takeExtension (filePath ev) == shutdownExtension =
    Logging.logInfo $ "User shutdown file opened " ++
      show (tarDir </> filePath ev)
handleTargetEvent _ _ tarDir ev@Deleted {}
  | not (isDirectory ev) && takeExtension (filePath ev) == shutdownExtension =
    Logging.logInfo $ "User shutdown file deleted " ++
      show (tarDir </> filePath ev)
handleTargetEvent lock _ tarDir ev =
  handleGenericEvent lock tarDir tarDir ev

-- | Dispatches inotify events depending on the directory they occur in.
handleDir :: Lock -> Monitors -> String -> String -> Event -> IO ()
handleDir lock monitors curDir tarDir event =
  do Logging.logDebug $ "Handle event " ++ show event
     if curDir == tarDir
       then handleTargetEvent lock monitors tarDir event
       else handleGenericEvent lock curDir tarDir event

-- | Simulates file creation events for the Qmp sockets that already
-- exist in @dir@.
recapDir :: Lock -> Monitors -> FilePath -> IO ()
recapDir lock monitors dir =
  do files <- getDirectoryContents dir
     let files' = filter isMonitorPath files
     mapM_ sendEvent files'
  where sendEvent file =
          handleTargetEvent lock monitors dir Created { isDirectory = False
                                                      , filePath = file }

-- | Crawls @tarDir@, or its parents until @tarDir@ becomes available,
-- always listening for inotify events.
--
-- Used for crawling the KVM control directory and its parents, as
-- well as simulating file creation events.
watchDir :: Lock -> FilePath -> INotify -> IO ()
watchDir lock tarDir inotify = watchDir' tarDir
  where watchDirEvents dir
          | dir == tarDir = [AllEvents]
          | otherwise = [Create, DeleteSelf]

        watchDir' dir =
          do add <- doesDirectoryExist dir
             if add
               then do
                 let events = watchDirEvents dir
                 Logging.logInfo $ "Watch directory " ++ show dir
                 monitors <- newMVar Set.empty
                 wd <- addWatch inotify events dir
                       (handleDir lock monitors dir tarDir)
                 when (dir == tarDir) $ recapDir lock monitors dir
                 () <- takeMVar lock
                 rem <- doesDirectoryExist dir
                 if rem
                   then do
                     Logging.logInfo $ "Unwatch directory " ++ show dir
                     removeWatch wd
                   else
                     Logging.logInfo $ "Throw away watch from directory " ++
                       show dir
               else
                 watchDir' (takeDirectory dir)

rewatchDir :: Lock -> FilePath -> INotify -> IO ()
rewatchDir lock tarDir inotify =
  do watchDir lock tarDir inotify
     rewatchDir lock tarDir inotify

-- * Starting point

startWith :: FilePath -> IO ()
startWith dir =
  do lock <- newEmptyMVar
     withINotify (rewatchDir lock dir)

start :: IO ()
start =
  do fqdn <- Daemon.getFQDN
     hypervisors <- Ssconf.getHypervisorList Nothing
     userShutdown <- Ssconf.getEnabledUserShutdown Nothing
     vmCapable <- Ssconf.getNodesVmCapable Nothing
     BasicTypes.genericResult
       Logging.logInfo
       (const $ startWith monitorDir) $ do
         isKvm =<< hypervisors
         isUserShutdown =<< userShutdown
         isVmCapable fqdn =<< vmCapable
  where
    isKvm hs
      | Types.Kvm `elem` hs = return ()
      | otherwise = fail "KVM not enabled, exiting"

    isUserShutdown True = return ()
    isUserShutdown _ = fail "User shutdown not enabled, exiting"

    isVmCapable node vmCapables =
      case lookup node vmCapables of
        Just True -> return ()
        _ -> fail $ "Node " ++ show node ++ " is not VM capable, exiting"

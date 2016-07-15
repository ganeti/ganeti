{-| Utility functions for complex operations carried out by several daemons.

-}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.Daemon.Utils
  ( verifyMaster
  , handleMasterVerificationOptions
  ) where

import Control.Concurrent (threadDelay)
import Control.Monad (unless)
import Data.Either (rights)
import qualified Data.Foldable as F
import Data.List (partition)
import System.Exit (ExitCode(..))

import Ganeti.BasicTypes
import qualified Ganeti.Config as Config
import qualified Ganeti.Constants as C
import Ganeti.Daemon (getFQDN, DaemonOptions, optNoVoting, optYesDoIt)
import Ganeti.Logging
import Ganeti.Objects
import qualified Ganeti.Path as Path
import Ganeti.Utils (frequency)
import Ganeti.Rpc

-- | Gather votes from all nodes and verify that we we are
-- the master. Return True if the voting is won, False if
-- not enough
verifyMasterVotes :: IO (Result Bool)
verifyMasterVotes = runResultT $ do
  liftIO $ logDebug "Gathering votes for the master node"
  myName <- liftIO getFQDN
  liftIO . logDebug $ "My hostname is " ++ myName
  conf_file <- liftIO Path.clusterConfFile
  config <- mkResultT $ Config.loadConfig conf_file
  let nodes = F.toList $ configNodes config
  votes <- liftIO . executeRpcCall nodes $ RpcCallMasterNodeName
  let (missing, valid) = partition (isLeft . snd) votes
      noDataNodes = map (nodeName . fst) missing
      validVotes = map rpcResultMasterNodeNameMaster . rights $ map snd valid
      inFavor = length $ filter (== myName) validVotes
      voters = length nodes
      unknown = length missing
  liftIO . unless (null noDataNodes) . logWarning
    . (++) "No voting RPC result from " $ show noDataNodes
  liftIO . logDebug . (++) "Valid votes: " $ show (frequency validVotes)
  if 2 * inFavor > voters
    then return True
    else if 2 * (inFavor + unknown) > voters
           then return False
           else fail $ "Voting cannot be won by " ++ myName
                       ++ ", valid votes of " ++ show voters
                       ++ " are " ++ show (frequency validVotes)

-- | Verify, by voting, that this node is the master. Bad if we're not.
-- Allow the given number of retries to wait for not available nodes.
verifyMaster :: Int -> IO (Result ())
verifyMaster retries = runResultT $ do
  won <- mkResultT verifyMasterVotes
  unless won $
    if retries <= 0
      then fail "Couldn't gather voting results of enough nodes"
      else do
        liftIO $ logDebug "Voting not final due to missing votes."
        liftIO . threadDelay $ C.masterVotingRetryIntervall * 1000000
        mkResultT $ verifyMaster (retries - 1)

-- | Verify master position according to the options provided, usually
-- by carrying out a voting. Either return unit on success, or a suggested
-- exit code.
handleMasterVerificationOptions :: DaemonOptions -> IO (Either ExitCode ())
handleMasterVerificationOptions opts =
  if optNoVoting opts
    then if optYesDoIt opts
           then return $ Right ()
           else do
             logError "The no-voting option is dangerous and cannot be\
                      \ given without providing yes-do-it as well."
             return . Left $ ExitFailure C.exitFailure
    else do
      masterStatus <- verifyMaster C.masterVotingRetries
      case masterStatus of
        Bad s -> do
          logError $ "Failed to verify master status: " ++ s
          return . Left $ ExitFailure C.exitFailure
        Ok _ -> return $ Right ()


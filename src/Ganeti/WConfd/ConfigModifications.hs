{-# LANGUAGE TemplateHaskell #-}

{-|  The WConfd functions for direct configuration manipulation

This module contains the client functions exported by WConfD for
specific configuration manipulation.

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

module Ganeti.WConfd.ConfigModifications where

import Control.Lens.Setter ((.~))
import Control.Lens.Traversal (mapMOf)
import Data.Maybe (isJust)
import Language.Haskell.TH (Name)

import Ganeti.JSON (alterContainerL)
import Ganeti.Locking.Locks (ClientId, ciIdentifier)
import Ganeti.Logging.Lifted (logDebug)
import Ganeti.Objects
import Ganeti.Objects.Lens
import Ganeti.WConfd.ConfigState (csConfigDataL)
import Ganeti.WConfd.Monad (WConfdMonad, modifyConfigWithLock)
import qualified Ganeti.WConfd.TempRes as T


-- | Add a new instance to the configuration, release DRBD minors,
-- and commit temporary IPs, all while temporarily holding the config
-- lock. Return True upon success and False if the config lock was not
-- available and the client should retry.
--
-- TODO: add verifications to this call; the client should have a lock
-- on the name of the instance, and no instance with the given uuid should
-- exist.
addInstance :: Instance -> ClientId -> WConfdMonad Bool
addInstance inst cid = do
  logDebug $ "AddInstance: client " ++ show (ciIdentifier cid)
             ++ " adding instance " ++ uuidOf inst
             ++ " with name " ++ show (instName inst)
  let addInst = csConfigDataL . configInstancesL . alterContainerL (uuidOf inst)
                  .~ Just inst
      commitRes tr = mapMOf csConfigDataL $ T.commitReservedIps cid tr
  r <- modifyConfigWithLock
         (\tr cs -> commitRes tr $ addInst  cs)
         . T.releaseDRBDMinors $ uuidOf inst
  logDebug $ "AddInstance: result of config modification is " ++ show r
  return $ isJust r

-- * The list of functions exported to RPC.

exportedFunctions :: [Name]
exportedFunctions = [ 'addInstance
                    ]

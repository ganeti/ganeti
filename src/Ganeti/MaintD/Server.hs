{-# LANGUAGE OverloadedStrings #-}

{-| Implementation of the Ganeti maintenenace server.

-}

{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.MaintD.Server
  ( options
  , main
  , checkMain
  , prepMain
  ) where

import Control.Applicative ((<|>))
import Snap.Core (Snap, method, Method(GET), ifTop)
import Snap.Http.Server (httpServe)
import Snap.Http.Server.Config (Config)

import qualified Ganeti.Constants as C
import Ganeti.Daemon ( OptType, CheckFn, PrepFn, MainFn, oDebug
                     , oNoVoting, oYesDoIt, oPort, oBindAddress, oNoDaemonize)
import Ganeti.Daemon.Utils (handleMasterVerificationOptions)
import Ganeti.Runtime (GanetiDaemon(GanetiMaintd))
import Ganeti.Utils.Http (httpConfFromOpts, plainJSON, error404)

-- | Options list and functions.
options :: [OptType]
options =
  [ oNoDaemonize
  , oDebug
  , oPort C.defaultMaintdPort
  , oBindAddress
  , oNoVoting
  , oYesDoIt
  ]

-- | Type alias for checkMain results.
type CheckResult = ()

-- | Type alias for prepMain results
type PrepResult = Config Snap ()

-- | The information to serve via HTTP
httpInterface :: Snap ()
httpInterface = ifTop (method GET $ plainJSON [1 :: Int])
                <|> error404

-- | Check function for luxid.
checkMain :: CheckFn CheckResult
checkMain = handleMasterVerificationOptions

-- | Prepare function for luxid.
prepMain :: PrepFn CheckResult PrepResult
prepMain opts _ = httpConfFromOpts GanetiMaintd opts

-- | Main function.
main :: MainFn CheckResult PrepResult
main _ _ httpConf =
  httpServe httpConf httpInterface

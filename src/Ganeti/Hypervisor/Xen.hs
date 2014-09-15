{-| Module to access the information provided by the Xen hypervisor.

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
module Ganeti.Hypervisor.Xen
  ( getDomainsInfo
  , getInferredDomInfo
  , getUptimeInfo
  --Data types to be re-exported from here
  , Domain(..)
  , UptimeInfo(..)
  ) where

import qualified Control.Exception as E
import Data.Attoparsec.Text as A
import qualified Data.Map as Map
import Data.Text (pack)
import System.Process

import qualified Ganeti.BasicTypes as BT
import qualified Ganeti.Constants as C
import Ganeti.Hypervisor.Xen.Types
import Ganeti.Hypervisor.Xen.XmParser
import Ganeti.Logging
import Ganeti.Utils


-- | Get information about the current Xen domains as a map where the domain
-- name is the key. This only includes the information made available by Xen
-- itself.
getDomainsInfo :: IO (BT.Result (Map.Map String Domain))
getDomainsInfo = do
  contents <-
        (E.try $ readProcess C.xenCmdXm ["list", "--long"] "")
          :: IO (Either IOError String)
  return $
    either (BT.Bad . show) (
      \c ->
        case A.parseOnly xmListParser $ pack c of
          Left msg -> BT.Bad msg
          Right dom -> BT.Ok dom
      ) contents

-- | Given a domain and a map containing information about multiple domains,
-- infer additional information about that domain (specifically, whether it is
-- hung).
inferDomInfos :: Map.Map String Domain -> Domain -> Domain
inferDomInfos domMap dom1 =
  case Map.lookup (domName dom1) domMap of
    Just dom2 ->
      dom1 { domIsHung = Just $ domCpuTime dom1 == domCpuTime dom2 }
    Nothing -> dom1 { domIsHung = Nothing }

-- | Get information about the current Xen domains as a map where the domain
-- name is the key. This includes information made available by Xen itself as
-- well as further information that can be inferred by querying Xen multiple
-- times and comparing the results.
getInferredDomInfo :: IO (BT.Result (Map.Map String Domain))
getInferredDomInfo = do
  domMap1 <- getDomainsInfo
  domMap2 <- getDomainsInfo
  case (domMap1, domMap2) of
    (BT.Bad m1, BT.Bad m2) -> return . BT.Bad $ m1 ++ "\n" ++ m2
    (BT.Bad m, BT.Ok d) -> do
      logWarning $ "Unable to retrieve domains info the first time" ++ m
      return $ BT.Ok d
    (BT.Ok d, BT.Bad m) -> do
      logWarning $ "Unable to retrieve domains info the second time" ++ m
      return $ BT.Ok d
    (BT.Ok d1, BT.Ok d2) -> return . BT.Ok $ fmap (inferDomInfos d2) d1

-- | Get information about the uptime of domains, as a map where the domain ID
-- is the key.
getUptimeInfo :: IO (Map.Map Int UptimeInfo)
getUptimeInfo = do
  contents <-
    ((E.try $ readProcess C.xenCmdXm ["uptime"] "")
      :: IO (Either IOError String)) >>=
      exitIfBad "running command" . either (BT.Bad . show) BT.Ok
  case A.parseOnly xmUptimeParser $ pack contents of
    Left msg -> exitErr msg
    Right uInfo -> return uInfo

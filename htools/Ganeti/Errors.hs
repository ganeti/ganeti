{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti error types.

This module implements our error hierarchy. Currently we implement one
identical to the Python one; later we might one to have separate ones
for frontend (clients), master and backend code.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.Errors
  ( ErrorCode(..)
  , GanetiException(..)
  , ErrorResult
  , excName
  ) where

import Text.JSON hiding (Result, Ok)

import Ganeti.THH
import Ganeti.BasicTypes
import qualified Ganeti.Constants as C

-- | Error code types for 'OpPrereqError'.
$(declareSADT "ErrorCode"
  [ ("ECodeResolver",  'C.errorsEcodeResolver)
  , ("ECodeNoRes",     'C.errorsEcodeNores)
  , ("ECodeInval",     'C.errorsEcodeInval)
  , ("ECodeState",     'C.errorsEcodeState)
  , ("ECodeNoEnt",     'C.errorsEcodeNoent)
  , ("ECodeExists",    'C.errorsEcodeExists)
  , ("ECodeNotUnique", 'C.errorsEcodeNotunique)
  , ("ECodeFault",     'C.errorsEcodeFault)
  , ("ECodeEnviron",   'C.errorsEcodeEnviron)
  ])
$(makeJSONInstance ''ErrorCode)

$(genException "GanetiException"
  [ ("GenericError", [excErrMsg])
  , ("LockError", [excErrMsg])
  , ("PidFileLockError", [excErrMsg])
  , ("HypervisorError", [excErrMsg])
  , ("ProgrammerError", [excErrMsg])
  , ("BlockDeviceError", [excErrMsg])
  , ("ConfigurationError", [excErrMsg])
  , ("ConfigVersionMismatch", [ ("expCode", [t| Int |])
                              , ("actCode", [t| Int |])])
  , ("ReservationError", [excErrMsg])
  , ("RemoteError", [excErrMsg])
  , ("SignatureError", [excErrMsg])
  , ("ParameterError", [excErrMsg])
  , ("ResultValidationError", [excErrMsg])
  , ("OpPrereqError", [excErrMsg, ("errCode", [t| ErrorCode |])])
  , ("OpExecError", [excErrMsg])
  , ("OpResultError", [excErrMsg])
  , ("OpCodeUnknown", [excErrMsg])
  , ("JobLost", [excErrMsg])
  , ("JobFileCorrupted", [excErrMsg])
  , ("ResolverError", [ ("errHostname", [t| String |])
                      , ("errResolverCode", [t| Int |])
                      , ("errResolverMsg", [t| String |])])
  , ("HooksFailure", [excErrMsg])
  , ("HooksAbort", [("errs", [t| [(String, String, String)] |])])
  , ("UnitParseError", [excErrMsg])
  , ("ParseError", [excErrMsg])
  , ("TypeEnforcementError", [excErrMsg])
  , ("X509CertError", [excErrMsg])
  , ("TagError", [excErrMsg])
  , ("CommandError", [excErrMsg])
  , ("StorageError", [excErrMsg])
  , ("InotifyError", [excErrMsg])
  , ("JobQueueError", [excErrMsg])
  , ("JobQueueDrainError", [excErrMsg])
  , ("JobQueueFull", [])
  , ("ConfdMagicError", [excErrMsg])
  , ("ConfdClientError", [excErrMsg])
  , ("UdpDataSizeError", [excErrMsg])
  , ("NoCtypesError", [excErrMsg])
  , ("IPAddressError", [excErrMsg])
  , ("LuxiError", [excErrMsg])
  , ("QueryFilterParseError", [excErrMsg]) -- not consistent with Python
  , ("RapiTestResult", [excErrMsg])
  , ("FileStoragePathError", [excErrMsg])
  ])

instance JSON GanetiException where
  showJSON = saveGanetiException
  readJSON = loadGanetiException

instance FromString GanetiException where
  mkFromString = GenericError

-- | Error monad using 'GanetiException' type alias.
type ErrorResult = GenericResult GanetiException

$(genStrOfOp ''GanetiException "excName")

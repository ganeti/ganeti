{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the Ganeti error types.

This module implements our error hierarchy. Currently we implement one
identical to the Python one; later we might one to have separate ones
for frontend (clients), master and backend code.

-}

{-

Copyright (C) 2012 Google Inc.
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

module Ganeti.Errors
  ( ErrorCode(..)
  , GanetiException(..)
  , ErrorResult
  , errToResult
  , errorExitCode
  , excName
  , formatError
  , ResultG
  , maybeToError
  ) where

import Text.JSON hiding (Result, Ok)
import System.Exit

import Ganeti.THH
import Ganeti.BasicTypes
import qualified Ganeti.Constants as C

-- | Error code types for 'OpPrereqError'.
$(declareSADT "ErrorCode"
  [ ("ECodeResolver",  'C.errorsEcodeResolver)
  , ("ECodeNoRes",     'C.errorsEcodeNores)
  , ("ECodeTempNoRes", 'C.errorsEcodeTempNores)
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
  , ("ConfigVerifyError", [excErrMsg, ("allErrors", [t| [String] |])])
  , ("ConfigVersionMismatch", [ ("expVer", [t| Int |])
                              , ("actVer", [t| Int |])])
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
  , ("X509CertError", [ ("certFileName", [t| String |])
                      , excErrMsg ])
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

instance Error GanetiException where
  strMsg = GenericError

instance JSON GanetiException where
  showJSON = saveGanetiException
  readJSON = loadGanetiException

-- | Error monad using 'GanetiException' type alias.
type ErrorResult = GenericResult GanetiException

$(genStrOfOp ''GanetiException "excName")

-- | Returns the exit code of a program that should be used if we got
-- back an exception from masterd.
errorExitCode :: GanetiException -> ExitCode
errorExitCode (ConfigurationError {}) = ExitFailure 2
errorExitCode (ConfigVerifyError {}) = ExitFailure 2
errorExitCode _ = ExitFailure 1

-- | Formats an exception.
formatError :: GanetiException -> String
formatError (ConfigurationError msg) =
  "Corrupt configuration file: " ++ msg ++ "\nAborting."
formatError (ConfigVerifyError msg es) =
  "Corrupt configuration file: " ++ msg ++ "\nAborting. Details:\n"
  ++ unlines es
formatError (HooksAbort errs) =
  unlines $
  "Failure: hooks execution failed:":
  map (\(node, script, out) ->
         "  node: " ++ node ++ ", script: " ++ script ++
                    if null out
                      then " (no output)"
                      else ", output: " ++ out
      ) errs
formatError (HooksFailure msg) =
  "Failure: hooks general failure: " ++ msg
formatError (ResolverError host _ _) =
  -- FIXME: in Python, this uses the system hostname to format the
  -- error differently if we are failing to resolve our own hostname
  "Failure: can't resolve hostname " ++ host
formatError (OpPrereqError msg code) =
  "Failure: prerequisites not met for this" ++
  " operation:\nerror type: " ++ show code ++ ", error details:\n" ++ msg
formatError (OpExecError msg) =
  "Failure: command execution error:\n" ++ msg
formatError (TagError msg) =
  "Failure: invalid tag(s) given:\n" ++ msg
formatError (JobQueueDrainError _)=
  "Failure: the job queue is marked for drain and doesn't accept new requests"
formatError JobQueueFull =
  "Failure: the job queue is full and doesn't accept new" ++
  " job submissions until old jobs are archived"
formatError (TypeEnforcementError msg) =
  "Parameter Error: " ++ msg
formatError (ParameterError msg) =
  "Failure: unknown/wrong parameter name '" ++ msg ++ "'"
formatError (JobLost msg) =
  "Error checking job status: " ++ msg
formatError (QueryFilterParseError msg) =
  -- FIXME: in Python, this has a more complex error message
  "Error while parsing query filter: " ++ msg
formatError (GenericError msg) =
  "Unhandled Ganeti error: " ++ msg
formatError err =
  "Unhandled exception: " ++ show err

-- | A type for IO actions with errors properly handled as
-- 'GanetiException's.
-- TODO: Move to Errors.hs
type ResultG = ResultT GanetiException IO

-- | Convert from an 'ErrorResult' to a standard 'Result'.
errToResult :: ErrorResult a -> Result a
errToResult (Ok a)  = Ok a
errToResult (Bad e) = Bad $ formatError e

-- | Convert from a 'Maybe' to a an 'ErrorResult'.
maybeToError :: String -> Maybe a -> ErrorResult a
maybeToError _ (Just a) = Ok a
maybeToError m  Nothing = Bad $ GenericError m

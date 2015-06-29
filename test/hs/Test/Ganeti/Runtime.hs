{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for "Ganeti.Runtime".

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

module Test.Ganeti.Runtime (testRuntime) where

import Test.HUnit
import qualified Text.JSON as J

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.Runtime

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Tests the compatibility between Haskell and Python log files.
case_LogFiles :: Assertion
case_LogFiles = do
  let daemons = [minBound..maxBound]::[GanetiDaemon]
      dnames = map daemonName daemons
  dfiles <- mapM daemonLogFile daemons
  let serialized = J.encode dnames
  py_stdout <-
    runPython "from ganeti import constants\n\
              \from ganeti import serializer\n\
              \import sys\n\
              \daemons = serializer.Load(sys.stdin.read())\n\
              \logfiles = [constants.DAEMONS_LOGFILES[d] for d in daemons]\n\
              \print serializer.Dump(logfiles)" serialized
    >>= checkPythonResult
  let deserialised = J.decode py_stdout::J.Result [String]
  decoded <- case deserialised of
               J.Ok ops -> return ops
               J.Error msg ->
                 assertFailure ("Unable to decode log files: " ++ msg)
                 -- this already raised an expection, but we need it
                 -- for proper types
                 >> fail "Unable to decode log files"
  assertEqual "Mismatch in number of returned log files"
    (length decoded) (length daemons)
  mapM_ (uncurry (assertEqual "Different result after encoding/decoding")
        ) $ zip dfiles decoded

-- | Tests the compatibility between Haskell and Python users.
case_UsersGroups :: Assertion
case_UsersGroups = do
  -- note: we don't have here a programatic way to list all users, so
  -- we harcode some parts of the two (hs/py) lists
  let daemons = [minBound..maxBound]::[GanetiDaemon]
      users = map daemonUser daemons
      groups = map daemonGroup $
               map DaemonGroup daemons ++ map ExtraGroup [minBound..maxBound]
  py_stdout <-
    runPython "from ganeti import constants\n\
              \from ganeti import serializer\n\
              \import sys\n\
              \users = [constants.MASTERD_USER,\n\
              \         constants.METAD_USER,\n\
              \         constants.NODED_USER,\n\
              \         constants.RAPI_USER,\n\
              \         constants.CONFD_USER,\n\
              \         constants.WCONFD_USER,\n\
              \         constants.KVMD_USER,\n\
              \         constants.LUXID_USER,\n\
              \         constants.MOND_USER,\n\
              \        ]\n\
              \groups = [constants.MASTERD_GROUP,\n\
              \          constants.METAD_GROUP,\n\
              \          constants.NODED_GROUP,\n\
              \          constants.RAPI_GROUP,\n\
              \          constants.CONFD_GROUP,\n\
              \          constants.WCONFD_GROUP,\n\
              \          constants.KVMD_GROUP,\n\
              \          constants.LUXID_GROUP,\n\
              \          constants.MOND_GROUP,\n\
              \          constants.DAEMONS_GROUP,\n\
              \          constants.ADMIN_GROUP,\n\
              \         ]\n\
              \encoded = (users, groups)\n\
              \print serializer.Dump(encoded)" ""
    >>= checkPythonResult
  let deserialised = J.decode py_stdout::J.Result ([String], [String])
  (py_users, py_groups) <-
    case deserialised of
      J.Ok ops -> return ops
      J.Error msg ->
        assertFailure ("Unable to decode users/groups: " ++ msg)
        -- this already raised an expection, but we need it for proper
        -- types
         >> fail "Unable to decode users/groups"
  assertEqual "Mismatch in number of returned users"
    (length py_users) (length users)
  assertEqual "Mismatch in number of returned users"
    (length py_groups) (length groups)
  mapM_ (uncurry (assertEqual "Different result for users")
        ) $ zip users py_users
  mapM_ (uncurry (assertEqual "Different result for groups")
        ) $ zip groups py_groups

testSuite "Runtime"
          [ 'case_LogFiles
          , 'case_UsersGroups
          ]

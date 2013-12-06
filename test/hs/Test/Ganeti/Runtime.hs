{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for "Ganeti.Runtime".

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
              \         constants.NODED_USER,\n\
              \         constants.RAPI_USER,\n\
              \         constants.CONFD_USER,\n\
              \         constants.WCONFD_USER,\n\
              \         constants.KVMD_USER,\n\
              \         constants.LUXID_USER,\n\
              \         constants.METAD_USER,\n\
              \         constants.MOND_USER,\n\
              \        ]\n\
              \groups = [constants.MASTERD_GROUP,\n\
              \          constants.NODED_GROUP,\n\
              \          constants.RAPI_GROUP,\n\
              \          constants.CONFD_GROUP,\n\
              \          constants.WCONFD_GROUP,\n\
              \          constants.KVMD_GROUP,\n\
              \          constants.LUXID_GROUP,\n\
              \          constants.METAD_GROUP,\n\
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

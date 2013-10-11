{-# LANGUAGE TemplateHaskell #-}
{-| Unittests for 'AutoConf'

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

module Test.AutoConf where

import qualified Data.Char as Char (isAlpha)
import Test.HUnit as HUnit

import qualified AutoConf
import qualified Test.Ganeti.TestHelper as TestHelper

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | 'isFilePath x' tests whether @x@ is a valid filepath
--
-- A valid filepath must be absolute and must not contain commas.
isFilePath :: String -> Bool
isFilePath ('/':str) = ',' `notElem` str
isFilePath _ = False

-- | 'isGntScript x' tests whether @x@ is a valid Ganeti script
--
-- A valid Ganeti script is prefixed by "gnt-" and the rest of the
-- 'String' contains only alphabetic 'Char's.
isGntScript :: String -> Bool
isGntScript str =
  case span (/= '-') str of
    (x, '-':y) -> x == "gnt" && all Char.isAlpha y
    _ -> False

-- | 'isGroup x' tests whether @x@ is a valid group name
--
-- A valid group name name is an alphabetic 'String' possibly
-- containing '-'.
isGroup :: String -> Bool
isGroup = all (\c -> Char.isAlpha c || c == '-')

-- | 'isProgram x' tests whether @x@ is a valid program name
--
-- A valid program name is an alphabetic 'String'.
isProgram :: String -> Bool
isProgram = all Char.isAlpha

-- | 'isUser x' tests whether @x@ is a valid username
--
-- See 'isGroup'.
isUser :: String -> Bool
isUser = isGroup

case_versionSuffix :: Assertion
case_versionSuffix =
  HUnit.assertBool
    "'versionSuffix' is invalid"
    (case AutoConf.versionSuffix of
        "" -> True
        '~':x -> not (null x)
        _ -> False)

case_localstatedir :: Assertion
case_localstatedir =
  HUnit.assertBool
    "'localstatedir' is invalid"
    (isFilePath AutoConf.localstatedir)

case_sysconfdir :: Assertion
case_sysconfdir =
  HUnit.assertBool
    "'sysconfdir' is invalid"
    (isFilePath AutoConf.sysconfdir)

case_sshConfigDir :: Assertion
case_sshConfigDir =
  HUnit.assertBool
    "'sshConfigDir' is invalid"
    (isFilePath AutoConf.sshConfigDir)

case_sshLoginUser :: Assertion
case_sshLoginUser =
  HUnit.assertBool
    "'sshLoginUser' is invalid"
    (isUser AutoConf.sshLoginUser)

case_sshConsoleUser :: Assertion
case_sshConsoleUser =
  HUnit.assertBool
    "'sshConsoleUser' is invalid"
    (isUser AutoConf.sshConsoleUser)

case_exportDir :: Assertion
case_exportDir =
  HUnit.assertBool
    "'exportDir' is invalid"
    (isFilePath AutoConf.exportDir)

case_osSearchPath :: Assertion
case_osSearchPath =
  HUnit.assertBool
    "'osSearchPath' is invalid"
    (all isFilePath AutoConf.osSearchPath)

case_esSearchPath :: Assertion
case_esSearchPath =
  HUnit.assertBool
    "'esSearchPath' is invalid"
    (all isFilePath AutoConf.esSearchPath)

case_xenBootloader :: Assertion
case_xenBootloader =
  HUnit.assertBool
    "'xenBootloader' is invalid"
    (null AutoConf.xenBootloader || isFilePath AutoConf.xenBootloader)

case_xenConfigDir :: Assertion
case_xenConfigDir =
  HUnit.assertBool
    "'xenConfigDir' is invalid"
    (isFilePath AutoConf.xenConfigDir)

case_xenKernel :: Assertion
case_xenKernel =
  HUnit.assertBool
    "'xenKernel' is invalid"
    (isFilePath AutoConf.xenKernel)

case_xenInitrd :: Assertion
case_xenInitrd =
  HUnit.assertBool
    "'xenInitrd' is invalid"
    (isFilePath AutoConf.xenInitrd)

case_kvmKernel :: Assertion
case_kvmKernel =
  HUnit.assertBool
    "'kvmKernel' is invalid"
    (isFilePath AutoConf.kvmKernel)

case_iallocatorSearchPath :: Assertion
case_iallocatorSearchPath =
  HUnit.assertBool
    "'iallocatorSearchPath' is invalid"
    (all isFilePath AutoConf.iallocatorSearchPath)

case_kvmPath :: Assertion
case_kvmPath =
  HUnit.assertBool
    "'kvmPath' is invalid"
    (isFilePath AutoConf.kvmPath)

case_ipPath :: Assertion
case_ipPath =
  HUnit.assertBool
    "'ipPath' is invalid"
    (isFilePath AutoConf.ipPath)

case_socatPath :: Assertion
case_socatPath =
  HUnit.assertBool
    "'socatPath' is invalid"
    (isFilePath AutoConf.socatPath)

case_toolsdir :: Assertion
case_toolsdir =
  HUnit.assertBool
    "'toolsdir' is invalid"
    (isFilePath AutoConf.toolsdir)

case_gntScripts :: Assertion
case_gntScripts =
  HUnit.assertBool
    "'gntScripts' is invalid"
    (all isGntScript AutoConf.gntScripts)

case_htoolsProgs :: Assertion
case_htoolsProgs =
  HUnit.assertBool
    "'htoolsProgs' is invalid"
    (all isProgram AutoConf.htoolsProgs)

case_pkglibdir :: Assertion
case_pkglibdir =
  HUnit.assertBool
    "'pkglibdir' is invalid"
    (isFilePath AutoConf.pkglibdir)

case_sharedir :: Assertion
case_sharedir =
  HUnit.assertBool
    "'sharedir' is invalid"
    (isFilePath AutoConf.sharedir)

case_versionedsharedir :: Assertion
case_versionedsharedir =
  HUnit.assertBool
    "'versionedsharedir' is invalid"
    (isFilePath AutoConf.versionedsharedir)

case_drbdBarriers :: Assertion
case_drbdBarriers =
  HUnit.assertBool
    "'drbdBarriers' is invalid"
    (AutoConf.drbdBarriers `elem` ["n", "bf"])

case_syslogUsage :: Assertion
case_syslogUsage =
  HUnit.assertBool
    "'syslogUsage' is invalid"
    (AutoConf.syslogUsage `elem` ["no", "yes", "only"])

case_daemonsGroup :: Assertion
case_daemonsGroup =
  HUnit.assertBool
    "'daemonsGroup' is invalid"
    (isGroup AutoConf.daemonsGroup)

case_adminGroup :: Assertion
case_adminGroup =
  HUnit.assertBool
    "'adminGroup' is invalid"
    (isGroup AutoConf.adminGroup)

case_masterdUser :: Assertion
case_masterdUser =
  HUnit.assertBool
    "'masterdUser' is invalid"
    (isUser AutoConf.masterdUser)

case_masterdGroup :: Assertion
case_masterdGroup =
  HUnit.assertBool
    "'masterdGroup' is invalid"
    (isGroup AutoConf.masterdGroup)

case_rapiUser :: Assertion
case_rapiUser =
  HUnit.assertBool
    "'rapiUser' is invalid"
    (isUser AutoConf.rapiUser)

case_rapiGroup :: Assertion
case_rapiGroup =
  HUnit.assertBool
    "'rapiGroup' is invalid"
    (isGroup AutoConf.rapiGroup)

case_confdUser :: Assertion
case_confdUser =
  HUnit.assertBool
    "'confdUser' is invalid"
    (isUser AutoConf.confdUser)

case_confdGroup :: Assertion
case_confdGroup =
  HUnit.assertBool
    "'confdGroup' is invalid"
    (isGroup AutoConf.confdGroup)

case_luxidUser :: Assertion
case_luxidUser =
  HUnit.assertBool
    "'luxidUser' is invalid"
    (isUser AutoConf.luxidUser)

case_luxidGroup :: Assertion
case_luxidGroup =
  HUnit.assertBool
    "'luxidGroup' is invalid"
    (isGroup AutoConf.luxidGroup)

case_nodedUser :: Assertion
case_nodedUser =
  HUnit.assertBool
    "'nodedUser' is invalid"
    (isUser AutoConf.nodedUser)

case_nodedGroup :: Assertion
case_nodedGroup =
  HUnit.assertBool
    "'nodedGroup' is invalid"
    (isGroup AutoConf.nodedGroup)

case_mondUser :: Assertion
case_mondUser =
  HUnit.assertBool
    "'mondUser' is invalid"
    (isUser AutoConf.mondUser)

case_mondGroup :: Assertion
case_mondGroup =
  HUnit.assertBool
    "'mondGroup' is invalid"
    (isUser AutoConf.mondGroup)

case_diskSeparator :: Assertion
case_diskSeparator =
  HUnit.assertBool
    "'diskSeparator' is invalid"
    (not (null AutoConf.diskSeparator))

case_qemuimgPath :: Assertion
case_qemuimgPath =
  HUnit.assertBool
    "'qemuimgPath' is invalid"
    (isFilePath AutoConf.qemuimgPath)

TestHelper.testSuite "AutoConf"
  [ 'case_versionSuffix
  , 'case_localstatedir
  , 'case_sysconfdir
  , 'case_sshConfigDir
  , 'case_sshLoginUser
  , 'case_sshConsoleUser
  , 'case_exportDir
  , 'case_osSearchPath
  , 'case_esSearchPath
  , 'case_xenBootloader
  , 'case_xenConfigDir
  , 'case_xenKernel
  , 'case_xenInitrd
  , 'case_kvmKernel
  , 'case_iallocatorSearchPath
  , 'case_kvmPath
  , 'case_ipPath
  , 'case_socatPath
  , 'case_toolsdir
  , 'case_gntScripts
  , 'case_htoolsProgs
  , 'case_pkglibdir
  , 'case_sharedir
  , 'case_versionedsharedir
  , 'case_drbdBarriers
  , 'case_syslogUsage
  , 'case_daemonsGroup
  , 'case_adminGroup
  , 'case_masterdUser
  , 'case_masterdGroup
  , 'case_rapiUser
  , 'case_rapiGroup
  , 'case_confdUser
  , 'case_confdGroup
  , 'case_luxidUser
  , 'case_luxidGroup
  , 'case_nodedUser
  , 'case_nodedGroup
  , 'case_mondUser
  , 'case_mondGroup
  , 'case_diskSeparator
  , 'case_qemuimgPath ]

#!/usr/bin/python
#

# Copyright (C) 2010, 2012, 2013 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""Script for testing tools/cfgupgrade"""

import os
import sys
import unittest
import shutil
import tempfile
import operator

from ganeti import constants
from ganeti import utils
from ganeti import serializer
from ganeti import netutils

from ganeti.utils import version

import testutils


def GetMinimalConfig():
  return {
    "version": constants.CONFIG_VERSION,
    "cluster": {
      "master_node": "node1-uuid",
      "ipolicy": None
    },
    "instances": {},
    "networks": {},
    "nodegroups": {},
    "nodes": {
      "node1-uuid": {
        "name": "node1",
        "uuid": "node1-uuid"
      }
    },
  }


def _RunUpgrade(path, dry_run, no_verify, ignore_hostname=True,
                downgrade=False):
  cmd = [sys.executable, "%s/tools/cfgupgrade" % testutils.GetSourceDir(),
         "--debug", "--force", "--path=%s" % path, "--confdir=%s" % path]

  if ignore_hostname:
    cmd.append("--ignore-hostname")
  if dry_run:
    cmd.append("--dry-run")
  if no_verify:
    cmd.append("--no-verify")
  if downgrade:
    cmd.append("--downgrade")

  result = utils.RunCmd(cmd, cwd=os.getcwd())
  if result.failed:
    raise Exception("cfgupgrade failed: %s, output %r" %
                    (result.fail_reason, result.output))


class TestCfgupgrade(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

    self.config_path = utils.PathJoin(self.tmpdir, "config.data")
    self.noded_cert_path = utils.PathJoin(self.tmpdir, "server.pem")
    self.rapi_cert_path = utils.PathJoin(self.tmpdir, "rapi.pem")
    self.rapi_users_path = utils.PathJoin(self.tmpdir, "rapi", "users")
    self.rapi_users_path_pre24 = utils.PathJoin(self.tmpdir, "rapi_users")
    self.known_hosts_path = utils.PathJoin(self.tmpdir, "known_hosts")
    self.confd_hmac_path = utils.PathJoin(self.tmpdir, "hmac.key")
    self.cds_path = utils.PathJoin(self.tmpdir, "cluster-domain-secret")
    self.ss_master_node_path = utils.PathJoin(self.tmpdir, "ssconf_master_node")
    self.file_storage_paths = utils.PathJoin(self.tmpdir, "file-storage-paths")

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _LoadConfig(self):
    return serializer.LoadJson(utils.ReadFile(self.config_path))

  def _LoadTestDataConfig(self, filename):
    return serializer.LoadJson(testutils.ReadTestData(filename))

  def _CreateValidConfigDir(self):
    utils.WriteFile(self.noded_cert_path, data="")
    utils.WriteFile(self.known_hosts_path, data="")
    utils.WriteFile(self.ss_master_node_path,
                    data="node.has.another.name.example.net")

  def testNoConfigDir(self):
    self.assertFalse(utils.ListVisibleFiles(self.tmpdir))
    self.assertRaises(Exception, _RunUpgrade, self.tmpdir, False, True)
    self.assertRaises(Exception, _RunUpgrade, self.tmpdir, True, True)

  def testWrongHostname(self):
    self._CreateValidConfigDir()

    utils.WriteFile(self.config_path,
                    data=serializer.DumpJson(GetMinimalConfig()))

    hostname = netutils.GetHostname().name
    assert hostname != utils.ReadOneLineFile(self.ss_master_node_path)

    self.assertRaises(Exception, _RunUpgrade, self.tmpdir, False, True,
                      ignore_hostname=False)

  def testCorrectHostname(self):
    self._CreateValidConfigDir()

    utils.WriteFile(self.config_path,
                    data=serializer.DumpJson(GetMinimalConfig()))

    utils.WriteFile(self.ss_master_node_path,
                    data="%s\n" % netutils.GetHostname().name)

    _RunUpgrade(self.tmpdir, False, True, ignore_hostname=False)

  def testInconsistentConfig(self):
    self._CreateValidConfigDir()
    # There should be no "config_version"
    cfg = GetMinimalConfig()
    cfg["version"] = 0
    cfg["cluster"]["config_version"] = 0
    utils.WriteFile(self.config_path, data=serializer.DumpJson(cfg))
    self.assertRaises(Exception, _RunUpgrade, self.tmpdir, False, True)

  def testInvalidConfig(self):
    self._CreateValidConfigDir()
    # Missing version from config
    utils.WriteFile(self.config_path, data=serializer.DumpJson({}))
    self.assertRaises(Exception, _RunUpgrade, self.tmpdir, False, True)

  def _TestUpgradeFromFile(self, filename, dry_run):
    cfg = self._LoadTestDataConfig(filename)
    self._TestUpgradeFromData(cfg, dry_run)

  def _TestSimpleUpgrade(self, from_version, dry_run,
                         file_storage_dir=None,
                         shared_file_storage_dir=None):
    cfg = GetMinimalConfig()
    cfg["version"] = from_version
    cluster = cfg["cluster"]

    if file_storage_dir:
      cluster["file_storage_dir"] = file_storage_dir
    if shared_file_storage_dir:
      cluster["shared_file_storage_dir"] = shared_file_storage_dir

    self._TestUpgradeFromData(cfg, dry_run)

  def _TestUpgradeFromData(self, cfg, dry_run):
    assert "version" in cfg
    from_version = cfg["version"]
    self._CreateValidConfigDir()
    utils.WriteFile(self.config_path, data=serializer.DumpJson(cfg))

    self.assertFalse(os.path.isfile(self.rapi_cert_path))
    self.assertFalse(os.path.isfile(self.confd_hmac_path))
    self.assertFalse(os.path.isfile(self.cds_path))

    _RunUpgrade(self.tmpdir, dry_run, True)

    if dry_run:
      expversion = from_version
      checkfn = operator.not_
    else:
      expversion = constants.CONFIG_VERSION
      checkfn = operator.truth

    self.assert_(checkfn(os.path.isfile(self.rapi_cert_path)))
    self.assert_(checkfn(os.path.isfile(self.confd_hmac_path)))
    self.assert_(checkfn(os.path.isfile(self.cds_path)))

    newcfg = self._LoadConfig()
    self.assertEqual(newcfg["version"], expversion)

  def testRapiUsers(self):
    self.assertFalse(os.path.exists(self.rapi_users_path))
    self.assertFalse(os.path.exists(self.rapi_users_path_pre24))
    self.assertFalse(os.path.exists(os.path.dirname(self.rapi_users_path)))

    utils.WriteFile(self.rapi_users_path_pre24, data="some user\n")
    self._TestSimpleUpgrade(version.BuildVersion(2, 3, 0), False)

    self.assertTrue(os.path.isdir(os.path.dirname(self.rapi_users_path)))
    self.assert_(os.path.islink(self.rapi_users_path_pre24))
    self.assert_(os.path.isfile(self.rapi_users_path))
    self.assertEqual(os.readlink(self.rapi_users_path_pre24),
                     self.rapi_users_path)
    for path in [self.rapi_users_path, self.rapi_users_path_pre24]:
      self.assertEqual(utils.ReadFile(path), "some user\n")

  def testRapiUsers24AndAbove(self):
    self.assertFalse(os.path.exists(self.rapi_users_path))
    self.assertFalse(os.path.exists(self.rapi_users_path_pre24))

    os.mkdir(os.path.dirname(self.rapi_users_path))
    utils.WriteFile(self.rapi_users_path, data="other user\n")
    self._TestSimpleUpgrade(version.BuildVersion(2, 3, 0), False)

    self.assert_(os.path.islink(self.rapi_users_path_pre24))
    self.assert_(os.path.isfile(self.rapi_users_path))
    self.assertEqual(os.readlink(self.rapi_users_path_pre24),
                     self.rapi_users_path)
    for path in [self.rapi_users_path, self.rapi_users_path_pre24]:
      self.assertEqual(utils.ReadFile(path), "other user\n")

  def testRapiUsersExistingSymlink(self):
    self.assertFalse(os.path.exists(self.rapi_users_path))
    self.assertFalse(os.path.exists(self.rapi_users_path_pre24))

    os.mkdir(os.path.dirname(self.rapi_users_path))
    os.symlink(self.rapi_users_path, self.rapi_users_path_pre24)
    utils.WriteFile(self.rapi_users_path, data="hello world\n")

    self._TestSimpleUpgrade(version.BuildVersion(2, 2, 0), False)

    self.assert_(os.path.isfile(self.rapi_users_path) and
                 not os.path.islink(self.rapi_users_path))
    self.assert_(os.path.islink(self.rapi_users_path_pre24))
    self.assertEqual(os.readlink(self.rapi_users_path_pre24),
                     self.rapi_users_path)
    for path in [self.rapi_users_path, self.rapi_users_path_pre24]:
      self.assertEqual(utils.ReadFile(path), "hello world\n")

  def testRapiUsersExistingTarget(self):
    self.assertFalse(os.path.exists(self.rapi_users_path))
    self.assertFalse(os.path.exists(self.rapi_users_path_pre24))

    os.mkdir(os.path.dirname(self.rapi_users_path))
    utils.WriteFile(self.rapi_users_path, data="other user\n")
    utils.WriteFile(self.rapi_users_path_pre24, data="hello world\n")

    self.assertRaises(Exception, self._TestSimpleUpgrade,
                      version.BuildVersion(2, 2, 0), False)

    for path in [self.rapi_users_path, self.rapi_users_path_pre24]:
      self.assert_(os.path.isfile(path) and not os.path.islink(path))
    self.assertEqual(utils.ReadFile(self.rapi_users_path), "other user\n")
    self.assertEqual(utils.ReadFile(self.rapi_users_path_pre24),
                     "hello world\n")

  def testRapiUsersDryRun(self):
    self.assertFalse(os.path.exists(self.rapi_users_path))
    self.assertFalse(os.path.exists(self.rapi_users_path_pre24))

    utils.WriteFile(self.rapi_users_path_pre24, data="some user\n")
    self._TestSimpleUpgrade(version.BuildVersion(2, 3, 0), True)

    self.assertFalse(os.path.isdir(os.path.dirname(self.rapi_users_path)))
    self.assertTrue(os.path.isfile(self.rapi_users_path_pre24) and
                    not os.path.islink(self.rapi_users_path_pre24))
    self.assertFalse(os.path.exists(self.rapi_users_path))

  def testRapiUsers24AndAboveDryRun(self):
    self.assertFalse(os.path.exists(self.rapi_users_path))
    self.assertFalse(os.path.exists(self.rapi_users_path_pre24))

    os.mkdir(os.path.dirname(self.rapi_users_path))
    utils.WriteFile(self.rapi_users_path, data="other user\n")
    self._TestSimpleUpgrade(version.BuildVersion(2, 3, 0), True)

    self.assertTrue(os.path.isfile(self.rapi_users_path) and
                    not os.path.islink(self.rapi_users_path))
    self.assertFalse(os.path.exists(self.rapi_users_path_pre24))
    self.assertEqual(utils.ReadFile(self.rapi_users_path), "other user\n")

  def testRapiUsersExistingSymlinkDryRun(self):
    self.assertFalse(os.path.exists(self.rapi_users_path))
    self.assertFalse(os.path.exists(self.rapi_users_path_pre24))

    os.mkdir(os.path.dirname(self.rapi_users_path))
    os.symlink(self.rapi_users_path, self.rapi_users_path_pre24)
    utils.WriteFile(self.rapi_users_path, data="hello world\n")

    self._TestSimpleUpgrade(version.BuildVersion(2, 2, 0), True)

    self.assertTrue(os.path.islink(self.rapi_users_path_pre24))
    self.assertTrue(os.path.isfile(self.rapi_users_path) and
                    not os.path.islink(self.rapi_users_path))
    self.assertEqual(os.readlink(self.rapi_users_path_pre24),
                     self.rapi_users_path)
    for path in [self.rapi_users_path, self.rapi_users_path_pre24]:
      self.assertEqual(utils.ReadFile(path), "hello world\n")

  def testFileStoragePathsDryRun(self):
    self.assertFalse(os.path.exists(self.file_storage_paths))

    self._TestSimpleUpgrade(version.BuildVersion(2, 6, 0), True,
                            file_storage_dir=self.tmpdir,
                            shared_file_storage_dir="/tmp")

    self.assertFalse(os.path.exists(self.file_storage_paths))

  def testFileStoragePathsBoth(self):
    self.assertFalse(os.path.exists(self.file_storage_paths))

    self._TestSimpleUpgrade(version.BuildVersion(2, 6, 0), False,
                            file_storage_dir=self.tmpdir,
                            shared_file_storage_dir="/tmp")

    lines = utils.ReadFile(self.file_storage_paths).splitlines()
    self.assertTrue(lines.pop(0).startswith("# "))
    self.assertTrue(lines.pop(0).startswith("# cfgupgrade"))
    self.assertEqual(lines.pop(0), self.tmpdir)
    self.assertEqual(lines.pop(0), "/tmp")
    self.assertFalse(lines)
    self.assertEqual(os.stat(self.file_storage_paths).st_mode & 0777,
                     0600, msg="Wrong permissions")

  def testFileStoragePathsSharedOnly(self):
    self.assertFalse(os.path.exists(self.file_storage_paths))

    self._TestSimpleUpgrade(version.BuildVersion(2, 5, 0), False,
                            file_storage_dir=None,
                            shared_file_storage_dir=self.tmpdir)

    lines = utils.ReadFile(self.file_storage_paths).splitlines()
    self.assertTrue(lines.pop(0).startswith("# "))
    self.assertTrue(lines.pop(0).startswith("# cfgupgrade"))
    self.assertEqual(lines.pop(0), self.tmpdir)
    self.assertFalse(lines)

  def testUpgradeFrom_2_0(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 0, 0), False)

  def testUpgradeFrom_2_1(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 1, 0), False)

  def testUpgradeFrom_2_2(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 2, 0), False)

  def testUpgradeFrom_2_3(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 3, 0), False)

  def testUpgradeFrom_2_4(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 4, 0), False)

  def testUpgradeFrom_2_5(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 5, 0), False)

  def testUpgradeFrom_2_6(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 6, 0), False)

  def testUpgradeFrom_2_7(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 7, 0), False)

  def testUpgradeFullConfigFrom_2_7(self):
    self._TestUpgradeFromFile("cluster_config_2.7.json", False)

  def testUpgradeFullConfigFrom_2_8(self):
    self._TestUpgradeFromFile("cluster_config_2.8.json", False)

  def testUpgradeCurrent(self):
    self._TestSimpleUpgrade(constants.CONFIG_VERSION, False)

  def _RunDowngradeUpgrade(self):
    oldconf = self._LoadConfig()
    _RunUpgrade(self.tmpdir, False, True, downgrade=True)
    _RunUpgrade(self.tmpdir, False, True)
    newconf = self._LoadConfig()
    self.assertEqual(oldconf, newconf)

  def testDowngrade(self):
    self._TestSimpleUpgrade(constants.CONFIG_VERSION, False)
    self._RunDowngradeUpgrade()

  def testDowngradeFullConfig(self):
    """Test for upgrade + downgrade combination."""
    # This test can work only with the previous version of a configuration!
    oldconfname = "cluster_config_2.9.json"
    self._TestUpgradeFromFile(oldconfname, False)
    _RunUpgrade(self.tmpdir, False, True, downgrade=True)
    oldconf = self._LoadTestDataConfig(oldconfname)
    newconf = self._LoadConfig()

    # downgrade from 2.10 to 2.9 does not add physical_id to disks, which is ok
    # TODO (2.11): Remove this code, it's not required to downgrade from 2.11
    #              to 2.10
    def RemovePhysicalId(disk):
      if "children" in disk:
        for d in disk["children"]:
          RemovePhysicalId(d)
      if "physical_id" in disk:
        del disk["physical_id"]

    for inst in oldconf["instances"].values():
      for disk in inst["disks"]:
        RemovePhysicalId(disk)

    self.assertEqual(oldconf, newconf)

  def testDowngradeFullConfigBackwardFrom_2_7(self):
    """Test for upgrade + downgrade + upgrade combination."""
    self._TestUpgradeFromFile("cluster_config_2.7.json", False)
    self._RunDowngradeUpgrade()

  def _RunDowngradeTwice(self):
    """Make sure that downgrade is idempotent."""
    _RunUpgrade(self.tmpdir, False, True, downgrade=True)
    oldconf = self._LoadConfig()
    _RunUpgrade(self.tmpdir, False, True, downgrade=True)
    newconf = self._LoadConfig()
    self.assertEqual(oldconf, newconf)

  def testDowngradeTwice(self):
    self._TestSimpleUpgrade(constants.CONFIG_VERSION, False)
    self._RunDowngradeTwice()

  def testDowngradeTwiceFullConfigFrom_2_7(self):
    self._TestUpgradeFromFile("cluster_config_2.7.json", False)
    self._RunDowngradeTwice()

  def testUpgradeDryRunFrom_2_0(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 0, 0), True)

  def testUpgradeDryRunFrom_2_1(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 1, 0), True)

  def testUpgradeDryRunFrom_2_2(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 2, 0), True)

  def testUpgradeDryRunFrom_2_3(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 3, 0), True)

  def testUpgradeDryRunFrom_2_4(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 4, 0), True)

  def testUpgradeDryRunFrom_2_5(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 5, 0), True)

  def testUpgradeDryRunFrom_2_6(self):
    self._TestSimpleUpgrade(version.BuildVersion(2, 6, 0), True)

  def testUpgradeCurrentDryRun(self):
    self._TestSimpleUpgrade(constants.CONFIG_VERSION, True)

  def testDowngradeDryRun(self):
    self._TestSimpleUpgrade(constants.CONFIG_VERSION, False)
    oldconf = self._LoadConfig()
    _RunUpgrade(self.tmpdir, True, True, downgrade=True)
    newconf = self._LoadConfig()
    self.assertEqual(oldconf["version"], newconf["version"])

if __name__ == "__main__":
  testutils.GanetiTestProgram()

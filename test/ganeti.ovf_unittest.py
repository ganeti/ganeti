#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.ovf.

"""

import optparse
import os
import os.path
import re
import shutil
import sys
import tempfile
import unittest

from ganeti import constants
from ganeti import errors
from ganeti import ovf
from ganeti import utils

import testutils

OUTPUT_DIR = "newdir"

GANETI_DISKS = {
  "disk_count": "1",
  "disk0_dump": "new_disk.raw",
  "disk0_size": "0",
  "disk0_ivname": "disk/0",
}
GANETI_NETWORKS = {
  "nic_count": "1",
  "nic0_mode": "bridged",
  "nic0_ip": "none",
  "nic0_mac": "aa:00:00:d8:2c:1e",
  "nic0_link": "xen-br0",
}
GANETI_HYPERVISOR = {
  "hypervisor_name": "xen-pvm",
  "root-path": "/dev/sda",
  "kernel_args": "ro",
}
GANETI_OS = {"os_name": "lenny-image"}
GANETI_BACKEND = {
  "vcpus": "1",
  "memory" : "2048",
  "auto_balance": "False",
}
GANETI_NAME = "ganeti-test-xen"
GANETI_TEMPLATE = "plain"
GANETI_TAGS = None
GANETI_VERSION = "0"

VIRTUALBOX_DISKS = {
  "disk_count": "2",
  "disk0_ivname": "disk/0",
  "disk0_dump": "new_disk.raw",
  "disk0_size": "0",
  "disk1_ivname": "disk/1",
  "disk1_dump": "second_disk.raw",
  "disk1_size": "0",
}
VIRTUALBOX_NETWORKS = {
  "nic_count": "1",
  "nic0_mode": "bridged",
  "nic0_ip": "none",
  "nic0_link": "auto",
  "nic0_mac": "auto",
}
VIRTUALBOX_HYPERVISOR = {"hypervisor_name": "auto"}
VIRTUALBOX_OS = {"os_name": None}
VIRTUALBOX_BACKEND = {
 "vcpus": "1",
  "memory" : "2048",
  "auto_balance": "auto",
}
VIRTUALBOX_NAME = None
VIRTUALBOX_TEMPLATE = None
VIRTUALBOX_TAGS = None
VIRTUALBOX_VERSION = None

EMPTY_DISKS = {}
EMPTY_NETWORKS = {}
EMPTY_HYPERVISOR = {"hypervisor_name": "auto"}
EMPTY_OS = {}
EMPTY_BACKEND = {
  "vcpus": "auto",
  "memory" : "auto",
  "auto_balance": "auto",
}
EMPTY_NAME = None
EMPTY_TEMPLATE = None
EMPTY_TAGS = None
EMPTY_VERSION = None

CMDARGS_DISKS = {
  "disk_count": "1",
  "disk0_ivname": "disk/0",
  "disk0_dump": "disk0.raw",
  "disk0_size": "8",
}
CMDARGS_NETWORKS = {
  "nic0_link": "auto",
  "nic0_mode": "bridged",
  "nic0_ip": "none",
  "nic0_mac": "auto",
  "nic_count": "1",
}
CMDARGS_HYPERVISOR = {
  "hypervisor_name": "xen-pvm"
}
CMDARGS_OS = {"os_name": "lenny-image"}
CMDARGS_BACKEND = {
  "auto_balance": False,
  "vcpus": "1",
  "memory": "256",
}
CMDARGS_NAME = "test-instance"
CMDARGS_TEMPLATE = "plain"
CMDARGS_TAGS = "test-tag-1,test-tag-2"

ARGS_EMPTY = {
  "output_dir": None,
  "nics": [],
  "disks": [],
  "name": "test-instance",
}
ARGS_EXPORT_DIR = dict(ARGS_EMPTY, **{
  "output_dir": OUTPUT_DIR,
  "name": None,
  "hypervisor": None,
  "os": None,
  "beparams": {},
  "no_nics": False,
  "disk_template": None,
  "tags": None,
})
ARGS_VBOX = dict(ARGS_EXPORT_DIR, **{
  "output_dir": OUTPUT_DIR,
  "name": "test-instance",
  "os": "lenny-image",
  "hypervisor": ("xen-pvm", {}),
  "osparams":{},
  "disks": [],
})
ARGS_COMPLETE = dict(ARGS_VBOX, **{
  "beparams": {"vcpus":"1", "memory":"256", "auto_balance": False},
  "disks": [(0,{"size":"5mb"})],
  "nics": [("0",{"mode":"bridged"})],
  "disk_template": "plain",
  "tags": "test-tag-1,test-tag-2",
})
ARGS_BROKEN = dict(ARGS_EXPORT_DIR , **{
  "no_nics": True,
  "disk_template": "diskless",
  "name": "test-instance",
  "os": "lenny-image",
  "osparams": {},
})


def _GetArgs(args, with_name=False):
  options = optparse.Values()
  needed = args
  if with_name:
    needed["name"] = "test-instance"
  options._update_loose(needed)
  return options


OPTS_EMPTY = _GetArgs(ARGS_EMPTY)
OPTS_EXPORT_NO_NAME = _GetArgs(ARGS_EXPORT_DIR)
OPTS_EXPORT = _GetArgs(ARGS_EXPORT_DIR, with_name=True)
OPTS_VBOX = _GetArgs(ARGS_VBOX)
OPTS_COMPLETE = _GetArgs(ARGS_COMPLETE)
OPTS_NONIC_NODISK = _GetArgs(ARGS_BROKEN)


def _GetFullFilename(file_name):
  file_path = "%s/test/data/ovfdata/%s" % (testutils.GetSourceDir(),
    file_name)
  file_path = os.path.abspath(file_path)
  return file_path


class BetterUnitTest(unittest.TestCase):
  def assertRaisesRegexp(self, exception, regexp_val, function, *args):
    try:
      function(*args)
      self.fail("Expected raising %s" % exception)
    except exception, err:
      regexp = re.compile(regexp_val)
      if re.search(regexp, str(err)) == None:
        self.fail("Expected matching '%s', got '%s'" %
          (regexp_val, str(err)))


class TestOVFImporter(BetterUnitTest):
  def setUp(self):
    self.non_existing_file = _GetFullFilename("not_the_file.ovf")
    self.ganeti_ovf = _GetFullFilename("ganeti.ovf")
    self.virtualbox_ovf = _GetFullFilename("virtualbox.ovf")
    self.ova_package = _GetFullFilename("ova.ova")
    self.empty_ovf = _GetFullFilename("empty.ovf")
    self.wrong_extension = _GetFullFilename("wrong_extension.ovd")
    self.wrong_ova_archive = _GetFullFilename("wrong_ova.ova")
    self.no_ovf_in_ova = _GetFullFilename("no_ovf.ova")
    self.importer = None

  def tearDown(self):
    if self.importer:
      self.importer.Cleanup()
    del_dir = os.path.abspath(OUTPUT_DIR)
    try:
      shutil.rmtree(del_dir)
    except OSError:
      pass

  def testFileDoesNotExistError(self):
    self.assertRaisesRegexp(errors.OpPrereqError, "does not exist",
      ovf.OVFImporter, self.non_existing_file, None)

  def testWrongInputFileExtensionError(self):
    self.assertRaisesRegexp(errors.OpPrereqError,
      "Unknown file extension", ovf.OVFImporter,
      self.wrong_extension, None)

  def testOVAUnpackingDirectories(self):
    self.importer = ovf.OVFImporter(self.ova_package, OPTS_EMPTY)
    self.assertTrue(self.importer.input_dir != None)
    self.assertEquals(self.importer.output_dir , constants.EXPORT_DIR)
    self.assertTrue(self.importer.temp_dir != None)

  def testOVFUnpackingDirectories(self):
    self.importer = ovf.OVFImporter(self.virtualbox_ovf,
      OPTS_EMPTY)
    self.assertEquals(self.importer.input_dir , _GetFullFilename(""))
    self.assertEquals(self.importer.output_dir , constants.EXPORT_DIR)
    self.assertEquals(self.importer.temp_dir , None)

  def testOVFSetOutputDirDirectories(self):
    self.importer = ovf.OVFImporter(self.ganeti_ovf, OPTS_EXPORT)
    self.assertEquals(self.importer.input_dir , _GetFullFilename(""))
    self.assertTrue(OUTPUT_DIR in self.importer.output_dir)
    self.assertEquals(self.importer.temp_dir , None)

  def testWrongOVAArchiveError(self):
    self.assertRaisesRegexp(errors.OpPrereqError, "not a proper tar",
      ovf.OVFImporter, self.wrong_ova_archive, None)

  def testNoOVFFileInOVAPackageError(self):
    self.assertRaisesRegexp(errors.OpPrereqError, "No .ovf file",
      ovf.OVFImporter, self.no_ovf_in_ova, None)

  def testParseGanetiOvf(self):
    self.importer = ovf.OVFImporter(self.ganeti_ovf, OPTS_EXPORT_NO_NAME)
    self.importer.Parse()
    self.assertTrue("%s/ganeti-test-xen" % OUTPUT_DIR in
      self.importer.output_dir)
    self.assertEqual(self.importer.results_disk, GANETI_DISKS)
    self.assertEqual(self.importer.results_network, GANETI_NETWORKS)
    self.assertEqual(self.importer.results_hypervisor, GANETI_HYPERVISOR)
    self.assertEqual(self.importer.results_os, GANETI_OS)
    self.assertEqual(self.importer.results_backend, GANETI_BACKEND)
    self.assertEqual(self.importer.results_name, GANETI_NAME)
    self.assertEqual(self.importer.results_template, GANETI_TEMPLATE)
    self.assertEqual(self.importer.results_tags, GANETI_TAGS)
    self.assertEqual(self.importer.results_version, GANETI_VERSION)

  def testParseVirtualboxOvf(self):
    self.importer = ovf.OVFImporter(self.virtualbox_ovf, OPTS_VBOX)
    self.importer.Parse()
    self.assertTrue("%s/test-instance" % OUTPUT_DIR in self.importer.output_dir)
    self.assertEquals(self.importer.results_disk, VIRTUALBOX_DISKS)
    self.assertEquals(self.importer.results_network, VIRTUALBOX_NETWORKS)
    self.assertEquals(self.importer.results_hypervisor, CMDARGS_HYPERVISOR)
    self.assertEquals(self.importer.results_os, CMDARGS_OS)
    self.assertEquals(self.importer.results_backend, VIRTUALBOX_BACKEND)
    self.assertEquals(self.importer.results_name, CMDARGS_NAME)
    self.assertEquals(self.importer.results_template, VIRTUALBOX_TEMPLATE)
    self.assertEqual(self.importer.results_tags, VIRTUALBOX_TAGS)
    self.assertEqual(self.importer.results_version, constants.EXPORT_VERSION)

  def testParseEmptyOvf(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    self.importer.Parse()
    self.assertTrue("%s/test-instance" % OUTPUT_DIR in self.importer.output_dir)
    self.assertEquals(self.importer.results_disk, CMDARGS_DISKS)
    self.assertEquals(self.importer.results_network, CMDARGS_NETWORKS)
    self.assertEquals(self.importer.results_hypervisor, CMDARGS_HYPERVISOR)
    self.assertEquals(self.importer.results_os, CMDARGS_OS)
    self.assertEquals(self.importer.results_backend, CMDARGS_BACKEND)
    self.assertEquals(self.importer.results_name, CMDARGS_NAME)
    self.assertEquals(self.importer.results_template, CMDARGS_TEMPLATE)
    self.assertEqual(self.importer.results_tags, CMDARGS_TAGS)
    self.assertEqual(self.importer.results_version, constants.EXPORT_VERSION)

  def testParseNameOptions(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    results = self.importer._ParseNameOptions()
    self.assertEquals(results, CMDARGS_NAME)

  def testParseHypervisorOptions(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    results = self.importer._ParseHypervisorOptions()
    self.assertEquals(results, CMDARGS_HYPERVISOR)

  def testParseOSOptions(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    results = self.importer._ParseOSOptions()
    self.assertEquals(results, CMDARGS_OS)

  def testParseBackendOptions(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    results = self.importer._ParseBackendOptions()
    self.assertEquals(results, CMDARGS_BACKEND)

  def testParseTags(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    results = self.importer._ParseTags()
    self.assertEquals(results, CMDARGS_TAGS)

  def testParseNicOptions(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    results = self.importer._ParseNicOptions()
    self.assertEquals(results, CMDARGS_NETWORKS)

  def testParseDiskOptionsFromGanetiOVF(self):
    self.importer = ovf.OVFImporter(self.ganeti_ovf, OPTS_EXPORT)
    os.mkdir(OUTPUT_DIR)
    results = self.importer._GetDiskInfo()
    self.assertEquals(results, GANETI_DISKS)

  def testParseTemplateOptions(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    results = self.importer._ParseTemplateOptions()
    self.assertEquals(results, GANETI_TEMPLATE)

  def testParseDiskOptionsFromCmdLine(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_COMPLETE)
    os.mkdir(OUTPUT_DIR)
    results = self.importer._ParseDiskOptions()
    self.assertEquals(results, CMDARGS_DISKS)

  def testGetDiskFormat(self):
    self.importer = ovf.OVFImporter(self.ganeti_ovf, OPTS_EXPORT)
    disks_list = self.importer.ovf_reader.GetDisksNames()
    results = [self.importer._GetDiskQemuInfo("%s/%s" %
      (self.importer.input_dir, path), "file format: (\S+)")
      for (path, _) in disks_list]
    self.assertEqual(results, ["vmdk"])

  def testNoInstanceNameOVF(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_EXPORT_NO_NAME)
    self.assertRaisesRegexp(errors.OpPrereqError, "Name of instance",
      self.importer.Parse)

  def testErrorNoOSNameOVF(self):
    self.importer = ovf.OVFImporter(self.virtualbox_ovf, OPTS_EXPORT)
    self.assertRaisesRegexp(errors.OpPrereqError, "OS name",
      self.importer.Parse)

  def testErrorNoDiskAndNoNetwork(self):
    self.importer = ovf.OVFImporter(self.empty_ovf, OPTS_NONIC_NODISK)
    self.assertRaisesRegexp(errors.OpPrereqError,
      "Either disk specification or network"
      " description", self.importer.Parse)


class TestOVFReader(BetterUnitTest):
  def setUp(self):
    self.wrong_xml_file = _GetFullFilename("wrong_xml.ovf")
    self.ganeti_ovf = _GetFullFilename("ganeti.ovf")
    self.virtualbox_ovf = _GetFullFilename("virtualbox.ovf")
    self.corrupted_ovf = _GetFullFilename("corrupted_resources.ovf")
    self.wrong_manifest_ovf = _GetFullFilename("wrong_manifest.ovf")
    self.no_disk_in_ref_ovf = _GetFullFilename("no_disk_in_ref.ovf")
    self.empty_ovf = _GetFullFilename("empty.ovf")
    self.compressed_disk = _GetFullFilename("gzip_disk.ovf")

  def tearDown(self):
    pass

  def testXMLParsingError(self):
    self.assertRaisesRegexp(errors.OpPrereqError,
      "Error while reading .ovf", ovf.OVFReader, self.wrong_xml_file)

  def testFileInResourcesDoesNotExistError(self):
    self.assertRaisesRegexp(errors.OpPrereqError, "does not exist",
      ovf.OVFReader, self.corrupted_ovf)

  def testWrongManifestChecksumError(self):
    reader = ovf.OVFReader(self.wrong_manifest_ovf)
    self.assertRaisesRegexp(errors.OpPrereqError,
      "does not match the value in manifest file", reader.VerifyManifest)

  def testGoodManifestChecksum(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    self.assertEqual(reader.VerifyManifest(), None)

  def testGetDisksNamesOVFCorruptedError(self):
    reader = ovf.OVFReader(self.no_disk_in_ref_ovf)
    self.assertRaisesRegexp(errors.OpPrereqError,
      "not found in references", reader.GetDisksNames)

  def testGetDisksNamesVirtualbox(self):
    reader = ovf.OVFReader(self.virtualbox_ovf)
    disk_names = reader.GetDisksNames()
    expected_names = [
      ("new_disk.vmdk", None) ,
      ("second_disk.vmdk", None),
    ]
    self.assertEqual(sorted(disk_names), sorted(expected_names))

  def testGetDisksNamesEmpty(self):
    reader = ovf.OVFReader(self.empty_ovf)
    disk_names = reader.GetDisksNames()
    self.assertEqual(disk_names, [])

  def testGetDisksNamesCompressed(self):
    reader = ovf.OVFReader(self.compressed_disk)
    disk_names = reader.GetDisksNames()
    self.assertEqual(disk_names, [("compr_disk.vmdk.gz", "gzip")])

  def testGetNetworkDataGaneti(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    networks = reader.GetNetworkData()
    self.assertEqual(networks, GANETI_NETWORKS)

  def testGetNetworkDataVirtualbox(self):
    reader = ovf.OVFReader(self.virtualbox_ovf)
    networks = reader.GetNetworkData()
    self.assertEqual(networks, VIRTUALBOX_NETWORKS)

  def testGetNetworkDataEmpty(self):
    reader = ovf.OVFReader(self.empty_ovf)
    networks = reader.GetNetworkData()
    self.assertEqual(networks, EMPTY_NETWORKS)

  def testGetHypervisorDataGaneti(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    hypervisor = reader.GetHypervisorData()
    self.assertEqual(hypervisor, GANETI_HYPERVISOR)

  def testGetHypervisorDataEmptyOvf(self):
    reader = ovf.OVFReader(self.empty_ovf)
    hypervisor = reader.GetHypervisorData()
    self.assertEqual(hypervisor, EMPTY_HYPERVISOR)

  def testGetOSDataGaneti(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    osys = reader.GetOSData()
    self.assertEqual(osys, GANETI_OS)

  def testGetOSDataEmptyOvf(self):
    reader = ovf.OVFReader(self.empty_ovf)
    osys = reader.GetOSData()
    self.assertEqual(osys, EMPTY_OS)

  def testGetBackendDataGaneti(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    backend = reader.GetBackendData()
    self.assertEqual(backend, GANETI_BACKEND)

  def testGetBackendDataVirtualbox(self):
    reader = ovf.OVFReader(self.virtualbox_ovf)
    backend = reader.GetBackendData()
    self.assertEqual(backend, VIRTUALBOX_BACKEND)

  def testGetBackendDataEmptyOvf(self):
    reader = ovf.OVFReader(self.empty_ovf)
    backend = reader.GetBackendData()
    self.assertEqual(backend, EMPTY_BACKEND)

  def testGetInstanceNameGaneti(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    name = reader.GetInstanceName()
    self.assertEqual(name, GANETI_NAME)

  def testGetInstanceNameDataEmptyOvf(self):
    reader = ovf.OVFReader(self.empty_ovf)
    name = reader.GetInstanceName()
    self.assertEqual(name, EMPTY_NAME)

  def testGetDiskTemplateGaneti(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    name = reader.GetDiskTemplate()
    self.assertEqual(name, GANETI_TEMPLATE)

  def testGetDiskTemplateEmpty(self):
    reader = ovf.OVFReader(self.empty_ovf)
    name = reader.GetDiskTemplate()
    self.assertEqual(name, EMPTY_TEMPLATE)

  def testGetTagsGaneti(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    tags = reader.GetTagsData()
    self.assertEqual(tags, GANETI_TAGS)

  def testGetTagsEmpty(self):
    reader = ovf.OVFReader(self.empty_ovf)
    tags = reader.GetTagsData()
    self.assertEqual(tags, EMPTY_TAGS)

  def testGetVersionGaneti(self):
    reader = ovf.OVFReader(self.ganeti_ovf)
    version = reader.GetVersionData()
    self.assertEqual(version, GANETI_VERSION)

  def testGetVersionEmpty(self):
    reader = ovf.OVFReader(self.empty_ovf)
    version = reader.GetVersionData()
    self.assertEqual(version, EMPTY_VERSION)


if __name__ == "__main__":
  testutils.GanetiTestProgram()

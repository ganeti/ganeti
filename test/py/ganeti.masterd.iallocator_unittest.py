#!/usr/bin/python3
#

# Copyright (C) 2012 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Script for testing ganeti.masterd.iallocator"""

import unittest

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import objects
from ganeti import ht
from ganeti.masterd import iallocator

import testutils


class _StubIAllocator(object):
  def __init__(self, success):
    self.success = success


class TestIAReqMultiInstanceAlloc(unittest.TestCase):
  def testResult(self):
    good_results = [
      # First result (all instances "allocate")
      [
        [["foo", ["a", "b"]],
         ["bar", ["c"]],
         ["baz", []]],
        []
      ],
      # Second result (partial "allocate", partial "fail")
      [
        [["bar", ["c", "b"]],
         ["baz", ["a"]]],
        ["foo"]
      ],
      # Third result (all instances "fail")
      [
        [],
        ["foo", "bar", "baz"]
      ],
      ]
    bad_results = [
      "foobar",
      1234,
      [],
      [[]],
      [[], [], []],
      ]

    result_fn = iallocator.IAReqMultiInstanceAlloc.REQ_RESULT

    self.assertTrue(compat.all(map(result_fn, good_results)))
    self.assertFalse(compat.any(map(result_fn, bad_results)))


class TestIARequestBase(unittest.TestCase):
  def testValidateResult(self):
    class _StubReqBase(iallocator.IARequestBase):
      MODE = constants.IALLOCATOR_MODE_ALLOC
      REQ_RESULT = ht.TBool

    stub = _StubReqBase()
    stub.ValidateResult(_StubIAllocator(True), True)
    self.assertRaises(errors.ResultValidationError, stub.ValidateResult,
                      _StubIAllocator(True), "foo")
    stub.ValidateResult(_StubIAllocator(False), True)
    # We don't validate the result if the iallocation request was not successful
    stub.ValidateResult(_StubIAllocator(False), "foo")


class _FakeConfigWithNdParams:
  def GetNdParams(self, _):
    return None


class TestComputeBasicNodeData(unittest.TestCase):
  def setUp(self):
    self.fn = compat.partial(iallocator.IAllocator._ComputeBasicNodeData,
                             _FakeConfigWithNdParams())

  def testEmpty(self):
    self.assertEqual(self.fn({}), {})

  def testSimple(self):
    node1 = objects.Node(name="node1",
                         primary_ip="192.0.2.1",
                         secondary_ip="192.0.2.2",
                         offline=False,
                         drained=False,
                         master_candidate=True,
                         master_capable=True,
                         group="11112222",
                         vm_capable=False)

    node2 = objects.Node(name="node2",
                         primary_ip="192.0.2.3",
                         secondary_ip="192.0.2.4",
                         offline=True,
                         drained=False,
                         master_candidate=False,
                         master_capable=False,
                         group="11112222",
                         vm_capable=True)

    assert node1 != node2

    ninfo = {
      "#unused-1#": node1,
      "#unused-2#": node2,
      }

    self.assertEqual(self.fn(ninfo), {
      "node1": {
        "tags": [],
        "primary_ip": "192.0.2.1",
        "secondary_ip": "192.0.2.2",
        "offline": False,
        "drained": False,
        "master_candidate": True,
        "group": "11112222",
        "master_capable": True,
        "vm_capable": False,
        "ndparams": None,
        },
      "node2": {
        "tags": [],
        "primary_ip": "192.0.2.3",
        "secondary_ip": "192.0.2.4",
        "offline": True,
        "drained": False,
        "master_candidate": False,
        "group": "11112222",
        "master_capable": False,
        "vm_capable": True,
        "ndparams": None,
        },
      })


class TestProcessStorageInfo(unittest.TestCase):

  def setUp(self):
    self.free_storage_file = 23
    self.total_storage_file = 42
    self.free_storage_lvm = 69
    self.total_storage_lvm = 666
    self.space_info = [{"name": "mynode",
                       "type": constants.ST_FILE,
                       "storage_free": self.free_storage_file,
                       "storage_size": self.total_storage_file},
                      {"name": "mynode",
                       "type": constants.ST_LVM_VG,
                       "storage_free": self.free_storage_lvm,
                       "storage_size": self.total_storage_lvm},
                      {"name": "mynode",
                       "type": constants.ST_LVM_PV,
                       "storage_free": 33,
                       "storage_size": 44}]

  def testComputeStorageDataFromNodeInfoDefault(self):
    has_lvm = False
    node_name = "mynode"
    (total_disk, free_disk, total_spindles, free_spindles) = \
        iallocator.IAllocator._ComputeStorageDataFromSpaceInfo(
            self.space_info, node_name, has_lvm)
    # FIXME: right now, iallocator ignores anything else than LVM, adjust
    # this test once that arbitrary storage is supported
    self.assertEqual(0, free_disk)
    self.assertEqual(0, total_disk)

  def testComputeStorageDataFromNodeInfoLvm(self):
    has_lvm = True
    node_name = "mynode"
    (total_disk, free_disk, total_spindles, free_spindles) = \
        iallocator.IAllocator._ComputeStorageDataFromSpaceInfo(
            self.space_info, node_name, has_lvm)
    self.assertEqual(self.free_storage_lvm, free_disk)
    self.assertEqual(self.total_storage_lvm, total_disk)

  def testComputeStorageDataFromSpaceInfoByTemplate(self):
    disk_template = constants.DT_FILE
    node_name = "mynode"
    (total_disk, free_disk, total_spindles, free_spindles) = \
        iallocator.IAllocator._ComputeStorageDataFromSpaceInfoByTemplate(
            self.space_info, node_name, disk_template)
    self.assertEqual(self.free_storage_file, free_disk)
    self.assertEqual(self.total_storage_file, total_disk)

  def testComputeStorageDataFromSpaceInfoByTemplateLvm(self):
    disk_template = constants.DT_PLAIN
    node_name = "mynode"
    (total_disk, free_disk, total_spindles, free_spindles) = \
        iallocator.IAllocator._ComputeStorageDataFromSpaceInfoByTemplate(
            self.space_info, node_name, disk_template)
    self.assertEqual(self.free_storage_lvm, free_disk)
    self.assertEqual(self.total_storage_lvm, total_disk)

  def testComputeStorageDataFromSpaceInfoByTemplateNoReport(self):
    disk_template = constants.DT_DISKLESS
    node_name = "mynode"
    (total_disk, free_disk, total_spindles, free_spindles) = \
        iallocator.IAllocator._ComputeStorageDataFromSpaceInfoByTemplate(
            self.space_info, node_name, disk_template)
    self.assertEqual(0, free_disk)
    self.assertEqual(0, total_disk)

if __name__ == "__main__":
  testutils.GanetiTestProgram()

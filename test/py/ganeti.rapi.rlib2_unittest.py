#!/usr/bin/python
#

# Copyright (C) 2010, 2012, 2013 Google Inc.
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


"""Script for unittesting the RAPI rlib2 module

"""


import unittest
import itertools
import random

from ganeti import constants
from ganeti import opcodes
from ganeti import compat
from ganeti import ht
from ganeti import http
from ganeti import query
import ganeti.rpc.errors as rpcerr
from ganeti import errors
from ganeti import rapi

from ganeti.rapi import rlib2
from ganeti.rapi import baserlib
from ganeti.rapi import connector

import testutils


class _FakeRequestPrivateData:
  def __init__(self, body_data):
    self.body_data = body_data


class _FakeRequest:
  def __init__(self, body_data):
    self.private = _FakeRequestPrivateData(body_data)


def _CreateHandler(cls, items, queryargs, body_data, client_cls):
  return cls(items, queryargs, _FakeRequest(body_data),
             _client_cls=client_cls)


class _FakeClient:
  def __init__(self, address=None):
    self._jobs = []

  def GetNextSubmittedJob(self):
    return self._jobs.pop(0)

  def SubmitJob(self, ops):
    job_id = str(1 + int(random.random() * 1000000))
    self._jobs.append((job_id, ops))
    return job_id


class _FakeClientFactory:
  def __init__(self, cls):
    self._client_cls = cls
    self._clients = []

  def GetNextClient(self):
    return self._clients.pop(0)

  def __call__(self, address=None):
    cl = self._client_cls(address=address)
    self._clients.append(cl)
    return cl


class RAPITestCase(testutils.GanetiTestCase):
  """Provides a few helper methods specific to RAPI testing.

  """
  def __init__(self, *args, **kwargs):
    """Creates a fake client factory the test may or may not use.

    """
    unittest.TestCase.__init__(self, *args, **kwargs)
    self._clfactory = _FakeClientFactory(_FakeClient)

  def assertNoNextClient(self, clfactory=None):
    """Insures that no further clients are present.

    """
    if clfactory is None:
      clfactory = self._clfactory

    self.assertRaises(IndexError, clfactory.GetNextClient)

  def getSubmittedOpcode(self, rapi_cls, items, query_args, body_data,
                         method_name, opcode_cls):
    """Submits a RAPI request and fetches the resulting opcode.

    """
    handler = _CreateHandler(rapi_cls, items, query_args, body_data,
                             self._clfactory)
    self.assertTrue(hasattr(handler, method_name),
                    "Handler lacks target method %s" % method_name)
    job_id = getattr(handler, method_name)()
    try:
      int(job_id)
    except ValueError:
      raise AssertionError("Returned value not job id; received %s" % job_id)

    cl = self._clfactory.GetNextClient()
    self.assertNoNextClient()

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id,
                     "Job IDs do not match: %s != %s" % (job_id, exp_job_id))
    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

    self.assertTrue(isinstance(op, opcode_cls),
                    "Wrong opcode class: expected %s, got %s" %
                    (opcode_cls.__name__, op.__class__.__name__))

    return op


class TestConstants(unittest.TestCase):
  def testConsole(self):
    # Exporting the console field without authentication might expose
    # information
    assert "console" in query.INSTANCE_FIELDS
    self.assertTrue("console" not in rlib2.I_FIELDS)

  def testFields(self):
    checks = {
      constants.QR_INSTANCE: rlib2.I_FIELDS,
      constants.QR_NODE: rlib2.N_FIELDS,
      constants.QR_GROUP: rlib2.G_FIELDS,
      }

    for (qr, fields) in checks.items():
      self.assertFalse(set(fields) - set(query.ALL_FIELDS[qr].keys()))


class TestClientConnectError(unittest.TestCase):
  @staticmethod
  def _FailingClient(address=None):
    raise rpcerr.NoMasterError("test")

  def test(self):
    resources = [
      rlib2.R_2_groups,
      rlib2.R_2_instances,
      rlib2.R_2_nodes,
      ]
    for cls in resources:
      handler = _CreateHandler(cls, ["name"], {}, None, self._FailingClient)
      self.assertRaises(http.HttpBadGateway, handler.GET)


class TestJobSubmitError(unittest.TestCase):
  class _SubmitErrorClient:
    def __init__(self, address=None):
      pass

    @staticmethod
    def SubmitJob(ops):
      raise errors.JobQueueFull("test")

  def test(self):
    handler = _CreateHandler(rlib2.R_2_redist_config, [], {}, None,
                             self._SubmitErrorClient)
    self.assertRaises(http.HttpServiceUnavailable, handler.PUT)


class TestClusterModify(RAPITestCase):
  def test(self):
    body_data = {
      "vg_name": "testvg",
      "candidate_pool_size": 100,
      }
    op = self.getSubmittedOpcode(rlib2.R_2_cluster_modify, [], {}, body_data,
                                 "PUT", opcodes.OpClusterSetParams)

    self.assertEqual(op.vg_name, "testvg")
    self.assertEqual(op.candidate_pool_size, 100)

  def testInvalidValue(self):
    for attr in ["vg_name", "candidate_pool_size", "beparams", "_-Unknown#"]:
      handler = _CreateHandler(rlib2.R_2_cluster_modify, [], {}, {
        attr: True,
        }, self._clfactory)
      self.assertRaises(http.HttpBadRequest, handler.PUT)
      self.assertNoNextClient()

  def testForbiddenParams(self):
    for attr, value in [
      ("compression_tools", ["lzop"]),
      ]:
      handler = _CreateHandler(rlib2.R_2_cluster_modify, [], {}, {
        attr: value,
        }, self._clfactory)
      self.assertRaises(http.HttpForbidden, handler.PUT)
      self.assertNoNextClient()


class TestRedistConfig(RAPITestCase):
  def test(self):
    self.getSubmittedOpcode(rlib2.R_2_redist_config, [], {}, None, "PUT",
                            opcodes.OpClusterRedistConf)


class TestNodeMigrate(RAPITestCase):
  def test(self):
    body_data = {
      "iallocator": "fooalloc",
      }
    op = self.getSubmittedOpcode(rlib2.R_2_nodes_name_migrate, ["node1"], {},
                                 body_data, "POST", opcodes.OpNodeMigrate)
    self.assertEqual(op.node_name, "node1")
    self.assertEqual(op.iallocator, "fooalloc")

  def testQueryArgsConflict(self):
    query_args = {
      "live": True,
      "mode": constants.HT_MIGRATION_NONLIVE,
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_migrate, ["node2"],
                             query_args, None, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)
    self.assertNoNextClient()

  def testQueryArgsMode(self):
    query_args = {
      "mode": [constants.HT_MIGRATION_LIVE],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_nodes_name_migrate, ["node17292"],
                                 query_args, None, "POST",
                                 opcodes.OpNodeMigrate)
    self.assertEqual(op.node_name, "node17292")
    self.assertEqual(op.mode, constants.HT_MIGRATION_LIVE)

  def testQueryArgsLive(self):
    clfactory = _FakeClientFactory(_FakeClient)

    for live in [False, True]:
      query_args = {
        "live": [str(int(live))],
        }
      op = self.getSubmittedOpcode(rlib2.R_2_nodes_name_migrate, ["node6940"],
                                   query_args, None, "POST",
                                   opcodes.OpNodeMigrate)

      self.assertEqual(op.node_name, "node6940")
      if live:
        self.assertEqual(op.mode, constants.HT_MIGRATION_LIVE)
      else:
        self.assertEqual(op.mode, constants.HT_MIGRATION_NONLIVE)


class TestNodeEvacuate(RAPITestCase):
  def test(self):
    query_args = {
      "dry-run": ["1"],
      }
    body_data = {
      "mode": constants.NODE_EVAC_SEC,
      }
    op = self.getSubmittedOpcode(rlib2.R_2_nodes_name_evacuate, ["node92"],
                                 query_args, body_data, "POST",
                                 opcodes.OpNodeEvacuate)
    self.assertEqual(op.node_name, "node92")
    self.assertEqual(op.mode, constants.NODE_EVAC_SEC)


class TestNodePowercycle(RAPITestCase):
  def test(self):
    query_args = {
      "force": ["1"],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_nodes_name_powercycle, ["node20744"],
                                 query_args, None, "POST",
                                 opcodes.OpNodePowercycle)
    self.assertEqual(op.node_name, "node20744")
    self.assertTrue(op.force)


class TestGroupAssignNodes(RAPITestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    query_args = {
      "dry-run": ["1"],
      "force": ["1"],
      }
    body_data = {
      "nodes": ["n2", "n3"],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_groups_name_assign_nodes, ["grp-a"],
                                 query_args, body_data, "PUT",
                                 opcodes.OpGroupAssignNodes)
    self.assertEqual(op.group_name, "grp-a")
    self.assertEqual(op.nodes, ["n2", "n3"])
    self.assertTrue(op.dry_run)
    self.assertTrue(op.force)


class TestInstanceDelete(RAPITestCase):
  def test(self):
    query_args = {
      "dry-run": ["1"],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name, ["inst30965"],
                                 query_args, {}, "DELETE",
                                 opcodes.OpInstanceRemove)

    self.assertEqual(op.instance_name, "inst30965")
    self.assertTrue(op.dry_run)
    self.assertFalse(op.ignore_failures)


class TestInstanceInfo(RAPITestCase):
  def test(self):
    query_args = {
      "static": ["1"],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_info, ["inst31217"],
                                 query_args, {}, "GET",
                                 opcodes.OpInstanceQueryData)

    self.assertEqual(op.instances, ["inst31217"])
    self.assertTrue(op.static)


class TestInstanceReboot(RAPITestCase):
  def test(self):
    query_args = {
      "dry-run": ["1"],
      "ignore_secondaries": ["1"],
      "reason": ["System update"],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_reboot, ["inst847"],
                                 query_args, {}, "POST",
                                 opcodes.OpInstanceReboot)

    self.assertEqual(op.instance_name, "inst847")
    self.assertEqual(op.reboot_type, constants.INSTANCE_REBOOT_HARD)
    self.assertTrue(op.ignore_secondaries)
    self.assertTrue(op.dry_run)
    self.assertEqual(op.reason[0][0], constants.OPCODE_REASON_SRC_USER)
    self.assertEqual(op.reason[0][1], "System update")
    self.assertEqual(op.reason[1][0],
                     "%s:%s" % (constants.OPCODE_REASON_SRC_RLIB2,
                                "instances_name_reboot"))
    self.assertEqual(op.reason[1][1], "")


class TestInstanceStartup(RAPITestCase):
  def test(self):
    query_args = {
      "force": ["1"],
      "no_remember": ["1"],
      "reason": ["Newly created instance"],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_startup,
                                 ["inst31083"], query_args, {}, "PUT",
                                 opcodes.OpInstanceStartup)

    self.assertEqual(op.instance_name, "inst31083")
    self.assertTrue(op.no_remember)
    self.assertTrue(op.force)
    self.assertFalse(op.dry_run)
    self.assertEqual(op.reason[0][0], constants.OPCODE_REASON_SRC_USER)
    self.assertEqual(op.reason[0][1], "Newly created instance")
    self.assertEqual(op.reason[1][0],
                     "%s:%s" % (constants.OPCODE_REASON_SRC_RLIB2,
                                "instances_name_startup"))
    self.assertEqual(op.reason[1][1], "")


class TestInstanceShutdown(RAPITestCase):
  def test(self):
    query_args = {
      "no_remember": ["0"],
      "reason": ["Not used anymore"],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_shutdown,
                                 ["inst26791"], query_args, {}, "PUT",
                                 opcodes.OpInstanceShutdown)

    self.assertEqual(op.instance_name, "inst26791")
    self.assertFalse(op.no_remember)
    self.assertFalse(op.dry_run)
    self.assertEqual(op.reason[0][0], constants.OPCODE_REASON_SRC_USER)
    self.assertEqual(op.reason[0][1], "Not used anymore")
    self.assertEqual(op.reason[1][0],
                     "%s:%s" % (constants.OPCODE_REASON_SRC_RLIB2,
                                "instances_name_shutdown"))
    self.assertEqual(op.reason[1][1], "")


class TestInstanceActivateDisks(RAPITestCase):
  def test(self):
    query_args = {
      "ignore_size": ["1"],
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_activate_disks,
                                 ["xyz"], query_args, {}, "PUT",
                                 opcodes.OpInstanceActivateDisks)

    self.assertEqual(op.instance_name, "xyz")
    self.assertTrue(op.ignore_size)
    self.assertFalse(op.dry_run)


class TestInstanceDeactivateDisks(RAPITestCase):
  def test(self):
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_deactivate_disks,
                                 ["inst22357"], {}, {}, "PUT",
                                 opcodes.OpInstanceDeactivateDisks)

    self.assertEqual(op.instance_name, "inst22357")
    self.assertFalse(op.dry_run)
    self.assertFalse(op.force)


class TestInstanceRecreateDisks(RAPITestCase):
  def test(self):
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_recreate_disks,
                                 ["inst22357"], {}, {}, "POST",
                                 opcodes.OpInstanceRecreateDisks)

    self.assertEqual(op.instance_name, "inst22357")
    self.assertFalse(op.dry_run)
    self.assertTrue(op.iallocator is None)
    self.assertFalse(hasattr(op, "force"))

  def testCustomParameters(self):
    data = {
      "iallocator": "hail",
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_recreate_disks,
                                 ["inst22357"], {}, data, "POST",
                                 opcodes.OpInstanceRecreateDisks)
    self.assertEqual(op.instance_name, "inst22357")
    self.assertEqual(op.iallocator, "hail")
    self.assertFalse(op.dry_run)


class TestInstanceFailover(RAPITestCase):
  def test(self):
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_failover,
                                 ["inst12794"], {}, {}, "PUT",
                                 opcodes.OpInstanceFailover)

    self.assertEqual(op.instance_name, "inst12794")
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))


class TestInstanceDiskGrow(RAPITestCase):
  def test(self):
    data = {
      "amount": 1024,
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_disk_grow,
                                 ["inst10742", "3"], {}, data, "POST",
                                 opcodes.OpInstanceGrowDisk)

    self.assertEqual(op.instance_name, "inst10742")
    self.assertEqual(op.disk, 3)
    self.assertEqual(op.amount, 1024)
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))


class TestInstanceModify(RAPITestCase):
  def testCustomParamRename(self):
    name = "instant_instance"
    data = {
      "custom_beparams": {},
      "custom_hvparams": {},
      }

    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_modify, [name], {},
                                 data, "PUT", opcodes.OpInstanceSetParams)

    self.assertEqual(op.beparams, {})
    self.assertEqual(op.hvparams, {})

    # Define both
    data["beparams"] = {}
    assert "beparams" in data and "custom_beparams" in data
    handler = _CreateHandler(rlib2.R_2_instances_name_modify, [name], {}, data,
                             self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)


class TestBackupPrepare(RAPITestCase):
  def test(self):
    query_args = {
      "mode": constants.EXPORT_MODE_REMOTE,
      }
    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_prepare_export,
                                 ["inst17925"], query_args, {}, "PUT",
                                 opcodes.OpBackupPrepare)

    self.assertEqual(op.instance_name, "inst17925")
    self.assertEqual(op.mode, constants.EXPORT_MODE_REMOTE)
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))


class TestGroupRemove(RAPITestCase):
  def test(self):
    op = self.getSubmittedOpcode(rlib2.R_2_groups_name, ["grp28575"], {}, {},
                                 "DELETE", opcodes.OpGroupRemove)

    self.assertEqual(op.group_name, "grp28575")
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))


class TestStorageQuery(RAPITestCase):
  def test(self):
    query_args = {
      "storage_type": constants.ST_LVM_PV,
      "output_fields": "name,other",
      }
    op = self.getSubmittedOpcode(rlib2.R_2_nodes_name_storage, ["node21075"],
                                 query_args, {}, "GET",
                                 opcodes.OpNodeQueryStorage)

    self.assertEqual(op.nodes, ["node21075"])
    self.assertEqual(op.storage_type, constants.ST_LVM_PV)
    self.assertEqual(op.output_fields, ["name", "other"])
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))

  def testErrors(self):
    # storage type which does not support space reporting
    queryargs = {
      "storage_type": constants.ST_DISKLESS,
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage,
                             ["node21273"], queryargs, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.GET)

    queryargs = {
      "storage_type": constants.ST_LVM_VG,
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage,
                             ["node21273"], queryargs, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.GET)

    queryargs = {
      "storage_type": "##unknown_storage##",
      "output_fields": "name,other",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage,
                             ["node10315"], queryargs, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.GET)


class TestStorageModify(RAPITestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    for allocatable in [None, "1", "0"]:
      query_args = {
        "storage_type": constants.ST_LVM_VG,
        "name": "pv-a",
        }

      if allocatable is not None:
        query_args["allocatable"] = allocatable

      op = self.getSubmittedOpcode(rlib2.R_2_nodes_name_storage_modify,
                                   ["node9292"], query_args, {}, "PUT",
                                   opcodes.OpNodeModifyStorage)

      self.assertEqual(op.node_name, "node9292")
      self.assertEqual(op.storage_type, constants.ST_LVM_VG)
      self.assertEqual(op.name, "pv-a")
      if allocatable is None:
        self.assertFalse(op.changes)
      else:
        assert allocatable in ("0", "1")
        self.assertEqual(op.changes, {
          constants.SF_ALLOCATABLE: (allocatable == "1"),
          })
      self.assertFalse(op.dry_run)
      self.assertFalse(hasattr(op, "force"))

  def testErrors(self):
    # No storage type
    queryargs = {
      "name": "xyz",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_modify,
                             ["node26016"], queryargs, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)

    # No name
    queryargs = {
      "storage_type": constants.ST_LVM_VG,
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_modify,
                             ["node21218"], queryargs, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)

    # Invalid value
    queryargs = {
      "storage_type": constants.ST_LVM_VG,
      "name": "pv-b",
      "allocatable": "noint",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_modify,
                             ["node30685"], queryargs, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)


class TestStorageRepair(RAPITestCase):
  def test(self):
    query_args = {
      "storage_type": constants.ST_LVM_PV,
      "name": "pv16611",
      }
    op = self.getSubmittedOpcode(rlib2.R_2_nodes_name_storage_repair,
                                 ["node19265"], query_args, {}, "PUT",
                                 opcodes.OpRepairNodeStorage)

    self.assertEqual(op.node_name, "node19265")
    self.assertEqual(op.storage_type, constants.ST_LVM_PV)
    self.assertEqual(op.name, "pv16611")
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))

  def testErrors(self):
    # No storage type
    queryargs = {
      "name": "xyz",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_repair,
                             ["node11275"], queryargs, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)

    # No name
    queryargs = {
      "storage_type": constants.ST_LVM_VG,
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_repair,
                             ["node21218"], queryargs, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)


class TestTags(RAPITestCase):
  TAG_HANDLERS = [
    rlib2.R_2_instances_name_tags,
    rlib2.R_2_nodes_name_tags,
    rlib2.R_2_groups_name_tags,
    rlib2.R_2_tags,
    ]

  def testSetAndDelete(self):
    for method, opcls in [("PUT", opcodes.OpTagsSet),
                          ("DELETE", opcodes.OpTagsDel)]:
      for idx, handler in enumerate(self.TAG_HANDLERS):
        dry_run = bool(idx % 2)
        name = "test%s" % idx
        queryargs = {
          "tag": ["foo", "bar", "baz"],
          "dry-run": str(int(dry_run)),
          }

        op = self.getSubmittedOpcode(handler, [name], queryargs, {}, method,
                                     opcls)

        self.assertEqual(op.kind, handler.TAG_LEVEL)
        if handler.TAG_LEVEL == constants.TAG_CLUSTER:
          self.assertTrue(op.name is None)
        else:
          self.assertEqual(op.name, name)
        self.assertEqual(op.tags, ["foo", "bar", "baz"])
        self.assertEqual(op.dry_run, dry_run)
        self.assertFalse(hasattr(op, "force"))


class TestInstanceCreation(RAPITestCase):
  def test(self):
    name = "inst863.example.com"

    disk_variants = [
      # No disks
      [],

      # Two disks
      [{"size": 5, }, {"size": 100, }],

      # Disk with mode
      [{"size": 123, "mode": constants.DISK_RDWR, }],
      ]

    nic_variants = [
      # No NIC
      [],

      # Three NICs
      [{}, {}, {}],

      # Two NICs
      [
        { "ip": "192.0.2.6", "mode": constants.NIC_MODE_ROUTED,
          "mac": "01:23:45:67:68:9A",
        },
        { "mode": constants.NIC_MODE_BRIDGED, "link": "br1" },
      ],
      ]

    beparam_variants = [
      None,
      {},
      { constants.BE_VCPUS: 2, },
      { constants.BE_MAXMEM: 200, },
      { constants.BE_MEMORY: 256, },
      { constants.BE_VCPUS: 2,
        constants.BE_MAXMEM: 1024,
        constants.BE_MINMEM: 1024,
        constants.BE_AUTO_BALANCE: True,
        constants.BE_ALWAYS_FAILOVER: True, }
      ]

    hvparam_variants = [
      None,
      { constants.HV_BOOT_ORDER: "anc", },
      { constants.HV_KERNEL_PATH: "/boot/fookernel",
        constants.HV_ROOT_PATH: "/dev/hda1", },
      ]

    for mode in [constants.INSTANCE_CREATE, constants.INSTANCE_IMPORT]:
      for nics in nic_variants:
        for disk_template in constants.DISK_TEMPLATES:
          for disks in disk_variants:
            for beparams in beparam_variants:
              for hvparams in hvparam_variants:
                for dry_run in [False, True]:
                  query_args = {
                    "dry-run": str(int(dry_run)),
                    }

                  data = {
                    rlib2._REQ_DATA_VERSION: 1,
                    "name": name,
                    "hypervisor": constants.HT_FAKE,
                    "disks": disks,
                    "nics": nics,
                    "mode": mode,
                    "disk_template": disk_template,
                    "os": "debootstrap",
                    }

                  if beparams is not None:
                    data["beparams"] = beparams

                  if hvparams is not None:
                    data["hvparams"] = hvparams

                  op = self.getSubmittedOpcode(
                    rlib2.R_2_instances, [], query_args, data, "POST",
                    opcodes.OpInstanceCreate
                  )

                  self.assertEqual(op.instance_name, name)
                  self.assertEqual(op.mode, mode)
                  self.assertEqual(op.disk_template, disk_template)
                  self.assertEqual(op.dry_run, dry_run)
                  self.assertEqual(len(op.disks), len(disks))
                  self.assertEqual(len(op.nics), len(nics))

                  for opdisk, disk in zip(op.disks, disks):
                    for key in constants.IDISK_PARAMS:
                      self.assertEqual(opdisk.get(key), disk.get(key))
                    self.assertFalse("unknown" in opdisk)

                  for opnic, nic in zip(op.nics, nics):
                    for key in constants.INIC_PARAMS:
                      self.assertEqual(opnic.get(key), nic.get(key))
                    self.assertFalse("unknown" in opnic)
                    self.assertFalse("foobar" in opnic)

                  if beparams is None:
                    self.assertTrue(op.beparams in [None, {}])
                  else:
                    self.assertEqualValues(op.beparams, beparams)

                  if hvparams is None:
                    self.assertTrue(op.hvparams in [None, {}])
                  else:
                    self.assertEqualValues(op.hvparams, hvparams)

  def testLegacyName(self):
    name = "inst29128.example.com"
    data = {
      rlib2._REQ_DATA_VERSION: 1,
      "name": name,
      "disks": [],
      "nics": [],
      "mode": constants.INSTANCE_CREATE,
      "disk_template": constants.DT_PLAIN,
      }

    op = self.getSubmittedOpcode(rlib2.R_2_instances, [], {}, data, "POST",
                                 opcodes.OpInstanceCreate)

    self.assertEqual(op.instance_name, name)
    self.assertFalse(hasattr(op, "name"))
    self.assertFalse(op.dry_run)

    # Define both
    data["instance_name"] = "other.example.com"
    assert "name" in data and "instance_name" in data
    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)
    self.assertNoNextClient()

  def testLegacyOs(self):
    name = "inst4673.example.com"
    os = "linux29206"
    data = {
      rlib2._REQ_DATA_VERSION: 1,
      "name": name,
      "os_type": os,
      "disks": [],
      "nics": [],
      "mode": constants.INSTANCE_CREATE,
      "disk_template": constants.DT_PLAIN,
      }

    op = self.getSubmittedOpcode(rlib2.R_2_instances, [], {}, data, "POST",
                                 opcodes.OpInstanceCreate)

    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.os_type, os)
    self.assertFalse(hasattr(op, "os"))
    self.assertFalse(op.dry_run)

    # Define both
    data["os"] = "linux9584"
    assert "os" in data and "os_type" in data
    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)

  def testErrors(self):
    # Test all required fields
    reqfields = {
      rlib2._REQ_DATA_VERSION: 1,
      "name": "inst1.example.com",
      "disks": [],
      "nics": [],
      "mode": constants.INSTANCE_CREATE,
      }

    for name in reqfields.keys():
      data = dict(i for i in reqfields.items() if i[0] != name)

      handler = _CreateHandler(rlib2.R_2_instances, [], {}, data,
                               self._clfactory)
      self.assertRaises(http.HttpBadRequest, handler.POST)
      self.assertNoNextClient()

    # Invalid disks and nics
    for field in ["disks", "nics"]:
      invalid_values = [None, 1, "", {}, [1, 2, 3], ["hda1", "hda2"],
                        [{"_unknown_": False, }]]

      for invvalue in invalid_values:
        data = reqfields.copy()
        data[field] = invvalue
        handler = _CreateHandler(rlib2.R_2_instances, [], {}, data,
                                 self._clfactory)
        self.assertRaises(http.HttpBadRequest, handler.POST)
        self.assertNoNextClient()

  def testVersion(self):
    # No version field
    data = {
      "name": "inst1.example.com",
      "disks": [],
      "nics": [],
      "mode": constants.INSTANCE_CREATE,
      "disk_template": constants.DT_PLAIN,
      }

    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)

    # Old and incorrect versions
    for version in [0, -1, 10483, "Hello World"]:
      data[rlib2._REQ_DATA_VERSION] = version

      handler = _CreateHandler(rlib2.R_2_instances, [], {}, data,
                               self._clfactory)
      self.assertRaises(http.HttpBadRequest, handler.POST)
      self.assertNoNextClient()

    # Correct version
    data[rlib2._REQ_DATA_VERSION] = 1
    self.getSubmittedOpcode(rlib2.R_2_instances, [], {}, data, "POST",
                            opcodes.OpInstanceCreate)


class TestBackupExport(RAPITestCase):
  def test(self):
    name = "instmoo"
    data = {
      "mode": constants.EXPORT_MODE_REMOTE,
      "destination": [(1, 2, 3), (99, 99, 99)],
      "shutdown": True,
      "remove_instance": True,
      "x509_key_name": ["name", "hash"],
      "destination_x509_ca": "---cert---"
      }

    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_export, [name], {},
                                 data, "PUT", opcodes.OpBackupExport)

    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.mode, constants.EXPORT_MODE_REMOTE)
    self.assertEqual(op.target_node, [(1, 2, 3), (99, 99, 99)])
    self.assertEqual(op.shutdown, True)
    self.assertEqual(op.remove_instance, True)
    self.assertEqual(op.x509_key_name, ["name", "hash"])
    self.assertEqual(op.destination_x509_ca, "---cert---")
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))

  def testDefaults(self):
    name = "inst1"
    data = {
      "destination": "node2",
      "shutdown": False,
      }

    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_export, [name], {},
                                 data, "PUT", opcodes.OpBackupExport)

    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.target_node, "node2")
    self.assertEqual(op.mode, "local")
    self.assertFalse(op.remove_instance)
    self.assertFalse(hasattr(op, "destination"))
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))

  def testErrors(self):
    clfactory = _FakeClientFactory(_FakeClient)

    for value in ["True", "False"]:
      data = {
        "remove_instance": value,
        }
      handler = _CreateHandler(rlib2.R_2_instances_name_export, ["err1"], {},
                               data, self._clfactory)
      self.assertRaises(http.HttpBadRequest, handler.PUT)


class TestInstanceMigrate(RAPITestCase):
  def test(self):
    name = "instYooho6ek"

    for cleanup in [False, True]:
      for mode in constants.HT_MIGRATION_MODES:
        data = {
          "cleanup": cleanup,
          "mode": mode,
          }

        op = self.getSubmittedOpcode(rlib2.R_2_instances_name_migrate, [name],
                                     {}, data, "PUT", opcodes.OpInstanceMigrate)

        self.assertEqual(op.instance_name, name)
        self.assertEqual(op.mode, mode)
        self.assertEqual(op.cleanup, cleanup)
        self.assertFalse(op.dry_run)
        self.assertFalse(hasattr(op, "force"))

  def testDefaults(self):
    name = "instnohZeex0"

    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_migrate, [name], {},
                                 {}, "PUT", opcodes.OpInstanceMigrate)

    self.assertEqual(op.instance_name, name)
    self.assertTrue(op.mode is None)
    self.assertFalse(op.cleanup)
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))


class TestParseRenameInstanceRequest(RAPITestCase):
  def test(self):
    name = "instij0eeph7"

    for new_name in ["ua0aiyoo", "fai3ongi"]:
      for ip_check in [False, True]:
        for name_check in [False, True]:
          data = {
            "new_name": new_name,
            "ip_check": ip_check,
            "name_check": name_check,
            }

          op = self.getSubmittedOpcode(rlib2.R_2_instances_name_rename, [name],
                                       {}, data, "PUT",
                                       opcodes.OpInstanceRename)

          self.assertEqual(op.instance_name, name)
          self.assertEqual(op.new_name, new_name)
          self.assertEqual(op.ip_check, ip_check)
          self.assertEqual(op.name_check, name_check)
          self.assertFalse(op.dry_run)
          self.assertFalse(hasattr(op, "force"))

  def testDefaults(self):
    name = "instahchie3t"

    for new_name in ["thag9mek", "quees7oh"]:
      data = {
        "new_name": new_name,
        }

      op = self.getSubmittedOpcode(rlib2.R_2_instances_name_rename, [name],
                                   {}, data, "PUT", opcodes.OpInstanceRename)

      self.assertEqual(op.instance_name, name)
      self.assertEqual(op.new_name, new_name)
      self.assertTrue(op.ip_check)
      self.assertTrue(op.name_check)
      self.assertFalse(op.dry_run)
      self.assertFalse(hasattr(op, "force"))


class TestParseModifyInstanceRequest(RAPITestCase):
  def test(self):
    name = "instush8gah"

    test_disks = [
      [],
      [(1, { constants.IDISK_MODE: constants.DISK_RDWR, })],
      ]

    for osparams in [{}, { "some": "value", "other": "Hello World", }]:
      for hvparams in [{}, { constants.HV_KERNEL_PATH: "/some/kernel", }]:
        for beparams in [{}, { constants.BE_MAXMEM: 128, }]:
          for force in [False, True]:
            for nics in [[], [(0, { constants.INIC_IP: "192.0.2.1", })]]:
              for disks in test_disks:
                for disk_template in constants.DISK_TEMPLATES:
                  data = {
                    "osparams": osparams,
                    "hvparams": hvparams,
                    "beparams": beparams,
                    "nics": nics,
                    "disks": disks,
                    "force": force,
                    "disk_template": disk_template,
                    }

                  op = self.getSubmittedOpcode(
                    rlib2.R_2_instances_name_modify, [name], {}, data, "PUT",
                    opcodes.OpInstanceSetParams
                  )

                  self.assertEqual(op.instance_name, name)
                  self.assertEqual(op.hvparams, hvparams)
                  self.assertEqual(op.beparams, beparams)
                  self.assertEqual(op.osparams, osparams)
                  self.assertEqual(op.force, force)
                  self.assertEqual(op.nics, nics)
                  self.assertEqual(op.disks, disks)
                  self.assertEqual(op.disk_template, disk_template)
                  self.assertTrue(op.remote_node is None)
                  self.assertTrue(op.os_name is None)
                  self.assertFalse(op.force_variant)
                  self.assertFalse(op.dry_run)

  def testDefaults(self):
    name = "instir8aish31"

    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_modify, [name], {},
                                 {}, "PUT", opcodes.OpInstanceSetParams)

    for i in ["hvparams", "beparams", "osparams", "force", "nics", "disks",
              "disk_template", "remote_node", "os_name", "force_variant"]:
      self.assertTrue(hasattr(op, i))


class TestParseInstanceReinstallRequest(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.Parse = rlib2._ParseInstanceReinstallRequest

  def _Check(self, ops, name):
    expcls = [
      opcodes.OpInstanceShutdown,
      opcodes.OpInstanceReinstall,
      opcodes.OpInstanceStartup,
      ]

    self.assert_(compat.all(isinstance(op, exp)
                            for op, exp in zip(ops, expcls)))
    self.assert_(compat.all(op.instance_name == name for op in ops))

  def test(self):
    name = "shoo0tihohma"

    ops = self.Parse(name, {"os": "sys1", "start": True,})
    self.assertEqual(len(ops), 3)
    self._Check(ops, name)
    self.assertEqual(ops[1].os_type, "sys1")
    self.assertFalse(ops[1].osparams)

    ops = self.Parse(name, {"os": "sys2", "start": False,})
    self.assertEqual(len(ops), 2)
    self._Check(ops, name)
    self.assertEqual(ops[1].os_type, "sys2")

    osparams = {
      "reformat": "1",
      }
    ops = self.Parse(name, {"os": "sys4035", "start": True,
                            "osparams": osparams,})
    self.assertEqual(len(ops), 3)
    self._Check(ops, name)
    self.assertEqual(ops[1].os_type, "sys4035")
    self.assertEqual(ops[1].osparams, osparams)

  def testDefaults(self):
    name = "noolee0g"

    ops = self.Parse(name, {"os": "linux1"})
    self.assertEqual(len(ops), 3)
    self._Check(ops, name)
    self.assertEqual(ops[1].os_type, "linux1")
    self.assertFalse(ops[1].osparams)

  def testErrors(self):
    self.assertRaises(http.HttpBadRequest, self.Parse,
                      "foo", "not a dictionary")


class TestGroupRename(RAPITestCase):
  def test(self):
    name = "group608242564"
    data = {
      "new_name": "ua0aiyoo15112",
      }

    op = self.getSubmittedOpcode(rlib2.R_2_groups_name_rename, [name], {}, data,
                                 "PUT", opcodes.OpGroupRename)

    self.assertEqual(op.group_name, name)
    self.assertEqual(op.new_name, "ua0aiyoo15112")
    self.assertFalse(op.dry_run)

  def testDryRun(self):
    name = "group28548"
    query_args = {
      "dry-run": ["1"],
      }
    data = {
      "new_name": "ua0aiyoo",
      }

    op = self.getSubmittedOpcode(rlib2.R_2_groups_name_rename, [name],
                                 query_args, data, "PUT", opcodes.OpGroupRename)

    self.assertEqual(op.group_name, name)
    self.assertEqual(op.new_name, "ua0aiyoo")
    self.assertTrue(op.dry_run)


class TestInstanceReplaceDisks(RAPITestCase):
  def test(self):
    name = "inst22568"

    for disks in [range(1, 4), "1,2,3", "1, 2, 3"]:
      data = {
        "mode": constants.REPLACE_DISK_SEC,
        "disks": disks,
        "iallocator": "myalloc",
        }

      op = self.getSubmittedOpcode(rlib2.R_2_instances_name_replace_disks,
                                   [name], {}, data, "POST",
                                   opcodes.OpInstanceReplaceDisks)

      self.assertEqual(op.instance_name, name)
      self.assertEqual(op.mode, constants.REPLACE_DISK_SEC)
      self.assertEqual(op.disks, [1, 2, 3])
      self.assertEqual(op.iallocator, "myalloc")

  def testDefaults(self):
    name = "inst11413"
    data = {
      "mode": constants.REPLACE_DISK_AUTO,
      }

    op = self.getSubmittedOpcode(rlib2.R_2_instances_name_replace_disks,
                                 [name], {}, data, "POST",
                                 opcodes.OpInstanceReplaceDisks)

    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.mode, constants.REPLACE_DISK_AUTO)
    self.assertTrue(op.iallocator is None)
    self.assertEqual(op.disks, [])

  def testNoDisks(self):
    handler = _CreateHandler(rlib2.R_2_instances_name_replace_disks,
                             ["inst20661"], {}, {}, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)

    for disks in [None, "", {}]:
      handler = _CreateHandler(rlib2.R_2_instances_name_replace_disks,
                               ["inst20661"], {}, {
        "disks": disks,
        }, self._clfactory)
      self.assertRaises(http.HttpBadRequest, handler.POST)

  def testWrong(self):
    data = {
      "mode": constants.REPLACE_DISK_AUTO,
      "disks": "hello world",
      }

    handler = _CreateHandler(rlib2.R_2_instances_name_replace_disks,
                             ["foo"], {}, data, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)


class TestGroupModify(RAPITestCase):
  def test(self):
    name = "group6002"

    for policy in constants.VALID_ALLOC_POLICIES:
      data = {
        "alloc_policy": policy,
        }

      op = self.getSubmittedOpcode(rlib2.R_2_groups_name_modify, [name], {},
                                   data, "PUT", opcodes.OpGroupSetParams)

      self.assertEqual(op.group_name, name)
      self.assertEqual(op.alloc_policy, policy)
      self.assertFalse(op.dry_run)

  def testUnknownPolicy(self):
    data = {
      "alloc_policy": "_unknown_policy_",
      }

    handler = _CreateHandler(rlib2.R_2_groups_name_modify, ["xyz"], {}, data,
                             self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)
    self.assertNoNextClient()

  def testDefaults(self):
    name = "group6679"

    op = self.getSubmittedOpcode(rlib2.R_2_groups_name_modify, [name], {}, {},
                                 "PUT", opcodes.OpGroupSetParams)

    self.assertEqual(op.group_name, name)
    self.assertTrue(op.alloc_policy is None)
    self.assertFalse(op.dry_run)

  def testCustomParamRename(self):
    name = "groupie"
    data = {
      "custom_diskparams": {},
      "custom_ipolicy": {},
      "custom_ndparams": {},
      }

    op = self.getSubmittedOpcode(rlib2.R_2_groups_name_modify, [name], {}, data,
                                 "PUT", opcodes.OpGroupSetParams)

    self.assertEqual(op.diskparams, {})
    self.assertEqual(op.ipolicy, {})
    self.assertEqual(op.ndparams, {})

    # Define both
    data["diskparams"] = {}
    assert "diskparams" in data and "custom_diskparams" in data
    handler = _CreateHandler(rlib2.R_2_groups_name_modify, [name], {}, data,
                             self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)


class TestGroupAdd(RAPITestCase):
  def test(self):
    name = "group3618"

    for policy in constants.VALID_ALLOC_POLICIES:
      data = {
        "group_name": name,
        "alloc_policy": policy,
        }

      op = self.getSubmittedOpcode(rlib2.R_2_groups, [], {}, data, "POST",
                                   opcodes.OpGroupAdd)

      self.assertEqual(op.group_name, name)
      self.assertEqual(op.alloc_policy, policy)
      self.assertFalse(op.dry_run)

  def testUnknownPolicy(self):
    data = {
      "alloc_policy": "_unknown_policy_",
      }

    handler = _CreateHandler(rlib2.R_2_groups, [], {}, data, self._clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)
    self.assertNoNextClient()

  def testDefaults(self):
    name = "group15395"
    data = {
      "group_name": name,
      }

    op = self.getSubmittedOpcode(rlib2.R_2_groups, [], {}, data, "POST",
                                 opcodes.OpGroupAdd)

    self.assertEqual(op.group_name, name)
    self.assertTrue(op.alloc_policy is None)
    self.assertFalse(op.dry_run)

  def testLegacyName(self):
    name = "group29852"
    query_args = {
      "dry-run": ["1"],
      }
    data = {
      "name": name,
      }

    op = self.getSubmittedOpcode(rlib2.R_2_groups, [], query_args, data, "POST",
                                 opcodes.OpGroupAdd)

    self.assertEqual(op.group_name, name)
    self.assertTrue(op.alloc_policy is None)
    self.assertTrue(op.dry_run)


class TestNodeRole(RAPITestCase):
  def test(self):
    for role in rlib2._NR_MAP.values():
      handler = _CreateHandler(rlib2.R_2_nodes_name_role,
                               ["node-z"], {}, role, self._clfactory)
      if role == rlib2._NR_MASTER:
        self.assertRaises(http.HttpBadRequest, handler.PUT)
      else:
        job_id = handler.PUT()

        cl = self._clfactory.GetNextClient()
        self.assertNoNextClient()

        (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
        self.assertEqual(job_id, exp_job_id)
        self.assertTrue(isinstance(op, opcodes.OpNodeSetParams))
        self.assertEqual(op.node_name, "node-z")
        self.assertFalse(op.force)
        self.assertFalse(op.dry_run)

        if role == rlib2._NR_REGULAR:
          self.assertFalse(op.drained)
          self.assertFalse(op.offline)
          self.assertFalse(op.master_candidate)
        elif role == rlib2._NR_MASTER_CANDIDATE:
          self.assertFalse(op.drained)
          self.assertFalse(op.offline)
          self.assertTrue(op.master_candidate)
        elif role == rlib2._NR_DRAINED:
          self.assertTrue(op.drained)
          self.assertFalse(op.offline)
          self.assertFalse(op.master_candidate)
        elif role == rlib2._NR_OFFLINE:
          self.assertFalse(op.drained)
          self.assertTrue(op.offline)
          self.assertFalse(op.master_candidate)
        else:
          self.fail("Unknown role '%s'" % role)

      self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestSimpleResources(RAPITestCase):
  def tearDown(self):
    self.assertNoNextClient()

  def testFeatures(self):
    handler = _CreateHandler(rlib2.R_2_features, [], {}, None, self._clfactory)
    self.assertEqual(set(handler.GET()), rlib2.ALL_FEATURES)

  def testEmpty(self):
    for cls in [rlib2.R_root, rlib2.R_2]:
      handler = _CreateHandler(cls, [], {}, None, self._clfactory)
      self.assertTrue(handler.GET() is None)

  def testVersion(self):
    handler = _CreateHandler(rlib2.R_version, [], {}, None, self._clfactory)
    self.assertEqual(handler.GET(), constants.RAPI_VERSION)


class TestClusterInfo(unittest.TestCase):
  class _ClusterInfoClient:
    def __init__(self, address=None):
      self.cluster_info = None

    def QueryClusterInfo(self):
      assert self.cluster_info is None
      self.cluster_info = {}
      return self.cluster_info

  def test(self):
    clfactory = _FakeClientFactory(self._ClusterInfoClient)
    handler = _CreateHandler(rlib2.R_2_info, [], {}, None, clfactory)
    result = handler.GET()
    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)
    self.assertEqual(result, cl.cluster_info)


class TestInstancesMultiAlloc(unittest.TestCase):
  def testInstanceUpdate(self):
    clfactory = _FakeClientFactory(_FakeClient)
    data = {
      "instances": [{
        "name": "bar",
        "mode": "create",
        "disks": [{"size": 1024}],
        "disk_template": "plain",
        "nics": [{}],
        }, {
        "name": "foo",
        "mode": "create",
        "disks": [{"size": 1024}],
        "disk_template": "drbd",
        "nics": [{}],
        }],
      }
    handler = _CreateHandler(rlib2.R_2_instances_multi_alloc, [], {}, data,
                             clfactory)

    (body, _) = handler.GetPostOpInput()

    self.assertTrue(compat.all(
      [isinstance(inst, opcodes.OpInstanceCreate) for inst in body["instances"]]
    ))


class TestPermissions(unittest.TestCase):
  def testEquality(self):
    self.assertEqual(rlib2.R_2_query.GET_ACCESS, rlib2.R_2_query.PUT_ACCESS)
    self.assertEqual(rlib2.R_2_query.GET_ACCESS,
                     rlib2.R_2_instances_name_console.GET_ACCESS)

  def testMethodAccess(self):
    for handler in connector.CONNECTOR.values():
      for method in baserlib._SUPPORTED_METHODS:
        access = baserlib.GetHandlerAccess(handler, method)
        self.assertFalse(access is None)
        self.assertFalse(set(access) - rapi.RAPI_ACCESS_ALL,
                         msg=("Handler '%s' uses unknown access options for"
                              " method %s" % (handler, method)))
        self.assertTrue(rapi.RAPI_ACCESS_READ not in access or
                        rapi.RAPI_ACCESS_WRITE in access,
                        msg=("Handler '%s' gives query, but not write access"
                             " for method %s (the latter includes query and"
                             " should therefore be given as well)" %
                             (handler, method)))


class ForbiddenOpcode(opcodes.OpCode):
  OP_PARAMS = [
    ("obligatory", None, ht.TString, None),
    ("forbidden", None, ht.TMaybe(ht.TString), None),
    ("forbidden_true", None, ht.TMaybe(ht.TBool), None),
    ]


class ForbiddenRAPI(baserlib.OpcodeResource):
  POST_OPCODE = ForbiddenOpcode
  POST_FORBIDDEN = [
    "forbidden",
    ("forbidden_true", [True]),
  ]
  POST_RENAME = {
    "totally_not_forbidden": "forbidden"
  }


class TestForbiddenParams(RAPITestCase):
  def testTestOpcode(self):
    obligatory_value = "a"
    forbidden_value = "b"
    forbidden_true_value = True
    op = ForbiddenOpcode(
      obligatory=obligatory_value,
      forbidden=forbidden_value,
      forbidden_true=forbidden_true_value
    )
    self.assertEqualValues(op.obligatory, obligatory_value)
    self.assertEqualValues(op.forbidden, forbidden_value)
    self.assertEqualValues(op.forbidden_true, forbidden_true_value)

  def testCorrectRequest(self):
    value = "o"
    op = self.getSubmittedOpcode(ForbiddenRAPI, [], {}, {"obligatory": value},
                                 "POST", ForbiddenOpcode)
    self.assertEqual(op.obligatory, value)

  def testValueForbidden(self):
    value = "o"
    data = {
      "obligatory": value,
      "forbidden": value,
    }
    handler = _CreateHandler(ForbiddenRAPI, [], {}, data, self._clfactory)
    self.assertRaises(http.HttpForbidden, handler.POST)

  def testSpecificValueForbidden(self):
    for value in [True, False, "True"]:
      data = {
        "obligatory": "o",
        "forbidden_true": value,
      }
      handler = _CreateHandler(ForbiddenRAPI, [], {}, data, self._clfactory)

      if value == True:
        self.assertRaises(http.HttpForbidden, handler.POST)
      elif value == "True":
        self.assertRaises(http.HttpBadRequest, handler.POST)
      else:
        handler.POST()
        cl = self._clfactory.GetNextClient()
        (_, (op, )) = cl.GetNextSubmittedJob()
        self.assertTrue(isinstance(op, ForbiddenOpcode))
        self.assertEqual(op.forbidden_true, value)

  def testRenameIntoForbidden(self):
    data = {
      "obligatory": "o",
      "totally_not_forbidden": "o",
    }
    handler = _CreateHandler(ForbiddenRAPI, [], {}, data, self._clfactory)
    self.assertRaises(http.HttpForbidden, handler.POST)

if __name__ == "__main__":
  testutils.GanetiTestProgram()

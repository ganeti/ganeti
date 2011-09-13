#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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


"""Script for unittesting the RAPI rlib2 module

"""


import unittest
import itertools
import random

from ganeti import constants
from ganeti import opcodes
from ganeti import compat
from ganeti import http
from ganeti import query
from ganeti import luxi
from ganeti import errors

from ganeti.rapi import rlib2

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
  def __init__(self):
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

  def __call__(self):
    cl = self._client_cls()
    self._clients.append(cl)
    return cl


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
  def _FailingClient():
    raise luxi.NoMasterError("test")

  def test(self):
    resources = [
      rlib2.R_2_groups,
      rlib2.R_2_instances,
      rlib2.R_2_nodes,
      ]
    for cls in resources:
      handler = _CreateHandler(cls, ["name"], [], None, self._FailingClient)
      self.assertRaises(http.HttpBadGateway, handler.GET)


class TestJobSubmitError(unittest.TestCase):
  class _SubmitErrorClient:
    @staticmethod
    def SubmitJob(ops):
      raise errors.JobQueueFull("test")

  def test(self):
    handler = _CreateHandler(rlib2.R_2_redist_config, [], [], None,
                             self._SubmitErrorClient)
    self.assertRaises(http.HttpServiceUnavailable, handler.PUT)


class TestClusterModify(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_cluster_modify, [], [], {
      "vg_name": "testvg",
      "candidate_pool_size": 100,
      }, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpClusterSetParams))
    self.assertEqual(op.vg_name, "testvg")
    self.assertEqual(op.candidate_pool_size, 100)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testInvalidValue(self):
    for attr in ["vg_name", "candidate_pool_size", "beparams", "_-Unknown#"]:
      clfactory = _FakeClientFactory(_FakeClient)
      handler = _CreateHandler(rlib2.R_2_cluster_modify, [], [], {
        attr: True,
        }, clfactory)
      self.assertRaises(http.HttpBadRequest, handler.PUT)
      self.assertRaises(IndexError, clfactory.GetNextClient)


class TestRedistConfig(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_redist_config, [], [], None, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpClusterRedistConf))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestNodeMigrate(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_nodes_name_migrate, ["node1"], {}, {
      "iallocator": "fooalloc",
      }, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpNodeMigrate))
    self.assertEqual(op.node_name, "node1")
    self.assertEqual(op.iallocator, "fooalloc")

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testQueryArgsConflict(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_nodes_name_migrate, ["node2"], {
      "live": True,
      "mode": constants.HT_MIGRATION_NONLIVE,
      }, None, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)
    self.assertRaises(IndexError, clfactory.GetNextClient)

  def testQueryArgsMode(self):
    clfactory = _FakeClientFactory(_FakeClient)
    queryargs = {
      "mode": [constants.HT_MIGRATION_LIVE],
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_migrate, ["node17292"],
                             queryargs, None, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpNodeMigrate))
    self.assertEqual(op.node_name, "node17292")
    self.assertEqual(op.mode, constants.HT_MIGRATION_LIVE)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testQueryArgsLive(self):
    clfactory = _FakeClientFactory(_FakeClient)

    for live in [False, True]:
      queryargs = {
        "live": [str(int(live))],
        }
      handler = _CreateHandler(rlib2.R_2_nodes_name_migrate, ["node6940"],
                               queryargs, None, clfactory)
      job_id = handler.POST()

      cl = clfactory.GetNextClient()
      self.assertRaises(IndexError, clfactory.GetNextClient)

      (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
      self.assertEqual(job_id, exp_job_id)
      self.assertTrue(isinstance(op, opcodes.OpNodeMigrate))
      self.assertEqual(op.node_name, "node6940")
      if live:
        self.assertEqual(op.mode, constants.HT_MIGRATION_LIVE)
      else:
        self.assertEqual(op.mode, constants.HT_MIGRATION_NONLIVE)

      self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestNodeEvacuate(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_nodes_name_evacuate, ["node92"], {
      "dry-run": ["1"],
      }, {
      "mode": constants.IALLOCATOR_NEVAC_SEC,
      }, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpNodeEvacuate))
    self.assertEqual(op.node_name, "node92")
    self.assertEqual(op.mode, constants.IALLOCATOR_NEVAC_SEC)
    self.assertTrue(op.dry_run)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestGroupAssignNodes(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_groups_name_assign_nodes, ["grp-a"], {
      "dry-run": ["1"],
      "force": ["1"],
      }, {
      "nodes": ["n2", "n3"],
      }, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpGroupAssignNodes))
    self.assertEqual(op.group_name, "grp-a")
    self.assertEqual(op.nodes, ["n2", "n3"])
    self.assertTrue(op.dry_run)
    self.assertTrue(op.force)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceDelete(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_instances_name, ["inst30965"], {
      "dry-run": ["1"],
      }, {}, clfactory)
    job_id = handler.DELETE()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceRemove))
    self.assertEqual(op.instance_name, "inst30965")
    self.assertTrue(op.dry_run)
    self.assertFalse(op.ignore_failures)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceInfo(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_instances_name_info, ["inst31217"], {
      "static": ["1"],
      }, {}, clfactory)
    job_id = handler.GET()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceQueryData))
    self.assertEqual(op.instances, ["inst31217"])
    self.assertTrue(op.static)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceReboot(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_instances_name_reboot, ["inst847"], {
      "dry-run": ["1"],
      "ignore_secondaries": ["1"],
      }, {}, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceReboot))
    self.assertEqual(op.instance_name, "inst847")
    self.assertEqual(op.reboot_type, constants.INSTANCE_REBOOT_HARD)
    self.assertTrue(op.ignore_secondaries)
    self.assertTrue(op.dry_run)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceStartup(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_instances_name_startup, ["inst31083"], {
      "force": ["1"],
      "no_remember": ["1"],
      }, {}, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceStartup))
    self.assertEqual(op.instance_name, "inst31083")
    self.assertTrue(op.no_remember)
    self.assertTrue(op.force)
    self.assertFalse(op.dry_run)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceShutdown(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_instances_name_shutdown, ["inst26791"], {
      "no_remember": ["0"],
      }, {}, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceShutdown))
    self.assertEqual(op.instance_name, "inst26791")
    self.assertFalse(op.no_remember)
    self.assertFalse(op.dry_run)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceActivateDisks(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_instances_name_activate_disks, ["xyz"], {
      "ignore_size": ["1"],
      }, {}, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceActivateDisks))
    self.assertEqual(op.instance_name, "xyz")
    self.assertTrue(op.ignore_size)
    self.assertFalse(hasattr(op, "dry_run"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceDeactivateDisks(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_instances_name_deactivate_disks,
                             ["inst22357"], {}, {}, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceDeactivateDisks))
    self.assertEqual(op.instance_name, "inst22357")
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceFailover(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_instances_name_failover,
                             ["inst12794"], {}, {}, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceFailover))
    self.assertEqual(op.instance_name, "inst12794")
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceDiskGrow(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    data = {
      "amount": 1024,
      }
    handler = _CreateHandler(rlib2.R_2_instances_name_disk_grow,
                             ["inst10742", "3"], {}, data, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceGrowDisk))
    self.assertEqual(op.instance_name, "inst10742")
    self.assertEqual(op.disk, 3)
    self.assertEqual(op.amount, 1024)
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestBackupPrepare(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    queryargs = {
      "mode": constants.EXPORT_MODE_REMOTE,
      }
    handler = _CreateHandler(rlib2.R_2_instances_name_prepare_export,
                             ["inst17925"], queryargs, {}, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpBackupPrepare))
    self.assertEqual(op.instance_name, "inst17925")
    self.assertEqual(op.mode, constants.EXPORT_MODE_REMOTE)
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestGroupRemove(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    handler = _CreateHandler(rlib2.R_2_groups_name,
                             ["grp28575"], {}, {}, clfactory)
    job_id = handler.DELETE()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpGroupRemove))
    self.assertEqual(op.group_name, "grp28575")
    self.assertFalse(op.dry_run)
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestStorageQuery(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    queryargs = {
      "storage_type": constants.ST_LVM_PV,
      "output_fields": "name,other",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage,
                             ["node21075"], queryargs, {}, clfactory)
    job_id = handler.GET()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpNodeQueryStorage))
    self.assertEqual(op.nodes, ["node21075"])
    self.assertEqual(op.storage_type, constants.ST_LVM_PV)
    self.assertEqual(op.output_fields, ["name", "other"])
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testErrors(self):
    clfactory = _FakeClientFactory(_FakeClient)

    queryargs = {
      "output_fields": "name,other",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage,
                             ["node10538"], queryargs, {}, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.GET)

    queryargs = {
      "storage_type": constants.ST_LVM_VG,
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage,
                             ["node21273"], queryargs, {}, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.GET)

    queryargs = {
      "storage_type": "##unknown_storage##",
      "output_fields": "name,other",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage,
                             ["node10315"], queryargs, {}, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.GET)


class TestStorageModify(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    for allocatable in [None, "1", "0"]:
      queryargs = {
        "storage_type": constants.ST_LVM_VG,
        "name": "pv-a",
        }

      if allocatable is not None:
        queryargs["allocatable"] = allocatable

      handler = _CreateHandler(rlib2.R_2_nodes_name_storage_modify,
                               ["node9292"], queryargs, {}, clfactory)
      job_id = handler.PUT()

      cl = clfactory.GetNextClient()
      self.assertRaises(IndexError, clfactory.GetNextClient)

      (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
      self.assertEqual(job_id, exp_job_id)
      self.assertTrue(isinstance(op, opcodes.OpNodeModifyStorage))
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
      self.assertFalse(hasattr(op, "dry_run"))
      self.assertFalse(hasattr(op, "force"))

      self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testErrors(self):
    clfactory = _FakeClientFactory(_FakeClient)

    # No storage type
    queryargs = {
      "name": "xyz",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_modify,
                             ["node26016"], queryargs, {}, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)

    # No name
    queryargs = {
      "storage_type": constants.ST_LVM_VG,
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_modify,
                             ["node21218"], queryargs, {}, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)

    # Invalid value
    queryargs = {
      "storage_type": constants.ST_LVM_VG,
      "name": "pv-b",
      "allocatable": "noint",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_modify,
                             ["node30685"], queryargs, {}, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)


class TestStorageRepair(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)
    queryargs = {
      "storage_type": constants.ST_LVM_PV,
      "name": "pv16611",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_repair,
                             ["node19265"], queryargs, {}, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpRepairNodeStorage))
    self.assertEqual(op.node_name, "node19265")
    self.assertEqual(op.storage_type, constants.ST_LVM_PV)
    self.assertEqual(op.name, "pv16611")
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testErrors(self):
    clfactory = _FakeClientFactory(_FakeClient)

    # No storage type
    queryargs = {
      "name": "xyz",
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_repair,
                             ["node11275"], queryargs, {}, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)

    # No name
    queryargs = {
      "storage_type": constants.ST_LVM_VG,
      }
    handler = _CreateHandler(rlib2.R_2_nodes_name_storage_repair,
                             ["node21218"], queryargs, {}, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)


class TestTags(unittest.TestCase):
  TAG_HANDLERS = [
    rlib2.R_2_instances_name_tags,
    rlib2.R_2_nodes_name_tags,
    rlib2.R_2_groups_name_tags,
    rlib2.R_2_tags,
    ]

  def testSetAndDelete(self):
    clfactory = _FakeClientFactory(_FakeClient)

    for method, opcls in [("PUT", opcodes.OpTagsSet),
                          ("DELETE", opcodes.OpTagsDel)]:
      for idx, handler in enumerate(self.TAG_HANDLERS):
        dry_run = bool(idx % 2)
        name = "test%s" % idx
        queryargs = {
          "tag": ["foo", "bar", "baz"],
          "dry-run": str(int(dry_run)),
          }

        handler = _CreateHandler(handler, [name], queryargs, {}, clfactory)
        job_id = getattr(handler, method)()

        cl = clfactory.GetNextClient()
        self.assertRaises(IndexError, clfactory.GetNextClient)

        (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
        self.assertEqual(job_id, exp_job_id)
        self.assertTrue(isinstance(op, opcls))
        self.assertEqual(op.kind, handler.TAG_LEVEL)
        if handler.TAG_LEVEL == constants.TAG_CLUSTER:
          self.assertTrue(op.name is None)
        else:
          self.assertEqual(op.name, name)
        self.assertEqual(op.tags, ["foo", "bar", "baz"])
        self.assertEqual(op.dry_run, dry_run)
        self.assertFalse(hasattr(op, "force"))

        self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceCreation(testutils.GanetiTestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

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
      { constants.BE_MEMORY: 123, },
      { constants.BE_VCPUS: 2,
        constants.BE_MEMORY: 1024,
        constants.BE_AUTO_BALANCE: True, }
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
                  queryargs = {
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

                  handler = _CreateHandler(rlib2.R_2_instances, [],
                                           queryargs, data, clfactory)
                  job_id = handler.POST()

                  cl = clfactory.GetNextClient()
                  self.assertRaises(IndexError, clfactory.GetNextClient)

                  (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
                  self.assertEqual(job_id, exp_job_id)
                  self.assertRaises(IndexError, cl.GetNextSubmittedJob)

                  self.assertTrue(isinstance(op, opcodes.OpInstanceCreate))
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
                    self.assertFalse(hasattr(op, "beparams"))
                  else:
                    self.assertEqualValues(op.beparams, beparams)

                  if hvparams is None:
                    self.assertFalse(hasattr(op, "hvparams"))
                  else:
                    self.assertEqualValues(op.hvparams, hvparams)

  def testLegacyName(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "inst29128.example.com"
    data = {
      rlib2._REQ_DATA_VERSION: 1,
      "name": name,
      "disks": [],
      "nics": [],
      "mode": constants.INSTANCE_CREATE,
      "disk_template": constants.DT_PLAIN,
      }

    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceCreate))
    self.assertEqual(op.instance_name, name)
    self.assertFalse(hasattr(op, "name"))
    self.assertFalse(op.dry_run)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

    # Define both
    data["instance_name"] = "other.example.com"
    assert "name" in data and "instance_name" in data
    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)
    self.assertRaises(IndexError, clfactory.GetNextClient)

  def testLegacyOs(self):
    clfactory = _FakeClientFactory(_FakeClient)

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

    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceCreate))
    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.os_type, os)
    self.assertFalse(hasattr(op, "os"))
    self.assertFalse(op.dry_run)

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

    # Define both
    data["os"] = "linux9584"
    assert "os" in data and "os_type" in data
    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)

  def testErrors(self):
    clfactory = _FakeClientFactory(_FakeClient)

    # Test all required fields
    reqfields = {
      rlib2._REQ_DATA_VERSION: 1,
      "name": "inst1.example.com",
      "disks": [],
      "nics": [],
      "mode": constants.INSTANCE_CREATE,
      "disk_template": constants.DT_PLAIN,
      }

    for name in reqfields.keys():
      data = dict(i for i in reqfields.iteritems() if i[0] != name)

      handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
      self.assertRaises(http.HttpBadRequest, handler.POST)
      self.assertRaises(IndexError, clfactory.GetNextClient)

    # Invalid disks and nics
    for field in ["disks", "nics"]:
      invalid_values = [None, 1, "", {}, [1, 2, 3], ["hda1", "hda2"],
                        [{"_unknown_": 999, }]]

      for invvalue in invalid_values:
        data = reqfields.copy()
        data[field] = invvalue
        handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
        self.assertRaises(http.HttpBadRequest, handler.POST)
        self.assertRaises(IndexError, clfactory.GetNextClient)

  def testVersion(self):
    clfactory = _FakeClientFactory(_FakeClient)

    # No version field
    data = {
      "name": "inst1.example.com",
      "disks": [],
      "nics": [],
      "mode": constants.INSTANCE_CREATE,
      "disk_template": constants.DT_PLAIN,
      }

    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)

    # Old and incorrect versions
    for version in [0, -1, 10483, "Hello World"]:
      data[rlib2._REQ_DATA_VERSION] = version

      handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
      self.assertRaises(http.HttpBadRequest, handler.POST)

      self.assertRaises(IndexError, clfactory.GetNextClient)

    # Correct version
    data[rlib2._REQ_DATA_VERSION] = 1
    handler = _CreateHandler(rlib2.R_2_instances, [], {}, data, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceCreate))
    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestBackupExport(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "instmoo"
    data = {
      "mode": constants.EXPORT_MODE_REMOTE,
      "destination": [(1, 2, 3), (99, 99, 99)],
      "shutdown": True,
      "remove_instance": True,
      "x509_key_name": ["name", "hash"],
      "destination_x509_ca": "---cert---"
      }

    handler = _CreateHandler(rlib2.R_2_instances_name_export, [name], {},
                             data, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpBackupExport))
    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.mode, constants.EXPORT_MODE_REMOTE)
    self.assertEqual(op.target_node, [(1, 2, 3), (99, 99, 99)])
    self.assertEqual(op.shutdown, True)
    self.assertEqual(op.remove_instance, True)
    self.assertEqual(op.x509_key_name, ["name", "hash"])
    self.assertEqual(op.destination_x509_ca, "---cert---")
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testDefaults(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "inst1"
    data = {
      "destination": "node2",
      "shutdown": False,
      }

    handler = _CreateHandler(rlib2.R_2_instances_name_export, [name], {},
                             data, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpBackupExport))
    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.target_node, "node2")
    self.assertFalse(hasattr(op, "mode"))
    self.assertFalse(hasattr(op, "remove_instance"))
    self.assertFalse(hasattr(op, "destination"))
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testErrors(self):
    clfactory = _FakeClientFactory(_FakeClient)

    for value in ["True", "False"]:
      handler = _CreateHandler(rlib2.R_2_instances_name_export, ["err1"], {}, {
        "remove_instance": value,
        }, clfactory)
      self.assertRaises(http.HttpBadRequest, handler.PUT)


class TestInstanceMigrate(testutils.GanetiTestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "instYooho6ek"

    for cleanup in [False, True]:
      for mode in constants.HT_MIGRATION_MODES:
        data = {
          "cleanup": cleanup,
          "mode": mode,
          }

        handler = _CreateHandler(rlib2.R_2_instances_name_migrate, [name], {},
                                 data, clfactory)
        job_id = handler.PUT()

        cl = clfactory.GetNextClient()
        self.assertRaises(IndexError, clfactory.GetNextClient)

        (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
        self.assertEqual(job_id, exp_job_id)
        self.assertTrue(isinstance(op, opcodes.OpInstanceMigrate))
        self.assertEqual(op.instance_name, name)
        self.assertEqual(op.mode, mode)
        self.assertEqual(op.cleanup, cleanup)
        self.assertFalse(hasattr(op, "dry_run"))
        self.assertFalse(hasattr(op, "force"))

        self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testDefaults(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "instnohZeex0"

    handler = _CreateHandler(rlib2.R_2_instances_name_migrate, [name], {}, {},
                             clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceMigrate))
    self.assertEqual(op.instance_name, name)
    self.assertFalse(hasattr(op, "mode"))
    self.assertFalse(hasattr(op, "cleanup"))
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertFalse(hasattr(op, "force"))

    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestParseRenameInstanceRequest(testutils.GanetiTestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "instij0eeph7"

    for new_name in ["ua0aiyoo", "fai3ongi"]:
      for ip_check in [False, True]:
        for name_check in [False, True]:
          data = {
            "new_name": new_name,
            "ip_check": ip_check,
            "name_check": name_check,
            }

          handler = _CreateHandler(rlib2.R_2_instances_name_rename, [name],
                                   {}, data, clfactory)
          job_id = handler.PUT()

          cl = clfactory.GetNextClient()
          self.assertRaises(IndexError, clfactory.GetNextClient)

          (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
          self.assertEqual(job_id, exp_job_id)
          self.assertTrue(isinstance(op, opcodes.OpInstanceRename))
          self.assertEqual(op.instance_name, name)
          self.assertEqual(op.new_name, new_name)
          self.assertEqual(op.ip_check, ip_check)
          self.assertEqual(op.name_check, name_check)
          self.assertFalse(hasattr(op, "dry_run"))
          self.assertFalse(hasattr(op, "force"))

          self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testDefaults(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "instahchie3t"

    for new_name in ["thag9mek", "quees7oh"]:
      data = {
        "new_name": new_name,
        }

      handler = _CreateHandler(rlib2.R_2_instances_name_rename, [name],
                               {}, data, clfactory)
      job_id = handler.PUT()

      cl = clfactory.GetNextClient()
      self.assertRaises(IndexError, clfactory.GetNextClient)

      (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
      self.assertEqual(job_id, exp_job_id)
      self.assertTrue(isinstance(op, opcodes.OpInstanceRename))
      self.assertEqual(op.instance_name, name)
      self.assertEqual(op.new_name, new_name)
      self.assertFalse(hasattr(op, "ip_check"))
      self.assertFalse(hasattr(op, "name_check"))
      self.assertFalse(hasattr(op, "dry_run"))
      self.assertFalse(hasattr(op, "force"))

      self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestParseModifyInstanceRequest(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "instush8gah"

    test_disks = [
      [],
      [(1, { constants.IDISK_MODE: constants.DISK_RDWR, })],
      ]

    for osparams in [{}, { "some": "value", "other": "Hello World", }]:
      for hvparams in [{}, { constants.HV_KERNEL_PATH: "/some/kernel", }]:
        for beparams in [{}, { constants.BE_MEMORY: 128, }]:
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

                  handler = _CreateHandler(rlib2.R_2_instances_name_modify,
                                           [name], {}, data, clfactory)
                  job_id = handler.PUT()

                  cl = clfactory.GetNextClient()
                  self.assertRaises(IndexError, clfactory.GetNextClient)

                  (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
                  self.assertEqual(job_id, exp_job_id)
                  self.assertTrue(isinstance(op, opcodes.OpInstanceSetParams))
                  self.assertEqual(op.instance_name, name)
                  self.assertEqual(op.hvparams, hvparams)
                  self.assertEqual(op.beparams, beparams)
                  self.assertEqual(op.osparams, osparams)
                  self.assertEqual(op.force, force)
                  self.assertEqual(op.nics, nics)
                  self.assertEqual(op.disks, disks)
                  self.assertEqual(op.disk_template, disk_template)
                  self.assertFalse(hasattr(op, "remote_node"))
                  self.assertFalse(hasattr(op, "os_name"))
                  self.assertFalse(hasattr(op, "force_variant"))
                  self.assertFalse(hasattr(op, "dry_run"))

                  self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testDefaults(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "instir8aish31"

    handler = _CreateHandler(rlib2.R_2_instances_name_modify,
                             [name], {}, {}, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)
    self.assertTrue(isinstance(op, opcodes.OpInstanceSetParams))
    self.assertEqual(op.instance_name, name)

    for i in ["hvparams", "beparams", "osparams", "force", "nics", "disks",
              "disk_template", "remote_node", "os_name", "force_variant"]:
      self.assertFalse(hasattr(op, i))


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


class TestGroupRename(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "group608242564"
    data = {
      "new_name": "ua0aiyoo15112",
      }

    handler = _CreateHandler(rlib2.R_2_groups_name_rename, [name], {}, data,
                             clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)

    self.assertTrue(isinstance(op, opcodes.OpGroupRename))
    self.assertEqual(op.group_name, name)
    self.assertEqual(op.new_name, "ua0aiyoo15112")
    self.assertFalse(op.dry_run)
    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testDryRun(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "group28548"
    data = {
      "new_name": "ua0aiyoo",
      }

    handler = _CreateHandler(rlib2.R_2_groups_name_rename, [name], {
      "dry-run": ["1"],
      }, data, clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)

    self.assertTrue(isinstance(op, opcodes.OpGroupRename))
    self.assertEqual(op.group_name, name)
    self.assertEqual(op.new_name, "ua0aiyoo")
    self.assertTrue(op.dry_run)
    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestInstanceReplaceDisks(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "inst22568"

    for disks in [range(1, 4), "1,2,3", "1, 2, 3"]:
      data = {
        "mode": constants.REPLACE_DISK_SEC,
        "disks": disks,
        "iallocator": "myalloc",
        }

      handler = _CreateHandler(rlib2.R_2_instances_name_replace_disks,
                               [name], {}, data, clfactory)
      job_id = handler.POST()

      cl = clfactory.GetNextClient()
      self.assertRaises(IndexError, clfactory.GetNextClient)

      (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
      self.assertEqual(job_id, exp_job_id)

      self.assertTrue(isinstance(op, opcodes.OpInstanceReplaceDisks))
      self.assertEqual(op.instance_name, name)
      self.assertEqual(op.mode, constants.REPLACE_DISK_SEC)
      self.assertEqual(op.disks, [1, 2, 3])
      self.assertEqual(op.iallocator, "myalloc")
      self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testDefaults(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "inst11413"
    data = {
      "mode": constants.REPLACE_DISK_AUTO,
      }

    handler = _CreateHandler(rlib2.R_2_instances_name_replace_disks,
                             [name], {}, data, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)

    self.assertTrue(isinstance(op, opcodes.OpInstanceReplaceDisks))
    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.mode, constants.REPLACE_DISK_AUTO)
    self.assertFalse(hasattr(op, "iallocator"))
    self.assertFalse(hasattr(op, "disks"))
    self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testWrong(self):
    clfactory = _FakeClientFactory(_FakeClient)

    data = {
      "mode": constants.REPLACE_DISK_AUTO,
      "disks": "hello world",
      }

    handler = _CreateHandler(rlib2.R_2_instances_name_replace_disks,
                             ["foo"], {}, data, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)


class TestGroupModify(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "group6002"

    for policy in constants.VALID_ALLOC_POLICIES:
      data = {
        "alloc_policy": policy,
        }

      handler = _CreateHandler(rlib2.R_2_groups_name_modify, [name], {}, data,
                               clfactory)
      job_id = handler.PUT()

      cl = clfactory.GetNextClient()
      self.assertRaises(IndexError, clfactory.GetNextClient)

      (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
      self.assertEqual(job_id, exp_job_id)

      self.assertTrue(isinstance(op, opcodes.OpGroupSetParams))
      self.assertEqual(op.group_name, name)
      self.assertEqual(op.alloc_policy, policy)
      self.assertFalse(hasattr(op, "dry_run"))
      self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testUnknownPolicy(self):
    clfactory = _FakeClientFactory(_FakeClient)

    data = {
      "alloc_policy": "_unknown_policy_",
      }

    handler = _CreateHandler(rlib2.R_2_groups_name_modify, ["xyz"], {}, data,
                             clfactory)
    self.assertRaises(http.HttpBadRequest, handler.PUT)
    self.assertRaises(IndexError, clfactory.GetNextClient)

  def testDefaults(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "group6679"

    handler = _CreateHandler(rlib2.R_2_groups_name_modify, [name], {}, {},
                             clfactory)
    job_id = handler.PUT()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)

    self.assertTrue(isinstance(op, opcodes.OpGroupSetParams))
    self.assertEqual(op.group_name, name)
    self.assertFalse(hasattr(op, "alloc_policy"))
    self.assertFalse(hasattr(op, "dry_run"))
    self.assertRaises(IndexError, cl.GetNextSubmittedJob)


class TestGroupAdd(unittest.TestCase):
  def test(self):
    name = "group3618"
    clfactory = _FakeClientFactory(_FakeClient)

    for policy in constants.VALID_ALLOC_POLICIES:
      data = {
        "group_name": name,
        "alloc_policy": policy,
        }

      handler = _CreateHandler(rlib2.R_2_groups, [], {}, data,
                               clfactory)
      job_id = handler.POST()

      cl = clfactory.GetNextClient()
      self.assertRaises(IndexError, clfactory.GetNextClient)

      (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
      self.assertEqual(job_id, exp_job_id)

      self.assertTrue(isinstance(op, opcodes.OpGroupAdd))
      self.assertEqual(op.group_name, name)
      self.assertEqual(op.alloc_policy, policy)
      self.assertFalse(op.dry_run)
      self.assertRaises(IndexError, cl.GetNextSubmittedJob)

  def testUnknownPolicy(self):
    clfactory = _FakeClientFactory(_FakeClient)

    data = {
      "alloc_policy": "_unknown_policy_",
      }

    handler = _CreateHandler(rlib2.R_2_groups, [], {}, data, clfactory)
    self.assertRaises(http.HttpBadRequest, handler.POST)
    self.assertRaises(IndexError, clfactory.GetNextClient)

  def testDefaults(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "group15395"
    data = {
      "group_name": name,
      }

    handler = _CreateHandler(rlib2.R_2_groups, [], {}, data, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)

    self.assertTrue(isinstance(op, opcodes.OpGroupAdd))
    self.assertEqual(op.group_name, name)
    self.assertFalse(hasattr(op, "alloc_policy"))
    self.assertFalse(op.dry_run)

  def testLegacyName(self):
    clfactory = _FakeClientFactory(_FakeClient)

    name = "group29852"
    data = {
      "name": name,
      }

    handler = _CreateHandler(rlib2.R_2_groups, [], {
      "dry-run": ["1"],
      }, data, clfactory)
    job_id = handler.POST()

    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)

    (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
    self.assertEqual(job_id, exp_job_id)

    self.assertTrue(isinstance(op, opcodes.OpGroupAdd))
    self.assertEqual(op.group_name, name)
    self.assertFalse(hasattr(op, "alloc_policy"))
    self.assertTrue(op.dry_run)


class TestNodeRole(unittest.TestCase):
  def test(self):
    clfactory = _FakeClientFactory(_FakeClient)

    for role in rlib2._NR_MAP.values():
      handler = _CreateHandler(rlib2.R_2_nodes_name_role,
                               ["node-z"], {}, role, clfactory)
      if role == rlib2._NR_MASTER:
        self.assertRaises(http.HttpBadRequest, handler.PUT)
      else:
        job_id = handler.PUT()

        cl = clfactory.GetNextClient()
        self.assertRaises(IndexError, clfactory.GetNextClient)

        (exp_job_id, (op, )) = cl.GetNextSubmittedJob()
        self.assertEqual(job_id, exp_job_id)
        self.assertTrue(isinstance(op, opcodes.OpNodeSetParams))
        self.assertEqual(op.node_name, "node-z")
        self.assertFalse(op.force)
        self.assertFalse(hasattr(op, "dry_run"))

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


class TestSimpleResources(unittest.TestCase):
  def setUp(self):
    self.clfactory = _FakeClientFactory(_FakeClient)

  def tearDown(self):
    self.assertRaises(IndexError, self.clfactory.GetNextClient)

  def testFeatures(self):
    handler = _CreateHandler(rlib2.R_2_features, [], {}, None, self.clfactory)
    self.assertEqual(set(handler.GET()), rlib2.ALL_FEATURES)

  def testEmpty(self):
    for cls in [rlib2.R_root, rlib2.R_2]:
      handler = _CreateHandler(cls, [], {}, None, self.clfactory)
      self.assertTrue(handler.GET() is None)

  def testVersion(self):
    handler = _CreateHandler(rlib2.R_version, [], {}, None, self.clfactory)
    self.assertEqual(handler.GET(), constants.RAPI_VERSION)


class TestClusterInfo(unittest.TestCase):
  class _ClusterInfoClient:
    def __init__(self):
      self.cluster_info = None

    def QueryClusterInfo(self):
      assert self.cluster_info is None
      self.cluster_info = object()
      return self.cluster_info

  def test(self):
    clfactory = _FakeClientFactory(self._ClusterInfoClient)
    handler = _CreateHandler(rlib2.R_2_info, [], {}, None, clfactory)
    result = handler.GET()
    cl = clfactory.GetNextClient()
    self.assertRaises(IndexError, clfactory.GetNextClient)
    self.assertEqual(result, cl.cluster_info)


if __name__ == '__main__':
  testutils.GanetiTestProgram()

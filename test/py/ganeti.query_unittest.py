#!/usr/bin/python
#

# Copyright (C) 2010, 2011, 2012, 2013 Google Inc.
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


"""Script for testing ganeti.query"""

import re
import unittest
import random
import uuid as uuid_module

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors
from ganeti import query
from ganeti import objects
from ganeti import cmdlib

import ganeti.masterd.instance as gmi
from ganeti.hypervisor import hv_base

import testutils


class TestConstants(unittest.TestCase):
  def test(self):
    self.assertEqual(set(query._VERIFY_FN.keys()),
                     constants.QFT_ALL)


class _QueryData:
  def __init__(self, data, **kwargs):
    self.data = data

    for name, value in kwargs.items():
      setattr(self, name, value)

  def __iter__(self):
    return iter(self.data)


def _GetDiskSize(nr, ctx, item):
  disks = item["disks"]
  try:
    return disks[nr]
  except IndexError:
    return query._FS_UNAVAIL


class TestQuery(unittest.TestCase):
  def test(self):
    (STATIC, DISK) = range(10, 12)

    fielddef = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       STATIC, 0, lambda ctx, item: item["name"]),
      (query._MakeField("master", "Master", constants.QFT_BOOL, "Master"),
       STATIC, 0, lambda ctx, item: ctx.mastername == item["name"]),
      ] +
      [(query._MakeField("disk%s.size" % i, "DiskSize%s" % i,
                         constants.QFT_UNIT, "Disk size %s" % i),
        DISK, 0, compat.partial(_GetDiskSize, i))
       for i in range(4)], [])

    q = query.Query(fielddef, ["name"])
    self.assertEqual(q.RequestedData(), set([STATIC]))
    self.assertEqual(len(q._fields), 1)
    self.assertEqual(len(q.GetFields()), 1)
    self.assertEqual(q.GetFields()[0].ToDict(),
      objects.QueryFieldDefinition(name="name",
                                   title="Name",
                                   kind=constants.QFT_TEXT,
                                   doc="Name").ToDict())

    # Create data only once query has been prepared
    data = [
      { "name": "node1", "disks": [0, 1, 2], },
      { "name": "node2", "disks": [3, 4], },
      { "name": "node3", "disks": [5, 6, 7], },
      ]

    self.assertEqual(q.Query(_QueryData(data, mastername="node3")),
                     [[(constants.RS_NORMAL, "node1")],
                      [(constants.RS_NORMAL, "node2")],
                      [(constants.RS_NORMAL, "node3")]])
    self.assertEqual(q.OldStyleQuery(_QueryData(data, mastername="node3")),
                     [["node1"], ["node2"], ["node3"]])

    q = query.Query(fielddef, ["name", "master"])
    self.assertEqual(q.RequestedData(), set([STATIC]))
    self.assertEqual(len(q._fields), 2)
    self.assertEqual(q.Query(_QueryData(data, mastername="node3")),
                     [[(constants.RS_NORMAL, "node1"),
                       (constants.RS_NORMAL, False)],
                      [(constants.RS_NORMAL, "node2"),
                       (constants.RS_NORMAL, False)],
                      [(constants.RS_NORMAL, "node3"),
                       (constants.RS_NORMAL, True)],
                     ])

    q = query.Query(fielddef, ["name", "master", "disk0.size"])
    self.assertEqual(q.RequestedData(), set([STATIC, DISK]))
    self.assertEqual(len(q._fields), 3)
    self.assertEqual(q.Query(_QueryData(data, mastername="node2")),
                     [[(constants.RS_NORMAL, "node1"),
                       (constants.RS_NORMAL, False),
                       (constants.RS_NORMAL, 0)],
                      [(constants.RS_NORMAL, "node2"),
                       (constants.RS_NORMAL, True),
                       (constants.RS_NORMAL, 3)],
                      [(constants.RS_NORMAL, "node3"),
                       (constants.RS_NORMAL, False),
                       (constants.RS_NORMAL, 5)],
                     ])

    # With unknown column
    q = query.Query(fielddef, ["disk2.size", "disk1.size", "disk99.size",
                               "disk0.size"])
    self.assertEqual(q.RequestedData(), set([DISK]))
    self.assertEqual(len(q._fields), 4)
    self.assertEqual(q.Query(_QueryData(data, mastername="node2")),
                     [[(constants.RS_NORMAL, 2),
                       (constants.RS_NORMAL, 1),
                       (constants.RS_UNKNOWN, None),
                       (constants.RS_NORMAL, 0)],
                      [(constants.RS_UNAVAIL, None),
                       (constants.RS_NORMAL, 4),
                       (constants.RS_UNKNOWN, None),
                       (constants.RS_NORMAL, 3)],
                      [(constants.RS_NORMAL, 7),
                       (constants.RS_NORMAL, 6),
                       (constants.RS_UNKNOWN, None),
                       (constants.RS_NORMAL, 5)],
                     ])
    self.assertRaises(errors.OpPrereqError, q.OldStyleQuery,
                      _QueryData(data, mastername="node2"))
    self.assertEqual([fdef.ToDict() for fdef in q.GetFields()], [
                     { "name": "disk2.size", "title": "DiskSize2",
                       "kind": constants.QFT_UNIT, "doc": "Disk size 2", },
                     { "name": "disk1.size", "title": "DiskSize1",
                       "kind": constants.QFT_UNIT, "doc": "Disk size 1", },
                     { "name": "disk99.size", "title": "disk99.size",
                       "kind": constants.QFT_UNKNOWN,
                       "doc": "Unknown field 'disk99.size'", },
                     { "name": "disk0.size", "title": "DiskSize0",
                       "kind": constants.QFT_UNIT, "doc": "Disk size 0", },
                     ])

    # Empty query
    q = query.Query(fielddef, [])
    self.assertEqual(q.RequestedData(), set([]))
    self.assertEqual(len(q._fields), 0)
    self.assertEqual(q.Query(_QueryData(data, mastername="node2")),
                     [[], [], []])
    self.assertEqual(q.OldStyleQuery(_QueryData(data, mastername="node2")),
                     [[], [], []])
    self.assertEqual(q.GetFields(), [])

  def testPrepareFieldList(self):
    # Duplicate titles
    for (a, b) in [("name", "name"), ("NAME", "name")]:
      self.assertRaises(AssertionError, query._PrepareFieldList, [
        (query._MakeField("name", b, constants.QFT_TEXT, "Name"), None, 0,
         lambda *args: None),
        (query._MakeField("other", a, constants.QFT_TEXT, "Other"), None, 0,
         lambda *args: None),
        ], [])

    # Non-lowercase names
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("NAME", "Name", constants.QFT_TEXT, "Name"), None, 0,
       lambda *args: None),
      ], [])
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("Name", "Name", constants.QFT_TEXT, "Name"), None, 0,
       lambda *args: None),
      ], [])

    # Empty name
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("", "Name", constants.QFT_TEXT, "Name"), None, 0,
       lambda *args: None),
      ], [])

    # Empty title
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "", constants.QFT_TEXT, "Name"), None, 0,
       lambda *args: None),
      ], [])

    # Whitespace in title
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "Co lu mn", constants.QFT_TEXT, "Name"),
       None, 0, lambda *args: None),
      ], [])

    # No callable function
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       None, 0, None),
      ], [])

    # Invalid documentation
    for doc in ["", ".", "Hello world\n", "Hello\nWo\nrld", "Hello World!",
                "HelloWorld.", "only lowercase", ",", " x y z .\t", "  "]:
      self.assertRaises(AssertionError, query._PrepareFieldList, [
        (query._MakeField("name", "Name", constants.QFT_TEXT, doc),
        None, 0, lambda *args: None),
        ], [])

    # Duplicate field name
    self.assertRaises(ValueError, query._PrepareFieldList, [
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       None, 0, lambda *args: None),
      (query._MakeField("name", "Other", constants.QFT_OTHER, "Other"),
       None, 0, lambda *args: None),
      ], [])

  def testUnknown(self):
    fielddef = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       None, 0, lambda _, item: "name%s" % item),
      (query._MakeField("other0", "Other0", constants.QFT_TIMESTAMP, "Other"),
       None, 0, lambda *args: 1234),
      (query._MakeField("nodata", "NoData", constants.QFT_NUMBER, "No data"),
       None, 0, lambda *args: query._FS_NODATA ),
      (query._MakeField("unavail", "Unavail", constants.QFT_BOOL, "Unavail"),
       None, 0, lambda *args: query._FS_UNAVAIL),
      ], [])

    for selected in [["foo"], ["Hello", "World"],
                     ["name1", "other", "foo"]]:
      q = query.Query(fielddef, selected)
      self.assertEqual(len(q._fields), len(selected))
      self.assertTrue(compat.all(len(row) == len(selected)
                              for row in q.Query(_QueryData(range(1, 10)))))
      self.assertEqual(q.Query(_QueryData(range(1, 10))),
                       [[(constants.RS_UNKNOWN, None)] * len(selected)
                        for i in range(1, 10)])
      self.assertEqual([fdef.ToDict() for fdef in q.GetFields()],
                       [{ "name": name, "title": name,
                          "kind": constants.QFT_UNKNOWN,
                          "doc": "Unknown field '%s'" % name}
                        for name in selected])

    q = query.Query(fielddef, ["name", "other0", "nodata", "unavail"])
    self.assertEqual(len(q._fields), 4)
    self.assertEqual(q.OldStyleQuery(_QueryData(range(1, 10))), [
                     ["name%s" % i, 1234, None, None]
                     for i in range(1, 10)
                     ])

    q = query.Query(fielddef, ["name", "other0", "nodata", "unavail", "unk"])
    self.assertEqual(len(q._fields), 5)
    self.assertEqual(q.Query(_QueryData(range(1, 10))),
                     [[(constants.RS_NORMAL, "name%s" % i),
                       (constants.RS_NORMAL, 1234),
                       (constants.RS_NODATA, None),
                       (constants.RS_UNAVAIL, None),
                       (constants.RS_UNKNOWN, None)]
                      for i in range(1, 10)])

  def testAliases(self):
    fields = [
      (query._MakeField("a", "a-title", constants.QFT_TEXT, "Field A"),
       None, 0, lambda *args: None),
      (query._MakeField("b", "b-title", constants.QFT_TEXT, "Field B"),
       None, 0, lambda *args: None),
      ]
    # duplicate field
    self.assertRaises(AssertionError, query._PrepareFieldList, fields,
                      [("b", "a")])
    self.assertRaises(AssertionError, query._PrepareFieldList, fields,
                      [("c", "b"), ("c", "a")])
    # missing target
    self.assertRaises(AssertionError, query._PrepareFieldList, fields,
                      [("c", "d")])
    fdefs = query._PrepareFieldList(fields, [("c", "b")])
    self.assertEqual(len(fdefs), 3)
    self.assertEqual(fdefs["b"][1:], fdefs["c"][1:])


class TestGetNodeRole(unittest.TestCase):
  def test(self):
    tested_role = set()
    master_uuid = "969502b9-f632-4d3d-83a5-a78b0ca8cdf6"
    node_uuid = "d75499b5-83e3-4b80-b6fe-3e1aee7e5a35"
    checks = [
      (constants.NR_MASTER,
       objects.Node(name="node1", uuid=master_uuid)),
      (constants.NR_MCANDIDATE,
       objects.Node(name="node1", uuid=node_uuid, master_candidate=True)),
      (constants.NR_REGULAR,
       objects.Node(name="node1", uuid=node_uuid)),
      (constants.NR_DRAINED,
       objects.Node(name="node1", uuid=node_uuid, drained=True)),
      (constants.NR_OFFLINE,
       objects.Node(name="node1", uuid=node_uuid, offline=True)),
      ]

    for (role, node) in checks:
      result = query._GetNodeRole(node, master_uuid)
      self.assertEqual(result, role)
      tested_role.add(result)

    self.assertEqual(tested_role, constants.NR_ALL)


class TestNodeQuery(unittest.TestCase):
  def _Create(self, selected):
    return query.Query(query.NODE_FIELDS, selected)

  def testSimple(self):
    cluster = objects.Cluster(cluster_name="testcluster",
                              ndparams=constants.NDC_DEFAULTS.copy())
    grp1 = objects.NodeGroup(name="default",
                             uuid="c0e89160-18e7-11e0-a46e-001d0904baeb",
                             alloc_policy=constants.ALLOC_POLICY_PREFERRED,
                             ipolicy=objects.MakeEmptyIPolicy(),
                             ndparams={},
                             )
    grp2 = objects.NodeGroup(name="group2",
                             uuid="c0e89160-18e7-11e0-a46e-001d0904babe",
                             alloc_policy=constants.ALLOC_POLICY_PREFERRED,
                             ipolicy=objects.MakeEmptyIPolicy(),
                             ndparams={constants.ND_SPINDLE_COUNT: 2},
                             )
    groups = {grp1.uuid: grp1, grp2.uuid: grp2}
    nodes = [
      objects.Node(name="node1", drained=False, group=grp1.uuid, ndparams={}),
      objects.Node(name="node2", drained=True, group=grp2.uuid, ndparams={}),
      objects.Node(name="node3", drained=False, group=grp1.uuid,
                   ndparams={constants.ND_SPINDLE_COUNT: 4}),
      ]
    for live_data in [None, dict.fromkeys([node.name for node in nodes], {})]:
      nqd = query.NodeQueryData(nodes, live_data, None, None, None, None,
                                groups, None, cluster)

      q = self._Create(["name", "drained"])
      self.assertEqual(q.RequestedData(), set([query.NQ_CONFIG]))
      self.assertEqual(q.Query(nqd),
                       [[(constants.RS_NORMAL, "node1"),
                         (constants.RS_NORMAL, False)],
                        [(constants.RS_NORMAL, "node2"),
                         (constants.RS_NORMAL, True)],
                        [(constants.RS_NORMAL, "node3"),
                         (constants.RS_NORMAL, False)],
                       ])
      self.assertEqual(q.OldStyleQuery(nqd),
                       [["node1", False],
                        ["node2", True],
                        ["node3", False]])
      q = self._Create(["ndp/spindle_count"])
      self.assertEqual(q.RequestedData(), set([query.NQ_GROUP]))
      self.assertEqual(q.Query(nqd),
                       [[(constants.RS_NORMAL,
                          constants.NDC_DEFAULTS[constants.ND_SPINDLE_COUNT])],
                        [(constants.RS_NORMAL,
                          grp2.ndparams[constants.ND_SPINDLE_COUNT])],
                        [(constants.RS_NORMAL,
                          nodes[2].ndparams[constants.ND_SPINDLE_COUNT])],
                       ])

  def test(self):
    selected = list(query.NODE_FIELDS)
    field_index = dict((field, idx) for idx, field in enumerate(selected))

    q = self._Create(selected)
    self.assertEqual(q.RequestedData(),
                     set([query.NQ_CONFIG, query.NQ_LIVE, query.NQ_INST,
                          query.NQ_GROUP, query.NQ_OOB]))

    cluster = objects.Cluster(cluster_name="testcluster",
      hvparams=constants.HVC_DEFAULTS,
      beparams={
        constants.PP_DEFAULT: constants.BEC_DEFAULTS,
        },
      nicparams={
        constants.PP_DEFAULT: constants.NICC_DEFAULTS,
        },
      ndparams=constants.NDC_DEFAULTS,
        )

    node_names = ["node%s" % i for i in range(20)]
    master_name = node_names[3]
    nodes = [
      objects.Node(name=name,
                   primary_ip="192.0.2.%s" % idx,
                   secondary_ip="192.0.100.%s" % idx,
                   serial_no=7789 * idx,
                   master_candidate=(name != master_name and idx % 3 == 0),
                   offline=False,
                   drained=False,
                   powered=True,
                   vm_capable=True,
                   master_capable=False,
                   ndparams={},
                   group="default",
                   ctime=1290006900,
                   mtime=1290006913,
                   uuid="fd9ccebe-6339-43c9-a82e-94bbe575%04d" % idx)
      for idx, name in enumerate(node_names)
      ]

    master_node = nodes[3]
    master_node.AddTag("masternode")
    master_node.AddTag("another")
    master_node.AddTag("tag")
    master_node.ctime = None
    master_node.mtime = None
    assert master_node.name == master_name

    live_data_node = nodes[4]
    assert live_data_node.name != master_name

    fake_live_data = {
      "bootid": "a2504766-498e-4b25-b21e-d23098dc3af4",
      "cnodes": 4,
      "cnos": 3,
      "csockets": 4,
      "ctotal": 8,
      "mnode": 128,
      "mfree": 100,
      "mtotal": 4096,
      "dfree": 5 * 1024 * 1024,
      "dtotal": 100 * 1024 * 1024,
      "spfree": 0,
      "sptotal": 0,
      }

    assert (sorted(query._NODE_LIVE_FIELDS.keys()) ==
            sorted(fake_live_data.keys()))

    live_data = dict.fromkeys([node.uuid for node in nodes], {})
    live_data[live_data_node.uuid] = \
      dict((query._NODE_LIVE_FIELDS[name][2], value)
           for name, value in fake_live_data.items())

    node_to_primary_uuid = dict((node.uuid, set()) for node in nodes)
    node_to_primary_uuid[master_node.uuid].update(["inst1", "inst2"])

    node_to_secondary_uuid = dict((node.uuid, set()) for node in nodes)
    node_to_secondary_uuid[live_data_node.uuid].update(["instX", "instY",
                                                        "instZ"])

    inst_uuid_to_inst_name = {
      "inst1": "inst1-name",
      "inst2": "inst2-name",
      "instX": "instX-name",
      "instY": "instY-name",
      "instZ": "instZ-name"
    }

    ng_uuid = "492b4b74-8670-478a-b98d-4c53a76238e6"
    groups = {
      ng_uuid: objects.NodeGroup(name="ng1", uuid=ng_uuid, ndparams={}),
      }

    oob_not_powered_node = nodes[0]
    oob_not_powered_node.powered = False
    oob_support = dict((node.uuid, False) for node in nodes)
    oob_support[master_node.uuid] = True
    oob_support[oob_not_powered_node.uuid] = True

    master_node.group = ng_uuid

    nqd = query.NodeQueryData(nodes, live_data, master_node.uuid,
                              node_to_primary_uuid, node_to_secondary_uuid,
                              inst_uuid_to_inst_name, groups, oob_support,
                              cluster)
    result = q.Query(nqd)
    self.assertTrue(compat.all(len(row) == len(selected) for row in result))
    self.assertEqual([row[field_index["name"]] for row in result],
                     [(constants.RS_NORMAL, name) for name in node_names])

    node_to_row = dict((row[field_index["name"]][1], idx)
                       for idx, row in enumerate(result))

    master_row = result[node_to_row[master_name]]
    self.assertTrue(master_row[field_index["master"]])
    self.assertTrue(master_row[field_index["role"]], "M")
    self.assertEqual(master_row[field_index["group"]],
                     (constants.RS_NORMAL, "ng1"))
    self.assertEqual(master_row[field_index["group.uuid"]],
                     (constants.RS_NORMAL, ng_uuid))
    self.assertEqual(master_row[field_index["ctime"]],
                     (constants.RS_UNAVAIL, None))
    self.assertEqual(master_row[field_index["mtime"]],
                     (constants.RS_UNAVAIL, None))

    self.assertTrue(row[field_index["pip"]] == node.primary_ip and
                 row[field_index["sip"]] == node.secondary_ip and
                 set(row[field_index["tags"]]) == node.GetTags() and
                 row[field_index["serial_no"]] == node.serial_no and
                 row[field_index["role"]] == query._GetNodeRole(node,
                                                                master_name) and
                 (node.name == master_name or
                  (row[field_index["group"]] == "<unknown>" and
                   row[field_index["group.uuid"]] is None and
                   row[field_index["ctime"]] == (constants.RS_NORMAL,
                                                 node.ctime) and
                   row[field_index["mtime"]] == (constants.RS_NORMAL,
                                                 node.mtime) and
                   row[field_index["powered"]] == (constants.RS_NORMAL,
                                                   True))) or
                 (node.name == oob_not_powered_node and
                  row[field_index["powered"]] == (constants.RS_NORMAL,
                                                  False)) or
                 row[field_index["powered"]] == (constants.RS_UNAVAIL, None)
                 for row, node in zip(result, nodes))

    live_data_row = result[node_to_row[live_data_node.name]]

    for (field, value) in fake_live_data.items():
      self.assertEqual(live_data_row[field_index[field]],
                       (constants.RS_NORMAL, value))

    self.assertEqual(master_row[field_index["pinst_cnt"]],
                     (constants.RS_NORMAL, 2))
    self.assertEqual(live_data_row[field_index["sinst_cnt"]],
                     (constants.RS_NORMAL, 3))
    self.assertEqual(master_row[field_index["pinst_list"]],
                     (constants.RS_NORMAL,
                      [inst_uuid_to_inst_name[uuid] for uuid in
                       node_to_primary_uuid[master_node.uuid]]))
    self.assertEqual(live_data_row[field_index["sinst_list"]],
                     (constants.RS_NORMAL,
                      utils.NiceSort(
                        [inst_uuid_to_inst_name[uuid] for uuid in
                        node_to_secondary_uuid[live_data_node.uuid]])))

  def testGetLiveNodeField(self):
    nodes = [
      objects.Node(name="node1", drained=False, offline=False,
                   vm_capable=True),
      objects.Node(name="node2", drained=True, offline=False,
                   vm_capable=True),
      objects.Node(name="node3", drained=False, offline=False,
                   vm_capable=True),
      objects.Node(name="node4", drained=False, offline=True,
                   vm_capable=True),
      objects.Node(name="node5", drained=False, offline=False,
                   vm_capable=False),
      ]
    live_data = dict.fromkeys([node.name for node in nodes], {})

    # No data
    nqd = query.NodeQueryData(None, None, None, None, None, None, None, None,
                              None)
    self.assertEqual(query._GetLiveNodeField("hello", constants.QFT_NUMBER,
                                             nqd, nodes[0]),
                     query._FS_NODATA)

    # Missing field
    ctx = _QueryData(None, curlive_data={
      "some": 1,
      "other": 2,
      })
    self.assertEqual(query._GetLiveNodeField("hello", constants.QFT_NUMBER,
                                             ctx, nodes[0]),
                     query._FS_UNAVAIL)

    # Wrong format/datatype
    ctx = _QueryData(None, curlive_data={
      "hello": ["Hello World"],
      "other": 2,
      })
    self.assertEqual(query._GetLiveNodeField("hello", constants.QFT_NUMBER,
                                             ctx, nodes[0]),
                     query._FS_UNAVAIL)

    # Offline node
    assert nodes[3].offline
    ctx = _QueryData(None, curlive_data={})
    self.assertEqual(query._GetLiveNodeField("hello", constants.QFT_NUMBER,
                                             ctx, nodes[3]),
                     query._FS_OFFLINE, None)

    # Wrong field type
    ctx = _QueryData(None, curlive_data={"hello": 123})
    self.assertRaises(AssertionError, query._GetLiveNodeField,
                      "hello", constants.QFT_BOOL, ctx, nodes[0])

    # Non-vm_capable node
    assert not nodes[4].vm_capable
    ctx = _QueryData(None, curlive_data={})
    self.assertEqual(query._GetLiveNodeField("hello", constants.QFT_NUMBER,
                                             ctx, nodes[4]),
                     query._FS_UNAVAIL, None)


class TestInstanceQuery(unittest.TestCase):
  def _Create(self, selected):
    return query.Query(query.INSTANCE_FIELDS, selected)

  def testSimple(self):
    q = self._Create(["name", "be/maxmem", "ip"])
    self.assertEqual(q.RequestedData(), set([query.IQ_CONFIG]))

    cluster = objects.Cluster(cluster_name="testcluster",
      hvparams=constants.HVC_DEFAULTS,
      beparams={
        constants.PP_DEFAULT: constants.BEC_DEFAULTS,
        },
      nicparams={
        constants.PP_DEFAULT: constants.NICC_DEFAULTS,
        },
      os_hvp={},
      osparams={})

    instances = [
      objects.Instance(name="inst1", hvparams={}, beparams={}, osparams={},
                       nics=[], os="deb1"),
      objects.Instance(name="inst2", hvparams={}, nics=[], osparams={},
        os="foomoo",
        beparams={
          constants.BE_MAXMEM: 512,
        }),
      objects.Instance(name="inst3", hvparams={}, beparams={}, osparams={},
        os="dos", nics=[objects.NIC(ip="192.0.2.99", nicparams={})]),
      ]

    iqd = query.InstanceQueryData(instances, cluster, None, [], [], {},
                                  set(), {}, None, None, None)
    self.assertEqual(q.Query(iqd),
      [[(constants.RS_NORMAL, "inst1"),
        (constants.RS_NORMAL, 128),
        (constants.RS_UNAVAIL, None),
       ],
       [(constants.RS_NORMAL, "inst2"),
        (constants.RS_NORMAL, 512),
        (constants.RS_UNAVAIL, None),
       ],
       [(constants.RS_NORMAL, "inst3"),
        (constants.RS_NORMAL, 128),
        (constants.RS_NORMAL, "192.0.2.99"),
       ]])
    self.assertEqual(q.OldStyleQuery(iqd),
      [["inst1", 128, None],
       ["inst2", 512, None],
       ["inst3", 128, "192.0.2.99"]])

  def test(self):
    selected = list(query.INSTANCE_FIELDS)
    fieldidx = dict((field, idx) for idx, field in enumerate(selected))

    macs = ["00:11:22:%02x:%02x:%02x" % (i % 255, i % 3, (i * 123) % 255)
            for i in range(20)]

    q = self._Create(selected)
    self.assertEqual(q.RequestedData(),
                     set([query.IQ_CONFIG, query.IQ_LIVE, query.IQ_DISKUSAGE,
                          query.IQ_CONSOLE, query.IQ_NODES, query.IQ_NETWORKS]))

    cluster = objects.Cluster(cluster_name="testcluster",
      enabled_user_shutdown=True,
      hvparams=constants.HVC_DEFAULTS,
      beparams={
        constants.PP_DEFAULT: constants.BEC_DEFAULTS,
        },
      nicparams={
        constants.PP_DEFAULT: constants.NICC_DEFAULTS,
        },
      os_hvp={},
      tcpudp_port_pool=set(),
      osparams={
        "deb99": {
          "clean_install": "yes",
          },
        })

    offline_nodes = ["nodeoff1-uuid", "nodeoff2-uuid"]
    bad_nodes = ["nodebad1-uuid", "nodebad2-uuid", "nodebad3-uuid"] +\
                offline_nodes
    node_uuids = ["node%s-uuid" % i for i in range(10)] + bad_nodes

    instances = [
      objects.Instance(name="inst1", hvparams={}, beparams={}, nics=[],
        uuid="inst1-uuid",
        ctime=1291244000, mtime=1291244400, serial_no=30,
        admin_state=constants.ADMINST_UP,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_XEN_PVM,
        os="linux1",
        primary_node="node1-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_PLAIN,
        disks=[],
        disks_active=True,
        osparams={}),
      objects.Instance(name="inst2", hvparams={}, nics=[],
        uuid="inst2-uuid",
        ctime=1291211000, mtime=1291211077, serial_no=1,
        admin_state=constants.ADMINST_UP,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_XEN_HVM,
        os="deb99",
        primary_node="node5-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_DISKLESS,
        disks=[],
        disks_active=True,
        beparams={
          constants.BE_MAXMEM: 512,
          constants.BE_MINMEM: 256,
        },
        osparams={}),
      objects.Instance(name="inst3", hvparams={}, beparams={},
        uuid="inst3-uuid",
        ctime=1291011000, mtime=1291013000, serial_no=1923,
        admin_state=constants.ADMINST_DOWN,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_KVM,
        os="busybox",
        primary_node="node6-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_DRBD8,
        disks=[],
        disks_active=False,
        nics=[
          objects.NIC(ip="192.0.2.99", mac=macs.pop(),
                      nicparams={
                        constants.NIC_LINK: constants.DEFAULT_BRIDGE,
                        }),
          objects.NIC(ip=None, mac=macs.pop(), nicparams={}),
          ],
        osparams={}),
      objects.Instance(name="inst4", hvparams={}, beparams={},
        uuid="inst4-uuid",
        ctime=1291244390, mtime=1291244395, serial_no=25,
        admin_state=constants.ADMINST_DOWN,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_XEN_PVM,
        os="linux1",
        primary_node="nodeoff2-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_DRBD8,
        disks=[],
        disks_active=True,
        nics=[
          objects.NIC(ip="192.0.2.1", mac=macs.pop(),
                      nicparams={
                        constants.NIC_LINK: constants.DEFAULT_BRIDGE,
                        }),
          objects.NIC(ip="192.0.2.2", mac=macs.pop(), nicparams={}),
          objects.NIC(ip="192.0.2.3", mac=macs.pop(),
                      nicparams={
                        constants.NIC_MODE: constants.NIC_MODE_ROUTED,
                        }),
          objects.NIC(ip="192.0.2.4", mac=macs.pop(),
                      nicparams={
                        constants.NIC_MODE: constants.NIC_MODE_BRIDGED,
                        constants.NIC_LINK: "eth123",
                        }),
          ],
        osparams={}),
      objects.Instance(name="inst5", hvparams={}, nics=[],
        uuid="inst5-uuid",
        ctime=1231211000, mtime=1261200000, serial_no=3,
        admin_state=constants.ADMINST_UP,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_XEN_HVM,
        os="deb99",
        primary_node="nodebad2-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_DISKLESS,
        disks=[],
        disks_active=True,
        beparams={
          constants.BE_MAXMEM: 512,
          constants.BE_MINMEM: 512,
        },
        osparams={}),
      objects.Instance(name="inst6", hvparams={}, nics=[],
        uuid="inst6-uuid",
        ctime=7513, mtime=11501, serial_no=13390,
        admin_state=constants.ADMINST_DOWN,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_XEN_HVM,
        os="deb99",
        primary_node="node7-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_DISKLESS,
        disks=[],
        disks_active=False,
        beparams={
          constants.BE_MAXMEM: 768,
          constants.BE_MINMEM: 256,
        },
        osparams={
          "clean_install": "no",
          }),
      objects.Instance(name="inst7", hvparams={}, nics=[],
        uuid="inst7-uuid",
        ctime=None, mtime=None, serial_no=1947,
        admin_state=constants.ADMINST_DOWN,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_XEN_HVM,
        os="deb99",
        primary_node="node6-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_DISKLESS,
        disks=[],
        disks_active=False,
        beparams={},
        osparams={}),
      objects.Instance(name="inst8", hvparams={}, nics=[],
        uuid="inst8-uuid",
        ctime=None, mtime=None, serial_no=19478,
        admin_state=constants.ADMINST_OFFLINE,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_XEN_HVM,
        os="deb99",
        primary_node="node6-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_DISKLESS,
        disks=[],
        disks_active=False,
        beparams={},
        osparams={}),
      objects.Instance(
        name="inst9",
        hvparams={constants.HV_KVM_USER_SHUTDOWN: True},
        nics=[],
        uuid="inst9-uuid",
        ctime=None, mtime=None, serial_no=19478,
        admin_state=constants.ADMINST_UP,
        admin_state_source=constants.ADMIN_SOURCE,
        hypervisor=constants.HT_XEN_HVM,
        os="deb99",
        primary_node="node6-uuid",
        secondary_nodes=[],
        disk_template=constants.DT_DISKLESS,
        disks=[],
        disks_active=False,
        beparams={},
        osparams={}),
      ]

    assert not utils.FindDuplicates(inst.uuid for inst in instances)
    assert not utils.FindDuplicates(inst.name for inst in instances)

    instbyname = dict((inst.name, inst) for inst in instances)

    disk_usage = dict((inst.uuid,
                       gmi.ComputeDiskSize([{"size": disk.size,
                                             "dev_type": disk.dev_type}
                                           for disk in inst.disks]))
                      for inst in instances)

    inst_bridges = {
      "inst3-uuid": [constants.DEFAULT_BRIDGE, constants.DEFAULT_BRIDGE],
      "inst4-uuid": [constants.DEFAULT_BRIDGE, constants.DEFAULT_BRIDGE,
                     None, "eth123"],
      }

    live_data = {
      "inst2-uuid": {
        "vcpus": 3,
        "state": hv_base.HvInstanceState.RUNNING,
        },
      "inst4-uuid": {
        "memory": 123,
        "state": hv_base.HvInstanceState.RUNNING,
        },
      "inst6-uuid": {
        "memory": 768,
        "state": hv_base.HvInstanceState.RUNNING,
        },
      "inst7-uuid": {
        "vcpus": 3,
        "state": hv_base.HvInstanceState.RUNNING,
        },
      "inst9-uuid": {
        "vcpus": 3,
        "state": hv_base.HvInstanceState.SHUTDOWN,
        },
      }
    wrongnode_inst = set(["inst7-uuid"])

    consinfo = dict((inst.uuid, None) for inst in instances)
    consinfo["inst7-uuid"] = \
      objects.InstanceConsole(instance="inst7", kind=constants.CONS_SSH,
                              host=instbyname["inst7"].primary_node,
                              user="root",
                              command=["hostname"]).ToDict()

    nodes = dict([(uuid, objects.Node(
                           name="%s.example.com" % uuid,
                           uuid=uuid,
                           group="default-uuid"))
                  for uuid in node_uuids])

    iqd = query.InstanceQueryData(instances, cluster, disk_usage,
                                  offline_nodes, bad_nodes, live_data,
                                  wrongnode_inst, consinfo, nodes, {}, {})
    result = q.Query(iqd)
    self.assertEqual(len(result), len(instances))
    self.assertTrue(compat.all(len(row) == len(selected)
                            for row in result))

    assert len(set(bad_nodes) & set(offline_nodes)) == len(offline_nodes), \
           "Offline nodes not included in bad nodes"

    tested_status = set()

    for (inst, row) in zip(instances, result):
      assert inst.primary_node in node_uuids

      self.assertEqual(row[fieldidx["name"]],
                       (constants.RS_NORMAL, inst.name))

      if inst.primary_node in offline_nodes:
        exp_status = constants.INSTST_NODEOFFLINE
      elif inst.primary_node in bad_nodes:
        exp_status = constants.INSTST_NODEDOWN
      elif inst.uuid in live_data:
        if inst.uuid in wrongnode_inst:
          exp_status = constants.INSTST_WRONGNODE
        else:
          instance_state = live_data[inst.uuid]["state"]
          if hv_base.HvInstanceState.IsShutdown(instance_state):
            if inst.admin_state == constants.ADMINST_UP:
              exp_status = constants.INSTST_USERDOWN
            else:
              exp_status = constants.INSTST_ADMINDOWN
          else:
            if inst.admin_state == constants.ADMINST_UP:
              exp_status = constants.INSTST_RUNNING
            else:
              exp_status = constants.INSTST_ERRORUP
      else:
        if inst.admin_state == constants.ADMINST_UP:
          exp_status = constants.INSTST_ERRORDOWN
        elif inst.admin_state == constants.ADMINST_DOWN:
          if inst.admin_state_source == constants.USER_SOURCE:
            exp_status = constants.INSTST_USERDOWN
          else:
            exp_status = constants.INSTST_ADMINDOWN
        else:
          exp_status = constants.INSTST_ADMINOFFLINE

      self.assertEqual(row[fieldidx["status"]],
                       (constants.RS_NORMAL, exp_status))

      (_, status) = row[fieldidx["status"]]
      tested_status.add(status)

      #FIXME(dynmem): check oper_ram vs min/max mem
      for (field, livefield) in [("oper_vcpus", "vcpus")]:
        if inst.primary_node in bad_nodes:
          exp = (constants.RS_NODATA, None)
        elif inst.uuid in live_data:
          value = live_data[inst.uuid].get(livefield, None)
          if value is None:
            exp = (constants.RS_UNAVAIL, None)
          else:
            exp = (constants.RS_NORMAL, value)
        else:
          exp = (constants.RS_UNAVAIL, None)

        self.assertEqual(row[fieldidx[field]], exp)

      bridges = inst_bridges.get(inst.uuid, [])
      self.assertEqual(row[fieldidx["nic.bridges"]],
                       (constants.RS_NORMAL, bridges))
      if bridges:
        self.assertEqual(row[fieldidx["bridge"]],
                         (constants.RS_NORMAL, bridges[0]))
      else:
        self.assertEqual(row[fieldidx["bridge"]],
                         (constants.RS_UNAVAIL, None))

      for i in range(constants.MAX_NICS):
        if i < len(bridges) and bridges[i] is not None:
          exp = (constants.RS_NORMAL, bridges[i])
        else:
          exp = (constants.RS_UNAVAIL, None)
        self.assertEqual(row[fieldidx["nic.bridge/%s" % i]], exp)

      if inst.primary_node in bad_nodes:
        exp = (constants.RS_NODATA, None)
      else:
        exp = (constants.RS_NORMAL, inst.uuid in live_data)
      self.assertEqual(row[fieldidx["oper_state"]], exp)

      cust_exp = (constants.RS_NORMAL, {})
      if inst.os == "deb99":
        if inst.uuid == "inst6-uuid":
          exp = (constants.RS_NORMAL, {"clean_install": "no"})
          cust_exp = exp
        else:
          exp = (constants.RS_NORMAL, {"clean_install": "yes"})
      else:
        exp = (constants.RS_NORMAL, {})
      self.assertEqual(row[fieldidx["osparams"]], exp)
      self.assertEqual(row[fieldidx["custom_osparams"]], cust_exp)

      usage = disk_usage[inst.uuid]
      if usage is None:
        usage = 0
      self.assertEqual(row[fieldidx["disk_usage"]],
                       (constants.RS_NORMAL, usage))

      for alias, target in [("sda_size", "disk.size/0"),
                            ("sdb_size", "disk.size/1"),
                            ("vcpus", "be/vcpus"),
                            ("ip", "nic.ip/0"),
                            ("mac", "nic.mac/0"),
                            ("bridge", "nic.bridge/0"),
                            ("nic_mode", "nic.mode/0"),
                            ("nic_link", "nic.link/0"),
                            ]:
        self.assertEqual(row[fieldidx[alias]], row[fieldidx[target]])

      for field in ["ctime", "mtime"]:
        if getattr(inst, field) is None:
          # No ctime/mtime
          exp = (constants.RS_UNAVAIL, None)
        else:
          exp = (constants.RS_NORMAL, getattr(inst, field))
        self.assertEqual(row[fieldidx[field]], exp)

      self._CheckInstanceConsole(inst, row[fieldidx["console"]])

    # Ensure all possible status' have been tested
    self.assertEqual(tested_status, set(constants.INSTST_ALL))

  def _CheckInstanceConsole(self, instance, console_info):
    (status, consdata) = console_info
    if instance.name == "inst7":
      self.assertEqual(status, constants.RS_NORMAL)
      console = objects.InstanceConsole.FromDict(consdata)
      self.assertEqual(console.Validate(), None)
      self.assertEqual(console.host, instance.primary_node)
    else:
      self.assertEqual(status, constants.RS_UNAVAIL)


class TestGroupQuery(unittest.TestCase):

  def setUp(self):
    self.custom_diskparams = {
      constants.DT_DRBD8: {
        constants.DRBD_DEFAULT_METAVG: "foobar",
      },
    }

    self.groups = [
      objects.NodeGroup(name="default",
                        uuid="c0e89160-18e7-11e0-a46e-001d0904baeb",
                        alloc_policy=constants.ALLOC_POLICY_PREFERRED,
                        ipolicy=objects.MakeEmptyIPolicy(),
                        ndparams={},
                        diskparams={},
                        ),
      objects.NodeGroup(name="restricted",
                        uuid="d2a40a74-18e7-11e0-9143-001d0904baeb",
                        alloc_policy=constants.ALLOC_POLICY_LAST_RESORT,
                        ipolicy=objects.MakeEmptyIPolicy(),
                        ndparams={},
                        diskparams=self.custom_diskparams,
                        ),
      ]
    self.cluster = objects.Cluster(cluster_name="testcluster",
      hvparams=constants.HVC_DEFAULTS,
      beparams={
        constants.PP_DEFAULT: constants.BEC_DEFAULTS,
        },
      nicparams={
        constants.PP_DEFAULT: constants.NICC_DEFAULTS,
        },
      ndparams=constants.NDC_DEFAULTS,
      ipolicy=constants.IPOLICY_DEFAULTS,
      diskparams=constants.DISK_DT_DEFAULTS,
      )

  def _Create(self, selected):
    return query.Query(query.GROUP_FIELDS, selected)

  def testSimple(self):
    q = self._Create(["name", "uuid", "alloc_policy"])
    gqd = query.GroupQueryData(self.cluster, self.groups, None, None, False)

    self.assertEqual(q.RequestedData(), set([query.GQ_CONFIG]))

    self.assertEqual(q.Query(gqd),
      [[(constants.RS_NORMAL, "default"),
        (constants.RS_NORMAL, "c0e89160-18e7-11e0-a46e-001d0904baeb"),
        (constants.RS_NORMAL, constants.ALLOC_POLICY_PREFERRED)
        ],
       [(constants.RS_NORMAL, "restricted"),
        (constants.RS_NORMAL, "d2a40a74-18e7-11e0-9143-001d0904baeb"),
        (constants.RS_NORMAL, constants.ALLOC_POLICY_LAST_RESORT)
        ],
       ])

  def testNodes(self):
    groups_to_nodes = {
      "c0e89160-18e7-11e0-a46e-001d0904baeb": ["node1", "node2"],
      "d2a40a74-18e7-11e0-9143-001d0904baeb": ["node1", "node10", "node9"],
      }

    q = self._Create(["name", "node_cnt", "node_list"])
    gqd = query.GroupQueryData(self.cluster, self.groups, groups_to_nodes, None,
                               False)

    self.assertEqual(q.RequestedData(), set([query.GQ_CONFIG, query.GQ_NODE]))

    self.assertEqual(q.Query(gqd),
                     [[(constants.RS_NORMAL, "default"),
                       (constants.RS_NORMAL, 2),
                       (constants.RS_NORMAL, ["node1", "node2"]),
                       ],
                      [(constants.RS_NORMAL, "restricted"),
                       (constants.RS_NORMAL, 3),
                       (constants.RS_NORMAL, ["node1", "node9", "node10"]),
                       ],
                      ])

  def testInstances(self):
    groups_to_instances = {
      "c0e89160-18e7-11e0-a46e-001d0904baeb": ["inst1", "inst2"],
      "d2a40a74-18e7-11e0-9143-001d0904baeb": ["inst1", "inst10", "inst9"],
      }

    q = self._Create(["pinst_cnt", "pinst_list"])
    gqd = query.GroupQueryData(self.cluster, self.groups, None,
      groups_to_instances, False)

    self.assertEqual(q.RequestedData(), set([query.GQ_INST]))

    self.assertEqual(q.Query(gqd),
                     [[(constants.RS_NORMAL, 2),
                       (constants.RS_NORMAL, ["inst1", "inst2"]),
                       ],
                      [(constants.RS_NORMAL, 3),
                       (constants.RS_NORMAL, ["inst1", "inst9", "inst10"]),
                       ],
                      ])

  def testDiskparams(self):
    q = self._Create(["name", "uuid", "diskparams", "custom_diskparams"])
    gqd = query.GroupQueryData(self.cluster, self.groups, None, None, True)

    self.assertEqual(q.RequestedData(),
                     set([query.GQ_CONFIG, query.GQ_DISKPARAMS]))

    self.assertEqual(q.Query(gqd),
      [[(constants.RS_NORMAL, "default"),
        (constants.RS_NORMAL, "c0e89160-18e7-11e0-a46e-001d0904baeb"),
        (constants.RS_NORMAL, constants.DISK_DT_DEFAULTS),
        (constants.RS_NORMAL, {}),
        ],
       [(constants.RS_NORMAL, "restricted"),
        (constants.RS_NORMAL, "d2a40a74-18e7-11e0-9143-001d0904baeb"),
        (constants.RS_NORMAL, objects.FillDiskParams(constants.DISK_DT_DEFAULTS,
                                                     self.custom_diskparams)),
        (constants.RS_NORMAL, self.custom_diskparams),
        ],
       ])


class TestOsQuery(unittest.TestCase):
  def _Create(self, selected):
    return query.Query(query.OS_FIELDS, selected)

  def test(self):
    variants = ["v00", "plain", "v3", "var0", "v33", "v20"]
    api_versions = [10, 0, 15, 5]
    parameters = ["zpar3", "apar9"]
    os_hvps = {
      "os+variant1": {
        "kvm": {
          "acpi": False,
          "migration_downtime": 35,}
        },
      "os+variant2": {
        "xen": {
          "acpi": "noirq",
          "console": "com1",}
        },
      }
    osparameters = {
      "os+variant3": {
        "img_id": "Debian",
        "img_passwd": "1234",
        "img_format": "diskdump",
        },
      }

    assert variants != sorted(variants) and variants != utils.NiceSort(variants)
    assert (api_versions != sorted(api_versions) and
            api_versions != utils.NiceSort(variants))
    assert (parameters != sorted(parameters) and
            parameters != utils.NiceSort(parameters))

    data = [
      query.OsInfo(name="debian", valid=False, hidden=False, blacklisted=False,
                   variants=set(), api_versions=set(), parameters=set(),
                   node_status={ "some": "status", }, os_hvp={}, osparams={}),
      query.OsInfo(name="dos", valid=True, hidden=False, blacklisted=True,
                   variants=set(variants),
                   api_versions=set(api_versions),
                   parameters=set(parameters),
                   node_status={ "some": "other", "status": None, },
                   os_hvp=os_hvps, osparams=osparameters),
      ]


    q = self._Create(["name", "valid", "hidden", "blacklisted", "variants",
                      "api_versions", "parameters", "node_status", "os_hvp",
                      "osparams"])
    self.assertEqual(q.RequestedData(), set([]))
    self.assertEqual(q.Query(data),
                     [[(constants.RS_NORMAL, "debian"),
                       (constants.RS_NORMAL, False),
                       (constants.RS_NORMAL, False),
                       (constants.RS_NORMAL, False),
                       (constants.RS_NORMAL, []),
                       (constants.RS_NORMAL, []),
                       (constants.RS_NORMAL, []),
                       (constants.RS_NORMAL, {"some": "status"}),
                       (constants.RS_NORMAL, {}),
                       (constants.RS_NORMAL, {})],
                      [(constants.RS_NORMAL, "dos"),
                       (constants.RS_NORMAL, True),
                       (constants.RS_NORMAL, False),
                       (constants.RS_NORMAL, True),
                       (constants.RS_NORMAL,
                        ["plain", "v00", "v3", "v20", "v33", "var0"]),
                       (constants.RS_NORMAL, [0, 5, 10, 15]),
                       (constants.RS_NORMAL, ["apar9", "zpar3"]),
                       (constants.RS_NORMAL,
                        { "some": "other", "status": None, }),
                       (constants.RS_NORMAL, os_hvps),
                       (constants.RS_NORMAL, osparameters)
                       ]])


class TestQueryFields(unittest.TestCase):
  def testAllFields(self):
    for fielddefs in query.ALL_FIELD_LISTS:
      result = query.QueryFields(fielddefs, None)
      self.assertTrue(isinstance(result, dict))
      response = objects.QueryFieldsResponse.FromDict(result)
      self.assertEqual([(fdef.name, fdef.title) for fdef in response.fields],
        [(fdef2.name, fdef2.title)
         for (fdef2, _, _, _) in utils.NiceSort(fielddefs.values(),
                                                key=lambda x: x[0].name)])

  def testSomeFields(self):
    rnd = random.Random(5357)

    for _ in range(10):
      for fielddefs in query.ALL_FIELD_LISTS:
        if len(fielddefs) > 20:
          sample_size = rnd.randint(5, 20)
        else:
          sample_size = rnd.randint(1, max(1, len(fielddefs) - 1))
        fields = [fdef for (fdef, _, _, _)
                  in rnd.sample(list(fielddefs.values()), sample_size)]
        result = query.QueryFields(fielddefs, [fdef.name for fdef in fields])
        self.assertTrue(isinstance(result, dict))
        response = objects.QueryFieldsResponse.FromDict(result)
        self.assertEqual([(fdef.name, fdef.title) for fdef in response.fields],
                         [(fdef2.name, fdef2.title) for fdef2 in fields])


class TestQueryFilter(unittest.TestCase):
  def testRequestedNames(self):
    for (what, fielddefs) in query.ALL_FIELDS.items():
      if what == constants.QR_JOB:
        namefield = "id"
        nameval = 123
        namevalempty = 0
        genval = lambda i: i * 10
        randvals = [17361, 22015, 13193, 15215]
      else:
        nameval = "abc"
        namevalempty = ""
        genval = lambda i: "x%s" % i
        randvals = ["x17361", "x22015", "x13193", "x15215"]
        namefield = {
          constants.QR_EXPORT: "export",
          constants.QR_FILTER: "uuid",
        }.get(what, "name")

      assert namefield in fielddefs

      reqnames = [genval(i) for i in range(4)]
      innerfilter = [["=", namefield, v] for v in reqnames]

      # No name field
      q = query.Query(fielddefs, [namefield],
                      qfilter=["=", namefield, nameval], namefield=None)
      self.assertEqual(q.RequestedNames(), None)

      # No filter
      q = query.Query(fielddefs, [namefield], qfilter=None, namefield=namefield)
      self.assertEqual(q.RequestedNames(), None)

      # Check empty query
      q = query.Query(fielddefs, [namefield], qfilter=["|"],
                      namefield=namefield)
      self.assertEqual(q.RequestedNames(), None)

      # Check order
      q = query.Query(fielddefs, [namefield], qfilter=["|"] + innerfilter,
                      namefield=namefield)
      self.assertEqual(q.RequestedNames(), reqnames)

      # Check reverse order
      q = query.Query(fielddefs, [namefield],
                      qfilter=["|"] + list(reversed(innerfilter)),
                      namefield=namefield)
      self.assertEqual(q.RequestedNames(), list(reversed(reqnames)))

      # Duplicates
      q = query.Query(fielddefs, [namefield],
                      qfilter=["|"] + innerfilter + list(reversed(innerfilter)),
                      namefield=namefield)
      self.assertEqual(q.RequestedNames(), reqnames)

      # Unknown name field
      self.assertRaises(AssertionError, query.Query, fielddefs, [namefield],
                        namefield="_unknown_field_")

      # Filter with AND
      q = query.Query(fielddefs, [namefield],
                      qfilter=["|", ["=", namefield, nameval],
                                    ["&", ["=", namefield, namevalempty]]],
                      namefield=namefield)
      self.assertTrue(q.RequestedNames() is None)

      # Filter with NOT
      q = query.Query(fielddefs, [namefield],
                      qfilter=["|", ["=", namefield, nameval],
                                    ["!", ["=", namefield, namevalempty]]],
                      namefield=namefield)
      self.assertTrue(q.RequestedNames() is None)

      # Filter with only OR (names must be in correct order)
      q = query.Query(fielddefs, [namefield],
                      qfilter=["|", ["=", namefield, randvals[0]],
                                    ["|", ["=", namefield, randvals[1]]],
                                    ["|", ["|", ["=", namefield, randvals[2]]]],
                                    ["=", namefield, randvals[3]]],
                      namefield=namefield)
      self.assertEqual(q.RequestedNames(), randvals)

  @staticmethod
  def _GenNestedFilter(namefield, op, depth, nameval):
    nested = ["=", namefield, nameval]
    for i in range(depth):
      nested = [op, nested]
    return nested

  def testCompileFilter(self):
    levels_max = query._FilterCompilerHelper._LEVELS_MAX

    for (what, fielddefs) in query.ALL_FIELDS.items():
      namefield, nameval = {
        constants.QR_JOB: ("id", 123),
        constants.QR_EXPORT: ("export", "value"),
        constants.QR_FILTER: ("uuid", str(uuid_module.uuid4())),
      }.get(what, ("name", "value"))

      checks = [
        [], ["="], ["=", "foo"], ["unknownop"], ["!"],
        ["=", "_unknown_field", "value"],
        self._GenNestedFilter(namefield, "|", levels_max, nameval),
        self._GenNestedFilter(namefield, "|", levels_max * 3, nameval),
        self._GenNestedFilter(namefield, "!", levels_max, nameval),
        ]

      for qfilter in checks:
        self.assertRaises(errors.ParameterError, query._CompileFilter,
                          fielddefs, None, qfilter)

      for op in ["|", "!"]:
        qfilter = self._GenNestedFilter(namefield, op, levels_max - 1, nameval)
        self.assertTrue(callable(query._CompileFilter(fielddefs, None,
                                                      qfilter)))

  def testQueryInputOrder(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("pnode", "PNode", constants.QFT_TEXT, "Primary"),
       None, 0, lambda ctx, item: item["pnode"]),
      (query._MakeField("snode", "SNode", constants.QFT_TEXT, "Secondary"),
       None, 0, lambda ctx, item: item["snode"]),
      ], [])

    data = [
      { "pnode": "node1", "snode": "node44", },
      { "pnode": "node30", "snode": "node90", },
      { "pnode": "node25", "snode": "node1", },
      { "pnode": "node20", "snode": "node1", },
      ]

    qfilter = ["|", ["=", "pnode", "node1"], ["=", "snode", "node1"]]

    q = query.Query(fielddefs, ["pnode", "snode"], namefield="pnode",
                    qfilter=qfilter)
    self.assertTrue(q.RequestedNames() is None)
    self.assertFalse(q.RequestedData())
    self.assertEqual(q.Query(data),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "node44")],
       [(constants.RS_NORMAL, "node20"), (constants.RS_NORMAL, "node1")],
       [(constants.RS_NORMAL, "node25"), (constants.RS_NORMAL, "node1")]])

    # Try again with reversed input data
    self.assertEqual(q.Query(reversed(data)),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "node44")],
       [(constants.RS_NORMAL, "node20"), (constants.RS_NORMAL, "node1")],
       [(constants.RS_NORMAL, "node25"), (constants.RS_NORMAL, "node1")]])

    # No name field, result must be in incoming order
    q = query.Query(fielddefs, ["pnode", "snode"], namefield=None,
                    qfilter=qfilter)
    self.assertFalse(q.RequestedData())
    self.assertEqual(q.Query(data),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "node44")],
       [(constants.RS_NORMAL, "node25"), (constants.RS_NORMAL, "node1")],
       [(constants.RS_NORMAL, "node20"), (constants.RS_NORMAL, "node1")]])
    self.assertEqual(q.OldStyleQuery(data), [
      ["node1", "node44"],
      ["node25", "node1"],
      ["node20", "node1"],
      ])
    self.assertEqual(q.Query(reversed(data)),
      [[(constants.RS_NORMAL, "node20"), (constants.RS_NORMAL, "node1")],
       [(constants.RS_NORMAL, "node25"), (constants.RS_NORMAL, "node1")],
       [(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "node44")]])
    self.assertEqual(q.OldStyleQuery(reversed(data)), [
      ["node20", "node1"],
      ["node25", "node1"],
      ["node1", "node44"],
      ])

    # Name field, but no sorting, result must be in incoming order
    q = query.Query(fielddefs, ["pnode", "snode"], namefield="pnode")
    self.assertFalse(q.RequestedData())
    self.assertEqual(q.Query(data, sort_by_name=False),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "node44")],
       [(constants.RS_NORMAL, "node30"), (constants.RS_NORMAL, "node90")],
       [(constants.RS_NORMAL, "node25"), (constants.RS_NORMAL, "node1")],
       [(constants.RS_NORMAL, "node20"), (constants.RS_NORMAL, "node1")]])
    self.assertEqual(q.OldStyleQuery(data, sort_by_name=False), [
      ["node1", "node44"],
      ["node30", "node90"],
      ["node25", "node1"],
      ["node20", "node1"],
      ])
    self.assertEqual(q.Query(reversed(data), sort_by_name=False),
      [[(constants.RS_NORMAL, "node20"), (constants.RS_NORMAL, "node1")],
       [(constants.RS_NORMAL, "node25"), (constants.RS_NORMAL, "node1")],
       [(constants.RS_NORMAL, "node30"), (constants.RS_NORMAL, "node90")],
       [(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "node44")]])
    self.assertEqual(q.OldStyleQuery(reversed(data), sort_by_name=False), [
      ["node20", "node1"],
      ["node25", "node1"],
      ["node30", "node90"],
      ["node1", "node44"],
      ])

  def testEqualNamesOrder(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("pnode", "PNode", constants.QFT_TEXT, "Primary"),
       None, 0, lambda ctx, item: item["pnode"]),
      (query._MakeField("num", "Num", constants.QFT_NUMBER, "Num"),
       None, 0, lambda ctx, item: item["num"]),
      ], [])

    data = [
      { "pnode": "node1", "num": 100, },
      { "pnode": "node1", "num": 25, },
      { "pnode": "node2", "num": 90, },
      { "pnode": "node2", "num": 30, },
      ]

    q = query.Query(fielddefs, ["pnode", "num"], namefield="pnode",
                    qfilter=["|", ["=", "pnode", "node1"],
                                  ["=", "pnode", "node2"],
                                  ["=", "pnode", "node1"]])
    self.assertEqual(q.RequestedNames(), ["node1", "node2"],
                     msg="Did not return unique names")
    self.assertFalse(q.RequestedData())
    self.assertEqual(q.Query(data),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, 100)],
       [(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, 25)],
       [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, 90)],
       [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, 30)]])
    self.assertEqual(q.Query(data, sort_by_name=False),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, 100)],
       [(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, 25)],
       [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, 90)],
       [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, 30)]])

    data = [
      { "pnode": "nodeX", "num": 50, },
      { "pnode": "nodeY", "num": 40, },
      { "pnode": "nodeX", "num": 30, },
      { "pnode": "nodeX", "num": 20, },
      { "pnode": "nodeM", "num": 10, },
      ]

    q = query.Query(fielddefs, ["pnode", "num"], namefield="pnode",
                    qfilter=["|", ["=", "pnode", "nodeX"],
                                  ["=", "pnode", "nodeY"],
                                  ["=", "pnode", "nodeY"],
                                  ["=", "pnode", "nodeY"],
                                  ["=", "pnode", "nodeM"]])
    self.assertEqual(q.RequestedNames(), ["nodeX", "nodeY", "nodeM"],
                     msg="Did not return unique names")
    self.assertFalse(q.RequestedData())

    # First sorted by name, then input order
    self.assertEqual(q.Query(data, sort_by_name=True),
      [[(constants.RS_NORMAL, "nodeM"), (constants.RS_NORMAL, 10)],
       [(constants.RS_NORMAL, "nodeX"), (constants.RS_NORMAL, 50)],
       [(constants.RS_NORMAL, "nodeX"), (constants.RS_NORMAL, 30)],
       [(constants.RS_NORMAL, "nodeX"), (constants.RS_NORMAL, 20)],
       [(constants.RS_NORMAL, "nodeY"), (constants.RS_NORMAL, 40)]])

    # Input order
    self.assertEqual(q.Query(data, sort_by_name=False),
      [[(constants.RS_NORMAL, "nodeX"), (constants.RS_NORMAL, 50)],
       [(constants.RS_NORMAL, "nodeY"), (constants.RS_NORMAL, 40)],
       [(constants.RS_NORMAL, "nodeX"), (constants.RS_NORMAL, 30)],
       [(constants.RS_NORMAL, "nodeX"), (constants.RS_NORMAL, 20)],
       [(constants.RS_NORMAL, "nodeM"), (constants.RS_NORMAL, 10)]])

  def testFilter(self):
    (DK_A, DK_B) = range(1000, 1002)

    fielddefs = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       DK_A, 0, lambda ctx, item: item["name"]),
      (query._MakeField("other", "Other", constants.QFT_TEXT, "Other"),
       DK_B, 0, lambda ctx, item: item["other"]),
      ], [])

    data = [
      { "name": "node1", "other": "foo", },
      { "name": "node2", "other": "bar", },
      { "name": "node3", "other": "Hello", },
      ]

    # Empty filter
    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=["|"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.RequestedData(), set([DK_A, DK_B]))
    self.assertEqual(q.Query(data), [])

    # Normal filter
    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=["=", "name", "node1"])
    self.assertEqual(q.RequestedNames(), ["node1"])
    self.assertEqual(q.Query(data),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "foo")]])

    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=(["|", ["=", "name", "node1"],
                                   ["=", "name", "node3"]]))
    self.assertEqual(q.RequestedNames(), ["node1", "node3"])
    self.assertEqual(q.Query(data),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "foo")],
       [(constants.RS_NORMAL, "node3"), (constants.RS_NORMAL, "Hello")]])

    # Complex filter
    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=(["|", ["=", "name", "node1"],
                                   ["|", ["=", "name", "node3"],
                                         ["=", "name", "node2"]],
                                   ["=", "name", "node3"]]))
    self.assertEqual(q.RequestedNames(), ["node1", "node3", "node2"])
    self.assertEqual(q.RequestedData(), set([DK_A, DK_B]))
    self.assertEqual(q.Query(data),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "foo")],
       [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, "bar")],
       [(constants.RS_NORMAL, "node3"), (constants.RS_NORMAL, "Hello")]])

    # Filter data type mismatch
    for i in [-1, 0, 1, 123, [], None, True, False]:
      self.assertRaises(errors.ParameterError, query.Query,
                        fielddefs, ["name", "other"], namefield="name",
                        qfilter=["=", "name", i])

    # Negative filter
    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=["!", ["|", ["=", "name", "node1"],
                                        ["=", "name", "node3"]]])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data),
      [[(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, "bar")]])

    # Not equal
    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=["!=", "name", "node3"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data),
      [[(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, "foo")],
       [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, "bar")]])

    # Data type
    q = query.Query(fielddefs, [], namefield="name",
                    qfilter=["|", ["=", "other", "bar"],
                                  ["=", "name", "foo"]])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.RequestedData(), set([DK_A, DK_B]))
    self.assertEqual(q.Query(data), [[]])

    # Only one data type
    q = query.Query(fielddefs, ["other"], namefield="name",
                    qfilter=["=", "other", "bar"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.RequestedData(), set([DK_B]))
    self.assertEqual(q.Query(data), [[(constants.RS_NORMAL, "bar")]])

    q = query.Query(fielddefs, [], namefield="name",
                    qfilter=["=", "other", "bar"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.RequestedData(), set([DK_B]))
    self.assertEqual(q.Query(data), [[]])

    # Data type in boolean operator
    q = query.Query(fielddefs, [], namefield="name",
                    qfilter=["?", "name"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.RequestedData(), set([DK_A]))
    self.assertEqual(q.Query(data), [[], [], []])

    q = query.Query(fielddefs, [], namefield="name",
                    qfilter=["!", ["?", "name"]])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.RequestedData(), set([DK_A]))
    self.assertEqual(q.Query(data), [])

  def testFilterContains(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       None, 0, lambda ctx, item: item["name"]),
      (query._MakeField("other", "Other", constants.QFT_OTHER, "Other"),
       None, 0, lambda ctx, item: item["other"]),
      ], [])

    data = [
      { "name": "node2", "other": ["x", "y", "bar"], },
      { "name": "node3", "other": "Hello", },
      { "name": "node1", "other": ["a", "b", "foo"], },
      { "name": "empty", "other": []},
      ]

    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=["=[]", "other", "bar"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node2"),
       (constants.RS_NORMAL, ["x", "y", "bar"])],
      ])

    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=["|", ["=[]", "other", "bar"],
                                  ["=[]", "other", "a"],
                                  ["=[]", "other", "b"]])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1"),
       (constants.RS_NORMAL, ["a", "b", "foo"])],
      [(constants.RS_NORMAL, "node2"),
       (constants.RS_NORMAL, ["x", "y", "bar"])],
      ])
    self.assertEqual(q.OldStyleQuery(data), [
      ["node1", ["a", "b", "foo"]],
      ["node2", ["x", "y", "bar"]],
      ])

    # Boolean test
    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=["?", "other"])
    self.assertEqual(q.OldStyleQuery(data), [
      ["node1", ["a", "b", "foo"]],
      ["node2", ["x", "y", "bar"]],
      ["node3", "Hello"],
      ])

    q = query.Query(fielddefs, ["name", "other"], namefield="name",
                    qfilter=["!", ["?", "other"]])
    self.assertEqual(q.OldStyleQuery(data), [
      ["empty", []],
      ])

  def testFilterHostname(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       None, query.QFF_HOSTNAME, lambda ctx, item: item["name"]),
      ], [])

    data = [
      { "name": "node1.example.com", },
      { "name": "node2.example.com", },
      { "name": "node2.example.net", },
      ]

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["=", "name", "node2"])
    self.assertEqual(q.RequestedNames(), ["node2"])
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node2.example.com")],
      [(constants.RS_NORMAL, "node2.example.net")],
      ])

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["=", "name", "node1"])
    self.assertEqual(q.RequestedNames(), ["node1"])
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1.example.com")],
      ])

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["=", "name", "othername"])
    self.assertEqual(q.RequestedNames(), ["othername"])
    self.assertEqual(q.Query(data), [])

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["|", ["=", "name", "node1.example.com"],
                                  ["=", "name", "node2"]])
    self.assertEqual(q.RequestedNames(), ["node1.example.com", "node2"])
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1.example.com")],
      [(constants.RS_NORMAL, "node2.example.com")],
      [(constants.RS_NORMAL, "node2.example.net")],
      ])
    self.assertEqual(q.OldStyleQuery(data), [
      ["node1.example.com"],
      ["node2.example.com"],
      ["node2.example.net"],
      ])

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["!=", "name", "node1"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node2.example.com")],
      [(constants.RS_NORMAL, "node2.example.net")],
      ])
    self.assertEqual(q.OldStyleQuery(data), [
      ["node2.example.com"],
      ["node2.example.net"],
      ])

  def testFilterBoolean(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       None, query.QFF_HOSTNAME, lambda ctx, item: item["name"]),
      (query._MakeField("value", "Value", constants.QFT_BOOL, "Value"),
       None, 0, lambda ctx, item: item["value"]),
      ], [])

    data = [
      { "name": "node1", "value": False, },
      { "name": "node2", "value": True, },
      { "name": "node3", "value": True, },
      ]

    q = query.Query(fielddefs, ["name", "value"],
                    qfilter=["|", ["=", "value", False],
                                  ["=", "value", True]])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, False)],
      [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, True)],
      [(constants.RS_NORMAL, "node3"), (constants.RS_NORMAL, True)],
      ])

    q = query.Query(fielddefs, ["name", "value"],
                    qfilter=["|", ["=", "value", False],
                                  ["!", ["=", "value", False]]])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, False)],
      [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, True)],
      [(constants.RS_NORMAL, "node3"), (constants.RS_NORMAL, True)],
      ])

    # Comparing bool with string
    for i in ["False", "True", "0", "1", "no", "yes", "N", "Y"]:
      self.assertRaises(errors.ParameterError, query.Query,
                        fielddefs, ["name", "value"],
                        qfilter=["=", "value", i])

    # Truth filter
    q = query.Query(fielddefs, ["name", "value"], qfilter=["?", "value"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, True)],
      [(constants.RS_NORMAL, "node3"), (constants.RS_NORMAL, True)],
      ])

    # Negative bool filter
    q = query.Query(fielddefs, ["name", "value"], qfilter=["!", ["?", "value"]])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, False)],
      ])

    # Complex truth filter
    q = query.Query(fielddefs, ["name", "value"],
                    qfilter=["|", ["&", ["=", "name", "node1"],
                                        ["!", ["?", "value"]]],
                                  ["?", "value"]])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1"), (constants.RS_NORMAL, False)],
      [(constants.RS_NORMAL, "node2"), (constants.RS_NORMAL, True)],
      [(constants.RS_NORMAL, "node3"), (constants.RS_NORMAL, True)],
      ])

  def testFilterRegex(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT, "Name"),
       None, 0, lambda ctx, item: item["name"]),
      ], [])

    data = [
      { "name": "node1.example.com", },
      { "name": "node2.site.example.com", },
      { "name": "node2.example.net", },

      # Empty name
      { "name": "", },
      ]

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["=~", "name", "site"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node2.site.example.com")],
      ])

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["=~", "name", "^node2"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node2.example.net")],
      [(constants.RS_NORMAL, "node2.site.example.com")],
      ])

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["=~", "name", r"(?i)\.COM$"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1.example.com")],
      [(constants.RS_NORMAL, "node2.site.example.com")],
      ])

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["=~", "name", r"."])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "node1.example.com")],
      [(constants.RS_NORMAL, "node2.example.net")],
      [(constants.RS_NORMAL, "node2.site.example.com")],
      ])

    q = query.Query(fielddefs, ["name"], namefield="name",
                    qfilter=["=~", "name", r"^$"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "")],
      ])

    # Invalid regular expression
    self.assertRaises(errors.ParameterError, query.Query, fielddefs, ["name"],
                      qfilter=["=~", "name", r"["])

  def testFilterLessGreater(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("value", "Value", constants.QFT_NUMBER, "Value"),
       None, 0, lambda ctx, item: item),
      ], [])

    data = range(100)

    q = query.Query(fielddefs, ["value"],
                    qfilter=["<", "value", 20])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data),
                     [[(constants.RS_NORMAL, i)] for i in range(20)])

    q = query.Query(fielddefs, ["value"],
                    qfilter=["<=", "value", 30])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data),
                     [[(constants.RS_NORMAL, i)] for i in range(31)])

    q = query.Query(fielddefs, ["value"],
                    qfilter=[">", "value", 40])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data),
                     [[(constants.RS_NORMAL, i)] for i in range(41, 100)])

    q = query.Query(fielddefs, ["value"],
                    qfilter=[">=", "value", 50])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data),
                     [[(constants.RS_NORMAL, i)] for i in range(50, 100)])

  def testFilterLessGreaterJobId(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("id", "ID", constants.QFT_TEXT, "Job ID"),
       None, query.QFF_JOB_ID, lambda ctx, item: item),
      ], [])

    data = ["1", "2", "3", "10", "102", "120", "125", "15", "100", "7"]

    assert data != utils.NiceSort(data), "Test data should not be sorted"

    q = query.Query(fielddefs, ["id"], qfilter=["<", "id", "20"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "1")],
      [(constants.RS_NORMAL, "2")],
      [(constants.RS_NORMAL, "3")],
      [(constants.RS_NORMAL, "10")],
      [(constants.RS_NORMAL, "15")],
      [(constants.RS_NORMAL, "7")],
      ])

    q = query.Query(fielddefs, ["id"], qfilter=[">=", "id", "100"])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, "102")],
      [(constants.RS_NORMAL, "120")],
      [(constants.RS_NORMAL, "125")],
      [(constants.RS_NORMAL, "100")],
      ])

    # Integers are no valid job IDs
    self.assertRaises(errors.ParameterError, query.Query,
                      fielddefs, ["id"], qfilter=[">=", "id", 10])

  def testFilterLessGreaterSplitTimestamp(self):
    fielddefs = query._PrepareFieldList([
      (query._MakeField("ts", "Timestamp", constants.QFT_OTHER, "Timestamp"),
       None, query.QFF_SPLIT_TIMESTAMP, lambda ctx, item: item),
      ], [])

    data = [
      utils.SplitTime(0),
      utils.SplitTime(0.1),
      utils.SplitTime(18224.7872),
      utils.SplitTime(919896.12623),
      utils.SplitTime(999),
      utils.SplitTime(989.9999),
      ]

    for i in [0, [0, 0]]:
      q = query.Query(fielddefs, ["ts"], qfilter=["<", "ts", i])
      self.assertTrue(q.RequestedNames() is None)
      self.assertEqual(q.Query(data), [])

    q = query.Query(fielddefs, ["ts"], qfilter=["<", "ts", 1000])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, (0, 0))],
      [(constants.RS_NORMAL, (0, 100000))],
      [(constants.RS_NORMAL, (999, 0))],
      [(constants.RS_NORMAL, (989, 999900))],
      ])

    q = query.Query(fielddefs, ["ts"], qfilter=[">=", "ts", 5000.3])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, (18224, 787200))],
      [(constants.RS_NORMAL, (919896, 126230))],
      ])

    for i in [18224.7772, utils.SplitTime(18224.7772)]:
      q = query.Query(fielddefs, ["ts"], qfilter=[">=", "ts", i])
      self.assertTrue(q.RequestedNames() is None)
      self.assertEqual(q.Query(data), [
        [(constants.RS_NORMAL, (18224, 787200))],
        [(constants.RS_NORMAL, (919896, 126230))],
        ])

    q = query.Query(fielddefs, ["ts"], qfilter=[">", "ts", 18224.7880])
    self.assertTrue(q.RequestedNames() is None)
    self.assertEqual(q.Query(data), [
      [(constants.RS_NORMAL, (919896, 126230))],
      ])


if __name__ == "__main__":
  testutils.GanetiTestProgram()

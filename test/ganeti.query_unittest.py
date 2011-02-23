#!/usr/bin/python
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Script for testing ganeti.query"""

import re
import unittest
import random

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors
from ganeti import query
from ganeti import objects
from ganeti import cmdlib

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
      (query._MakeField("name", "Name", constants.QFT_TEXT),
       STATIC, lambda ctx, item: item["name"]),
      (query._MakeField("master", "Master", constants.QFT_BOOL),
       STATIC, lambda ctx, item: ctx.mastername == item["name"]),
      ] +
      [(query._MakeField("disk%s.size" % i, "DiskSize%s" % i,
                         constants.QFT_UNIT),
        DISK, compat.partial(_GetDiskSize, i))
       for i in range(4)], [])

    q = query.Query(fielddef, ["name"])
    self.assertEqual(q.RequestedData(), set([STATIC]))
    self.assertEqual(len(q._fields), 1)
    self.assertEqual(len(q.GetFields()), 1)
    self.assertEqual(q.GetFields()[0].ToDict(),
      objects.QueryFieldDefinition(name="name",
                                   title="Name",
                                   kind=constants.QFT_TEXT).ToDict())

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
                       "kind": constants.QFT_UNIT, },
                     { "name": "disk1.size", "title": "DiskSize1",
                       "kind": constants.QFT_UNIT, },
                     { "name": "disk99.size", "title": "disk99.size",
                       "kind": constants.QFT_UNKNOWN, },
                     { "name": "disk0.size", "title": "DiskSize0",
                       "kind": constants.QFT_UNIT, },
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
        (query._MakeField("name", b, constants.QFT_TEXT), None,
         lambda *args: None),
        (query._MakeField("other", a, constants.QFT_TEXT), None,
         lambda *args: None),
        ], [])

    # Non-lowercase names
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("NAME", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ], [])
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("Name", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ], [])

    # Empty name
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ], [])

    # Empty title
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "", constants.QFT_TEXT), None,
       lambda *args: None),
      ], [])

    # Whitespace in title
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "Co lu mn", constants.QFT_TEXT), None,
       lambda *args: None),
      ], [])

    # No callable function
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "Name", constants.QFT_TEXT), None, None),
      ], [])

  def testUnknown(self):
    fielddef = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT),
       None, lambda _, item: "name%s" % item),
      (query._MakeField("other0", "Other0", constants.QFT_TIMESTAMP),
       None, lambda *args: 1234),
      (query._MakeField("nodata", "NoData", constants.QFT_NUMBER),
       None, lambda *args: query._FS_NODATA ),
      (query._MakeField("unavail", "Unavail", constants.QFT_BOOL),
       None, lambda *args: query._FS_UNAVAIL),
      ], [])

    for selected in [["foo"], ["Hello", "World"],
                     ["name1", "other", "foo"]]:
      q = query.Query(fielddef, selected)
      self.assertEqual(len(q._fields), len(selected))
      self.assert_(compat.all(len(row) == len(selected)
                              for row in q.Query(_QueryData(range(1, 10)))))
      self.assertEqual(q.Query(_QueryData(range(1, 10))),
                       [[(constants.RS_UNKNOWN, None)] * len(selected)
                        for i in range(1, 10)])
      self.assertEqual([fdef.ToDict() for fdef in q.GetFields()],
                       [{ "name": name, "title": name,
                          "kind": constants.QFT_UNKNOWN, }
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
      (query._MakeField("a", "a-title", constants.QFT_TEXT), None,
       lambda *args: None),
      (query._MakeField("b", "b-title", constants.QFT_TEXT), None,
       lambda *args: None),
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

    checks = [
      (constants.NR_MASTER, "node1", objects.Node(name="node1")),
      (constants.NR_MCANDIDATE, "master",
       objects.Node(name="node1", master_candidate=True)),
      (constants.NR_REGULAR, "master", objects.Node(name="node1")),
      (constants.NR_DRAINED, "master",
       objects.Node(name="node1", drained=True)),
      (constants.NR_OFFLINE,
       "master", objects.Node(name="node1", offline=True)),
      ]

    for (role, master_name, node) in checks:
      result = query._GetNodeRole(node, master_name)
      self.assertEqual(result, role)
      tested_role.add(result)

    self.assertEqual(tested_role, constants.NR_ALL)


class TestNodeQuery(unittest.TestCase):
  def _Create(self, selected):
    return query.Query(query.NODE_FIELDS, selected)

  def testSimple(self):
    nodes = [
      objects.Node(name="node1", drained=False),
      objects.Node(name="node2", drained=True),
      objects.Node(name="node3", drained=False),
      ]
    for live_data in [None, dict.fromkeys([node.name for node in nodes], {})]:
      nqd = query.NodeQueryData(nodes, live_data, None, None, None, None, None,
                                None)

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

  def test(self):
    selected = query.NODE_FIELDS.keys()
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

    live_data_name = node_names[4]
    assert live_data_name != master_name

    fake_live_data = {
      "bootid": "a2504766-498e-4b25-b21e-d23098dc3af4",
      "cnodes": 4,
      "csockets": 4,
      "ctotal": 8,
      "mnode": 128,
      "mfree": 100,
      "mtotal": 4096,
      "dfree": 5 * 1024 * 1024,
      "dtotal": 100 * 1024 * 1024,
      }

    assert (sorted(query._NODE_LIVE_FIELDS.keys()) ==
            sorted(fake_live_data.keys()))

    live_data = dict.fromkeys(node_names, {})
    live_data[live_data_name] = \
      dict((query._NODE_LIVE_FIELDS[name][2], value)
           for name, value in fake_live_data.items())

    node_to_primary = dict((name, set()) for name in node_names)
    node_to_primary[master_name].update(["inst1", "inst2"])

    node_to_secondary = dict((name, set()) for name in node_names)
    node_to_secondary[live_data_name].update(["instX", "instY", "instZ"])

    ng_uuid = "492b4b74-8670-478a-b98d-4c53a76238e6"
    groups = {
      ng_uuid: objects.NodeGroup(name="ng1", uuid=ng_uuid, ndparams={}),
      }

    oob_support = dict((name, False) for name in node_names)

    master_node.group = ng_uuid

    nqd = query.NodeQueryData(nodes, live_data, master_name,
                              node_to_primary, node_to_secondary, groups,
                              oob_support, cluster)
    result = q.Query(nqd)
    self.assert_(compat.all(len(row) == len(selected) for row in result))
    self.assertEqual([row[field_index["name"]] for row in result],
                     [(constants.RS_NORMAL, name) for name in node_names])

    node_to_row = dict((row[field_index["name"]][1], idx)
                       for idx, row in enumerate(result))

    master_row = result[node_to_row[master_name]]
    self.assert_(master_row[field_index["master"]])
    self.assert_(master_row[field_index["role"]], "M")
    self.assertEqual(master_row[field_index["group"]],
                     (constants.RS_NORMAL, "ng1"))
    self.assertEqual(master_row[field_index["group.uuid"]],
                     (constants.RS_NORMAL, ng_uuid))
    self.assertEqual(master_row[field_index["ctime"]],
                     (constants.RS_UNAVAIL, None))
    self.assertEqual(master_row[field_index["mtime"]],
                     (constants.RS_UNAVAIL, None))

    self.assert_(row[field_index["pip"]] == node.primary_ip and
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
                                                 node.mtime)))
                 for row, node in zip(result, nodes))

    live_data_row = result[node_to_row[live_data_name]]

    for (field, value) in fake_live_data.items():
      self.assertEqual(live_data_row[field_index[field]],
                       (constants.RS_NORMAL, value))

    self.assertEqual(master_row[field_index["pinst_cnt"]],
                     (constants.RS_NORMAL, 2))
    self.assertEqual(live_data_row[field_index["sinst_cnt"]],
                     (constants.RS_NORMAL, 3))
    self.assertEqual(master_row[field_index["pinst_list"]],
                     (constants.RS_NORMAL,
                      list(node_to_primary[master_name])))
    self.assertEqual(live_data_row[field_index["sinst_list"]],
                     (constants.RS_NORMAL,
                      list(node_to_secondary[live_data_name])))

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
    nqd = query.NodeQueryData(None, None, None, None, None, None, None, None)
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
    q = self._Create(["name", "be/memory", "ip"])
    self.assertEqual(q.RequestedData(), set([query.IQ_CONFIG]))

    cluster = objects.Cluster(cluster_name="testcluster",
      hvparams=constants.HVC_DEFAULTS,
      beparams={
        constants.PP_DEFAULT: constants.BEC_DEFAULTS,
        },
      nicparams={
        constants.PP_DEFAULT: constants.NICC_DEFAULTS,
        })

    instances = [
      objects.Instance(name="inst1", hvparams={}, beparams={}, nics=[]),
      objects.Instance(name="inst2", hvparams={}, nics=[],
        beparams={
          constants.BE_MEMORY: 512,
        }),
      objects.Instance(name="inst3", hvparams={}, beparams={},
        nics=[objects.NIC(ip="192.0.2.99", nicparams={})]),
      ]

    iqd = query.InstanceQueryData(instances, cluster, None, [], [], {},
                                  set(), {})
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
    selected = query.INSTANCE_FIELDS.keys()
    fieldidx = dict((field, idx) for idx, field in enumerate(selected))

    macs = ["00:11:22:%02x:%02x:%02x" % (i % 255, i % 3, (i * 123) % 255)
            for i in range(20)]

    q = self._Create(selected)
    self.assertEqual(q.RequestedData(),
                     set([query.IQ_CONFIG, query.IQ_LIVE, query.IQ_DISKUSAGE,
                          query.IQ_CONSOLE]))

    cluster = objects.Cluster(cluster_name="testcluster",
      hvparams=constants.HVC_DEFAULTS,
      beparams={
        constants.PP_DEFAULT: constants.BEC_DEFAULTS,
        },
      nicparams={
        constants.PP_DEFAULT: constants.NICC_DEFAULTS,
        },
      os_hvp={},
      tcpudp_port_pool=set())

    offline_nodes = ["nodeoff1", "nodeoff2"]
    bad_nodes = ["nodebad1", "nodebad2", "nodebad3"] + offline_nodes
    nodes = ["node%s" % i for i in range(10)] + bad_nodes

    instances = [
      objects.Instance(name="inst1", hvparams={}, beparams={}, nics=[],
        uuid="f90eccb3-e227-4e3c-bf2a-94a21ca8f9cd",
        ctime=1291244000, mtime=1291244400, serial_no=30,
        admin_up=True, hypervisor=constants.HT_XEN_PVM, os="linux1",
        primary_node="node1",
        disk_template=constants.DT_PLAIN,
        disks=[]),
      objects.Instance(name="inst2", hvparams={}, nics=[],
        uuid="73a0f8a7-068c-4630-ada2-c3440015ab1a",
        ctime=1291211000, mtime=1291211077, serial_no=1,
        admin_up=True, hypervisor=constants.HT_XEN_HVM, os="deb99",
        primary_node="node5",
        disk_template=constants.DT_DISKLESS,
        disks=[],
        beparams={
          constants.BE_MEMORY: 512,
        }),
      objects.Instance(name="inst3", hvparams={}, beparams={},
        uuid="11ec8dff-fb61-4850-bfe0-baa1803ff280",
        ctime=1291011000, mtime=1291013000, serial_no=1923,
        admin_up=False, hypervisor=constants.HT_KVM, os="busybox",
        primary_node="node6",
        disk_template=constants.DT_DRBD8,
        disks=[],
        nics=[
          objects.NIC(ip="192.0.2.99", mac=macs.pop(),
                      nicparams={
                        constants.NIC_LINK: constants.DEFAULT_BRIDGE,
                        }),
          objects.NIC(ip=None, mac=macs.pop(), nicparams={}),
          ]),
      objects.Instance(name="inst4", hvparams={}, beparams={},
        uuid="68dab168-3ef5-4c9d-b4d3-801e0672068c",
        ctime=1291244390, mtime=1291244395, serial_no=25,
        admin_up=False, hypervisor=constants.HT_XEN_PVM, os="linux1",
        primary_node="nodeoff2",
        disk_template=constants.DT_DRBD8,
        disks=[],
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
          ]),
      objects.Instance(name="inst5", hvparams={}, nics=[],
        uuid="0e3dca12-5b42-4e24-98a2-415267545bd0",
        ctime=1231211000, mtime=1261200000, serial_no=3,
        admin_up=True, hypervisor=constants.HT_XEN_HVM, os="deb99",
        primary_node="nodebad2",
        disk_template=constants.DT_DISKLESS,
        disks=[],
        beparams={
          constants.BE_MEMORY: 512,
        }),
      objects.Instance(name="inst6", hvparams={}, nics=[],
        uuid="72de6580-c8d5-4661-b902-38b5785bb8b3",
        ctime=7513, mtime=11501, serial_no=13390,
        admin_up=False, hypervisor=constants.HT_XEN_HVM, os="deb99",
        primary_node="node7",
        disk_template=constants.DT_DISKLESS,
        disks=[],
        beparams={
          constants.BE_MEMORY: 768,
        }),
      objects.Instance(name="inst7", hvparams={}, nics=[],
        uuid="ceec5dc4-b729-4f42-ae28-69b3cd24920e",
        ctime=None, mtime=None, serial_no=1947,
        admin_up=False, hypervisor=constants.HT_XEN_HVM, os="deb99",
        primary_node="node6",
        disk_template=constants.DT_DISKLESS,
        disks=[],
        beparams={}),
      ]

    assert not utils.FindDuplicates(inst.name for inst in instances)

    instbyname = dict((inst.name, inst) for inst in instances)

    disk_usage = dict((inst.name,
                       cmdlib._ComputeDiskSize(inst.disk_template,
                                               [{"size": disk.size}
                                                for disk in inst.disks]))
                      for inst in instances)

    inst_bridges = {
      "inst3": [constants.DEFAULT_BRIDGE, constants.DEFAULT_BRIDGE],
      "inst4": [constants.DEFAULT_BRIDGE, constants.DEFAULT_BRIDGE,
                None, "eth123"],
      }

    live_data = {
      "inst2": {
        "vcpus": 3,
        },
      "inst4": {
        "memory": 123,
        },
      "inst6": {
        "memory": 768,
        },
      "inst7": {
        "vcpus": 3,
        },
      }
    wrongnode_inst = set(["inst7"])

    consinfo = dict((inst.name, None) for inst in instances)
    consinfo["inst7"] = \
      objects.InstanceConsole(instance="inst7", kind=constants.CONS_SSH,
                              host=instbyname["inst7"].primary_node,
                              user=constants.GANETI_RUNAS,
                              command=["hostname"]).ToDict()

    iqd = query.InstanceQueryData(instances, cluster, disk_usage,
                                  offline_nodes, bad_nodes, live_data,
                                  wrongnode_inst, consinfo)
    result = q.Query(iqd)
    self.assertEqual(len(result), len(instances))
    self.assert_(compat.all(len(row) == len(selected)
                            for row in result))

    assert len(set(bad_nodes) & set(offline_nodes)) == len(offline_nodes), \
           "Offline nodes not included in bad nodes"

    tested_status = set()

    for (inst, row) in zip(instances, result):
      assert inst.primary_node in nodes

      self.assertEqual(row[fieldidx["name"]],
                       (constants.RS_NORMAL, inst.name))

      if inst.primary_node in offline_nodes:
        exp_status = constants.INSTST_NODEOFFLINE
      elif inst.primary_node in bad_nodes:
        exp_status = constants.INSTST_NODEDOWN
      elif inst.name in live_data:
        if inst.name in wrongnode_inst:
          exp_status = constants.INSTST_WRONGNODE
        elif inst.admin_up:
          exp_status = constants.INSTST_RUNNING
        else:
          exp_status = constants.INSTST_ERRORUP
      elif inst.admin_up:
        exp_status = constants.INSTST_ERRORDOWN
      else:
        exp_status = constants.INSTST_ADMINDOWN

      self.assertEqual(row[fieldidx["status"]],
                       (constants.RS_NORMAL, exp_status))

      (_, status) = row[fieldidx["status"]]
      tested_status.add(status)

      for (field, livefield) in [("oper_ram", "memory"),
                                 ("oper_vcpus", "vcpus")]:
        if inst.primary_node in bad_nodes:
          exp = (constants.RS_NODATA, None)
        elif inst.name in live_data:
          value = live_data[inst.name].get(livefield, None)
          if value is None:
            exp = (constants.RS_UNAVAIL, None)
          else:
            exp = (constants.RS_NORMAL, value)
        else:
          exp = (constants.RS_UNAVAIL, None)

        self.assertEqual(row[fieldidx[field]], exp)

      bridges = inst_bridges.get(inst.name, [])
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
        exp = (constants.RS_NORMAL, inst.name in live_data)
      self.assertEqual(row[fieldidx["oper_state"]], exp)

      usage = disk_usage[inst.name]
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
    self.assertEqual(tested_status, constants.INSTST_ALL)

  def _CheckInstanceConsole(self, instance, (status, consdata)):
    if instance.name == "inst7":
      self.assertEqual(status, constants.RS_NORMAL)
      console = objects.InstanceConsole.FromDict(consdata)
      self.assertTrue(console.Validate())
      self.assertEqual(console.host, instance.primary_node)
    else:
      self.assertEqual(status, constants.RS_UNAVAIL)


class TestGroupQuery(unittest.TestCase):

  def setUp(self):
    self.groups = [
      objects.NodeGroup(name="default",
                        uuid="c0e89160-18e7-11e0-a46e-001d0904baeb",
                        alloc_policy=constants.ALLOC_POLICY_PREFERRED),
      objects.NodeGroup(name="restricted",
                        uuid="d2a40a74-18e7-11e0-9143-001d0904baeb",
                        alloc_policy=constants.ALLOC_POLICY_LAST_RESORT),
      ]

  def _Create(self, selected):
    return query.Query(query.GROUP_FIELDS, selected)

  def testSimple(self):
    q = self._Create(["name", "uuid", "alloc_policy"])
    gqd = query.GroupQueryData(self.groups, None, None)

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
    gqd = query.GroupQueryData(self.groups, groups_to_nodes, None)

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
    gqd = query.GroupQueryData(self.groups, None, groups_to_instances)

    self.assertEqual(q.RequestedData(), set([query.GQ_INST]))

    self.assertEqual(q.Query(gqd),
                     [[(constants.RS_NORMAL, 2),
                       (constants.RS_NORMAL, ["inst1", "inst2"]),
                       ],
                      [(constants.RS_NORMAL, 3),
                       (constants.RS_NORMAL, ["inst1", "inst9", "inst10"]),
                       ],
                      ])


class TestQueryFields(unittest.TestCase):
  def testAllFields(self):
    for fielddefs in query.ALL_FIELD_LISTS:
      result = query.QueryFields(fielddefs, None)
      self.assert_(isinstance(result, dict))
      response = objects.QueryFieldsResponse.FromDict(result)
      self.assertEqual([(fdef.name, fdef.title) for fdef in response.fields],
        [(fdef2.name, fdef2.title)
         for (fdef2, _, _) in utils.NiceSort(fielddefs.values(),
                                             key=lambda x: x[0].name)])

  def testSomeFields(self):
    rnd = random.Random(5357)

    for _ in range(10):
      for fielddefs in query.ALL_FIELD_LISTS:
        if len(fielddefs) > 20:
          sample_size = rnd.randint(5, 20)
        else:
          sample_size = rnd.randint(1, max(1, len(fielddefs) - 1))
        fields = [fdef for (fdef, _, _) in rnd.sample(fielddefs.values(),
                                                      sample_size)]
        result = query.QueryFields(fielddefs, [fdef.name for fdef in fields])
        self.assert_(isinstance(result, dict))
        response = objects.QueryFieldsResponse.FromDict(result)
        self.assertEqual([(fdef.name, fdef.title) for fdef in response.fields],
                         [(fdef2.name, fdef2.title) for fdef2 in fields])


if __name__ == "__main__":
  testutils.GanetiTestProgram()

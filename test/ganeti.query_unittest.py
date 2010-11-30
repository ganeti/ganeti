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


"""Script for testing ganeti.query"""

import re
import unittest

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
    return (constants.QRFS_NORMAL, disks[nr])
  except IndexError:
    return (constants.QRFS_UNAVAIL, None)


class TestQuery(unittest.TestCase):
  def test(self):
    (STATIC, DISK) = range(10, 12)

    fielddef = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT),
       STATIC, lambda ctx, item: (constants.QRFS_NORMAL, item["name"])),
      (query._MakeField("master", "Master", constants.QFT_BOOL),
       STATIC, lambda ctx, item: (constants.QRFS_NORMAL,
                                  ctx.mastername == item["name"])),
      ] +
      [(query._MakeField("disk%s.size" % i, "DiskSize%s" % i,
                         constants.QFT_UNIT),
        DISK, compat.partial(_GetDiskSize, i))
       for i in range(4)])

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
                     [[(constants.QRFS_NORMAL, "node1")],
                      [(constants.QRFS_NORMAL, "node2")],
                      [(constants.QRFS_NORMAL, "node3")]])
    self.assertEqual(q.OldStyleQuery(_QueryData(data, mastername="node3")),
                     [["node1"], ["node2"], ["node3"]])

    q = query.Query(fielddef, ["name", "master"])
    self.assertEqual(q.RequestedData(), set([STATIC]))
    self.assertEqual(len(q._fields), 2)
    self.assertEqual(q.Query(_QueryData(data, mastername="node3")),
                     [[(constants.QRFS_NORMAL, "node1"),
                       (constants.QRFS_NORMAL, False)],
                      [(constants.QRFS_NORMAL, "node2"),
                       (constants.QRFS_NORMAL, False)],
                      [(constants.QRFS_NORMAL, "node3"),
                       (constants.QRFS_NORMAL, True)],
                     ])

    q = query.Query(fielddef, ["name", "master", "disk0.size"])
    self.assertEqual(q.RequestedData(), set([STATIC, DISK]))
    self.assertEqual(len(q._fields), 3)
    self.assertEqual(q.Query(_QueryData(data, mastername="node2")),
                     [[(constants.QRFS_NORMAL, "node1"),
                       (constants.QRFS_NORMAL, False),
                       (constants.QRFS_NORMAL, 0)],
                      [(constants.QRFS_NORMAL, "node2"),
                       (constants.QRFS_NORMAL, True),
                       (constants.QRFS_NORMAL, 3)],
                      [(constants.QRFS_NORMAL, "node3"),
                       (constants.QRFS_NORMAL, False),
                       (constants.QRFS_NORMAL, 5)],
                     ])

    # With unknown column
    q = query.Query(fielddef, ["disk2.size", "disk1.size", "disk99.size",
                               "disk0.size"])
    self.assertEqual(q.RequestedData(), set([DISK]))
    self.assertEqual(len(q._fields), 4)
    self.assertEqual(q.Query(_QueryData(data, mastername="node2")),
                     [[(constants.QRFS_NORMAL, 2),
                       (constants.QRFS_NORMAL, 1),
                       (constants.QRFS_UNKNOWN, None),
                       (constants.QRFS_NORMAL, 0)],
                      [(constants.QRFS_UNAVAIL, None),
                       (constants.QRFS_NORMAL, 4),
                       (constants.QRFS_UNKNOWN, None),
                       (constants.QRFS_NORMAL, 3)],
                      [(constants.QRFS_NORMAL, 7),
                       (constants.QRFS_NORMAL, 6),
                       (constants.QRFS_UNKNOWN, None),
                       (constants.QRFS_NORMAL, 5)],
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
        ])

    # Non-lowercase names
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("NAME", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ])
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("Name", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ])

    # Empty name
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ])

    # Empty title
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "", constants.QFT_TEXT), None,
       lambda *args: None),
      ])

    # Whitespace in title
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "Co lu mn", constants.QFT_TEXT), None,
       lambda *args: None),
      ])

    # No callable function
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "Name", constants.QFT_TEXT), None, None),
      ])

  def testUnknown(self):
    fielddef = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT),
       None, lambda _, item: (constants.QRFS_NORMAL, "name%s" % item)),
      (query._MakeField("other0", "Other0", constants.QFT_TIMESTAMP),
       None, lambda *args: (constants.QRFS_NORMAL, 1234)),
      (query._MakeField("nodata", "NoData", constants.QFT_NUMBER),
       None, lambda *args: (constants.QRFS_NODATA, None)),
      (query._MakeField("unavail", "Unavail", constants.QFT_BOOL),
       None, lambda *args: (constants.QRFS_UNAVAIL, None)),
      ])

    for selected in [["foo"], ["Hello", "World"],
                     ["name1", "other", "foo"]]:
      q = query.Query(fielddef, selected)
      self.assertEqual(len(q._fields), len(selected))
      self.assert_(compat.all(len(row) == len(selected)
                              for row in q.Query(_QueryData(range(1, 10)))))
      self.assertEqual(q.Query(_QueryData(range(1, 10))),
                       [[(constants.QRFS_UNKNOWN, None)] * len(selected)
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
                     [[(constants.QRFS_NORMAL, "name%s" % i),
                       (constants.QRFS_NORMAL, 1234),
                       (constants.QRFS_NODATA, None),
                       (constants.QRFS_UNAVAIL, None),
                       (constants.QRFS_UNKNOWN, None)]
                      for i in range(1, 10)])


class TestGetNodeRole(unittest.TestCase):
  def testMaster(self):
    node = objects.Node(name="node1")
    self.assertEqual(query._GetNodeRole(node, "node1"), "M")

  def testMasterCandidate(self):
    node = objects.Node(name="node1", master_candidate=True)
    self.assertEqual(query._GetNodeRole(node, "master"), "C")

  def testRegular(self):
    node = objects.Node(name="node1")
    self.assertEqual(query._GetNodeRole(node, "master"), "R")

  def testDrained(self):
    node = objects.Node(name="node1", drained=True)
    self.assertEqual(query._GetNodeRole(node, "master"), "D")

  def testOffline(self):
    node = objects.Node(name="node1", offline=True)
    self.assertEqual(query._GetNodeRole(node, "master"), "O")


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
      nqd = query.NodeQueryData(nodes, live_data, None, None, None, None)

      q = self._Create(["name", "drained"])
      self.assertEqual(q.RequestedData(), set([query.NQ_CONFIG]))
      self.assertEqual(q.Query(nqd),
                       [[(constants.QRFS_NORMAL, "node1"),
                         (constants.QRFS_NORMAL, False)],
                        [(constants.QRFS_NORMAL, "node2"),
                         (constants.QRFS_NORMAL, True)],
                        [(constants.QRFS_NORMAL, "node3"),
                         (constants.QRFS_NORMAL, False)],
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
                          query.NQ_GROUP]))

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
                   vm_capable=False,
                   master_capable=False,
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
      ng_uuid: objects.NodeGroup(name="ng1", uuid=ng_uuid),
      }

    master_node.group = ng_uuid

    nqd = query.NodeQueryData(nodes, live_data, master_name,
                              node_to_primary, node_to_secondary, groups)
    result = q.Query(nqd)
    self.assert_(compat.all(len(row) == len(selected) for row in result))
    self.assertEqual([row[field_index["name"]] for row in result],
                     [(constants.QRFS_NORMAL, name) for name in node_names])

    node_to_row = dict((row[field_index["name"]][1], idx)
                       for idx, row in enumerate(result))

    master_row = result[node_to_row[master_name]]
    self.assert_(master_row[field_index["master"]])
    self.assert_(master_row[field_index["role"]], "M")
    self.assertEqual(master_row[field_index["group"]],
                     (constants.QRFS_NORMAL, "ng1"))
    self.assertEqual(master_row[field_index["group.uuid"]],
                     (constants.QRFS_NORMAL, ng_uuid))

    self.assert_(row[field_index["pip"]] == node.primary_ip and
                 row[field_index["sip"]] == node.secondary_ip and
                 set(row[field_index["tags"]]) == node.GetTags() and
                 row[field_index["serial_no"]] == node.serial_no and
                 row[field_index["role"]] == query._GetNodeRole(node,
                                                                master_name) and
                 (node.name == master_name or
                  (row[field_index["group"]] == "<unknown>" and
                   row[field_index["group.uuid"]] is None))
                 for row, node in zip(result, nodes))

    live_data_row = result[node_to_row[live_data_name]]

    for (field, value) in fake_live_data.items():
      self.assertEqual(live_data_row[field_index[field]],
                       (constants.QRFS_NORMAL, value))

    self.assertEqual(master_row[field_index["pinst_cnt"]],
                     (constants.QRFS_NORMAL, 2))
    self.assertEqual(live_data_row[field_index["sinst_cnt"]],
                     (constants.QRFS_NORMAL, 3))
    self.assertEqual(master_row[field_index["pinst_list"]],
                     (constants.QRFS_NORMAL,
                      list(node_to_primary[master_name])))
    self.assertEqual(live_data_row[field_index["sinst_list"]],
                     (constants.QRFS_NORMAL,
                      list(node_to_secondary[live_data_name])))

  def testGetLiveNodeField(self):
    nodes = [
      objects.Node(name="node1", drained=False),
      objects.Node(name="node2", drained=True),
      objects.Node(name="node3", drained=False),
      ]
    live_data = dict.fromkeys([node.name for node in nodes], {})

    # No data
    nqd = query.NodeQueryData(None, None, None, None, None, None)
    self.assertEqual(query._GetLiveNodeField("hello", constants.QFT_NUMBER,
                                             nqd, None),
                     (constants.QRFS_NODATA, None))

    # Missing field
    ctx = _QueryData(None, curlive_data={
      "some": 1,
      "other": 2,
      })
    self.assertEqual(query._GetLiveNodeField("hello", constants.QFT_NUMBER,
                                             ctx, None),
                     (constants.QRFS_UNAVAIL, None))

    # Wrong format/datatype
    ctx = _QueryData(None, curlive_data={
      "hello": ["Hello World"],
      "other": 2,
      })
    self.assertEqual(query._GetLiveNodeField("hello", constants.QFT_NUMBER,
                                             ctx, None),
                     (constants.QRFS_UNAVAIL, None))

    # Wrong field type
    ctx = _QueryData(None, curlive_data={"hello": 123})
    self.assertRaises(AssertionError, query._GetLiveNodeField,
                      "hello", constants.QFT_BOOL, ctx, None)


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

    iqd = query.InstanceQueryData(instances, cluster, None, [], [], {})
    self.assertEqual(q.Query(iqd),
      [[(constants.QRFS_NORMAL, "inst1"),
        (constants.QRFS_NORMAL, 128),
        (constants.QRFS_UNAVAIL, None),
       ],
       [(constants.QRFS_NORMAL, "inst2"),
        (constants.QRFS_NORMAL, 512),
        (constants.QRFS_UNAVAIL, None),
       ],
       [(constants.QRFS_NORMAL, "inst3"),
        (constants.QRFS_NORMAL, 128),
        (constants.QRFS_NORMAL, "192.0.2.99"),
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
                     set([query.IQ_CONFIG, query.IQ_LIVE, query.IQ_DISKUSAGE]))

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
      ]

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
      }

    iqd = query.InstanceQueryData(instances, cluster, disk_usage,
                                  offline_nodes, bad_nodes, live_data)
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
                       (constants.QRFS_NORMAL, inst.name))

      if inst.primary_node in offline_nodes:
        exp_status = "ERROR_nodeoffline"
      elif inst.primary_node in bad_nodes:
        exp_status = "ERROR_nodedown"
      elif inst.name in live_data:
        if inst.admin_up:
          exp_status = "running"
        else:
          exp_status = "ERROR_up"
      elif inst.admin_up:
        exp_status = "ERROR_down"
      else:
        exp_status = "ADMIN_down"

      self.assertEqual(row[fieldidx["status"]],
                       (constants.QRFS_NORMAL, exp_status))

      (_, status) = row[fieldidx["status"]]
      tested_status.add(status)

      for (field, livefield) in [("oper_ram", "memory"),
                                 ("oper_vcpus", "vcpus")]:
        if inst.primary_node in bad_nodes:
          exp = (constants.QRFS_NODATA, None)
        elif inst.name in live_data:
          value = live_data[inst.name].get(livefield, None)
          if value is None:
            exp = (constants.QRFS_UNAVAIL, None)
          else:
            exp = (constants.QRFS_NORMAL, value)
        else:
          exp = (constants.QRFS_UNAVAIL, None)

        self.assertEqual(row[fieldidx[field]], exp)

      bridges = inst_bridges.get(inst.name, [])
      self.assertEqual(row[fieldidx["nic.bridges"]],
                       (constants.QRFS_NORMAL, bridges))
      if bridges:
        self.assertEqual(row[fieldidx["bridge"]],
                         (constants.QRFS_NORMAL, bridges[0]))
      else:
        self.assertEqual(row[fieldidx["bridge"]],
                         (constants.QRFS_UNAVAIL, None))

      for i in range(constants.MAX_NICS):
        if i < len(bridges) and bridges[i] is not None:
          exp = (constants.QRFS_NORMAL, bridges[i])
        else:
          exp = (constants.QRFS_UNAVAIL, None)
        self.assertEqual(row[fieldidx["nic.bridge/%s" % i]], exp)

      if inst.primary_node in bad_nodes:
        exp = (constants.QRFS_NODATA, None)
      else:
        exp = (constants.QRFS_NORMAL, inst.name in live_data)
      self.assertEqual(row[fieldidx["oper_state"]], exp)

      usage = disk_usage[inst.name]
      if usage is None:
        usage = 0
      self.assertEqual(row[fieldidx["disk_usage"]],
                       (constants.QRFS_NORMAL, usage))

      self.assertEqual(row[fieldidx["sda_size"]], row[fieldidx["disk.size/0"]])
      self.assertEqual(row[fieldidx["sdb_size"]], row[fieldidx["disk.size/1"]])

    # Ensure all possible status' have been tested
    self.assertEqual(tested_status,
                     set(["ERROR_nodeoffline", "ERROR_nodedown",
                          "running", "ERROR_up", "ERROR_down",
                          "ADMIN_down"]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()

#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008, 2010 Google Inc.
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
# 0.0510-1301, USA.


"""Script for unittesting the objects module"""


import unittest

from ganeti import constants
from ganeti import objects

import testutils


class SimpleObject(objects.ConfigObject):
  __slots__ = ['a', 'b']


class TestDictState(unittest.TestCase):
  """Simple dict tansformation tests"""

  def testSimpleObjectToDict(self):
    o1 = SimpleObject(a='1')
    self.assertEquals(o1.ToDict(), {'a': '1'})
    self.assertEquals(o1.__getstate__(), {'a': '1'})
    self.assertEquals(o1.__getstate__(), o1.ToDict())
    o1.a = 2
    o1.b = 5
    self.assertEquals(o1.ToDict(), {'a': 2, 'b': 5})
    o2 = SimpleObject.FromDict(o1.ToDict())
    self.assertEquals(o1.ToDict(), {'a': 2, 'b': 5})


class TestClusterObject(unittest.TestCase):
  """Tests done on a L{objects.Cluster}"""

  def setUp(self):
    hvparams = {
      constants.HT_FAKE: {
        "foo": "bar",
        "bar": "foo",
        "foobar": "barfoo",
        },
      }
    os_hvp = {
      "lenny-image": {
        constants.HT_FAKE: {
          "foo": "baz",
          "foobar": "foobar",
          "blah": "blibb",
          "blubb": "blah",
          },
        constants.HT_XEN_PVM: {
          "root_path": "/dev/sda5",
          "foo": "foobar",
          },
        },
      "ubuntu-hardy": {
        },
      }
    self.fake_cl = objects.Cluster(hvparams=hvparams, os_hvp=os_hvp)
    self.fake_cl.UpgradeConfig()

  def testGetHVDefaults(self):
    cl = self.fake_cl
    self.failUnlessEqual(cl.GetHVDefaults(constants.HT_FAKE),
                         cl.hvparams[constants.HT_FAKE])
    self.failUnlessEqual(cl.GetHVDefaults(None), {})
    self.failUnlessEqual(cl.GetHVDefaults(constants.HT_XEN_PVM,
                                          os_name="lenny-image"),
                         cl.os_hvp["lenny-image"][constants.HT_XEN_PVM])


  def testFillHvFullMerge(self):
    inst_hvparams = {
      "blah": "blubb",
      }

    fake_dict = {
      "foo": "baz",
      "bar": "foo",
      "foobar": "foobar",
      "blah": "blubb",
      "blubb": "blah",
      }
    fake_inst = objects.Instance(name="foobar",
                                 os="lenny-image",
                                 hypervisor=constants.HT_FAKE,
                                 hvparams=inst_hvparams)
    self.assertEqual(fake_dict, self.fake_cl.FillHV(fake_inst))

  def testFillHvGlobalParams(self):
    fake_inst = objects.Instance(name="foobar",
                                 os="ubuntu-hardy",
                                 hypervisor=constants.HT_FAKE,
                                 hvparams={})
    self.assertEqual(self.fake_cl.hvparams[constants.HT_FAKE],
                     self.fake_cl.FillHV(fake_inst))

  def testFillHvInstParams(self):
    inst_hvparams = {
      "blah": "blubb",
      }
    fake_inst = objects.Instance(name="foobar",
                                 os="ubuntu-hardy",
                                 hypervisor=constants.HT_XEN_PVM,
                                 hvparams=inst_hvparams)
    self.assertEqual(inst_hvparams, self.fake_cl.FillHV(fake_inst))

  def testFillHvEmptyParams(self):
    fake_inst = objects.Instance(name="foobar",
                                 os="ubuntu-hardy",
                                 hypervisor=constants.HT_XEN_PVM,
                                 hvparams={})
    self.assertEqual({}, self.fake_cl.FillHV(fake_inst))

  def testFillHvPartialParams(self):
    os = "lenny-image"
    fake_inst = objects.Instance(name="foobar",
                                 os=os,
                                 hypervisor=constants.HT_XEN_PVM,
                                 hvparams={})
    self.assertEqual(self.fake_cl.os_hvp[os][constants.HT_XEN_PVM],
                     self.fake_cl.FillHV(fake_inst))


class TestOS(unittest.TestCase):
  ALL_DATA = [
    "debootstrap",
    "debootstrap+default",
    "debootstrap++default",
    ]

  def testSplitNameVariant(self):
    for name in self.ALL_DATA:
      self.assertEqual(len(objects.OS.SplitNameVariant(name)), 2)

  def testVariant(self):
    self.assertEqual(objects.OS.GetVariant("debootstrap"), "")
    self.assertEqual(objects.OS.GetVariant("debootstrap+default"), "default")


if __name__ == '__main__':
  testutils.GanetiTestProgram()

#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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

from ganeti import objects

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


if __name__ == '__main__':
  unittest.main()

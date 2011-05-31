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

"""Script for testing ganeti.cache"""

import testutils
import unittest

from ganeti import cache


class ReturnStub:
  def __init__(self, values):
    self.values = values

  def __call__(self):
    assert self.values
    return self.values.pop(0)


class SimpleCacheTest(unittest.TestCase):
  def setUp(self):
    self.cache = cache.SimpleCache()

  def testNoKey(self):
    self.assertEqual(self.cache.GetMulti(["i-dont-exist", "neither-do-i", "no"]),
                     [None, None, None])

  def testCache(self):
    value = 0xc0ffee
    self.assert_(self.cache.Store("i-exist", value))
    self.assertEqual(self.cache.GetMulti(["i-exist"]), [value])

  def testMixed(self):
    value = 0xb4dc0de
    self.assert_(self.cache.Store("i-exist", value))
    self.assertEqual(self.cache.GetMulti(["i-exist", "i-dont"]), [value, None])

  def testTtl(self):
    my_times = ReturnStub([0, 1, 1, 2, 3, 5])
    ttl_cache = cache.SimpleCache(_time_fn=my_times)
    self.assert_(ttl_cache.Store("test-expire", 0xdeadbeef, ttl=2))

    # At this point time will return 2, 1 (start) + 2 (ttl) = 3, still valid
    self.assertEqual(ttl_cache.Get("test-expire"), 0xdeadbeef)

    # At this point time will return 3, 1 (start) + 2 (ttl) = 3, still valid
    self.assertEqual(ttl_cache.Get("test-expire"), 0xdeadbeef)

    # We are at 5, < 3, invalid
    self.assertEqual(ttl_cache.Get("test-expire"), None)
    self.assertFalse(my_times.values)

  def testCleanup(self):
    my_times = ReturnStub([0, 1, 1, 2, 2, 3, 3, 5, 5,
                           21 + cache.SimpleCache.CLEANUP_ROUND,
                           34 + cache.SimpleCache.CLEANUP_ROUND,
                           55 + cache.SimpleCache.CLEANUP_ROUND * 2,
                           89 + cache.SimpleCache.CLEANUP_ROUND * 3])
    # Index 0
    ttl_cache = cache.SimpleCache(_time_fn=my_times)
    # Index 1, 2
    self.assert_(ttl_cache.Store("foobar", 0x1dea, ttl=6))
    # Index 3, 4
    self.assert_(ttl_cache.Store("baz", 0xc0dea55, ttl=11))
    # Index 6, 7
    self.assert_(ttl_cache.Store("long-foobar", "pretty long",
                                 ttl=(22 + cache.SimpleCache.CLEANUP_ROUND)))
    # Index 7, 8
    self.assert_(ttl_cache.Store("foobazbar", "alive forever"))

    self.assertEqual(set(ttl_cache.cache.keys()),
                     set(["foobar", "baz", "long-foobar", "foobazbar"]))
    ttl_cache.Cleanup()
    self.assertEqual(set(ttl_cache.cache.keys()),
                     set(["long-foobar", "foobazbar"]))
    ttl_cache.Cleanup()
    self.assertEqual(set(ttl_cache.cache.keys()),
                     set(["long-foobar", "foobazbar"]))
    ttl_cache.Cleanup()
    self.assertEqual(set(ttl_cache.cache.keys()), set(["foobazbar"]))
    ttl_cache.Cleanup()
    self.assertEqual(set(ttl_cache.cache.keys()), set(["foobazbar"]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()

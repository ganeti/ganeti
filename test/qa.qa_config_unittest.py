#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing qa.qa_config"""

import unittest

from qa import qa_config

import testutils


class TestTestEnabled(unittest.TestCase):
  def testSimple(self):
    for name in ["test", ["foobar"], ["a", "b"]]:
      self.assertTrue(qa_config.TestEnabled(name, _cfg={}))

    for default in [False, True]:
      self.assertFalse(qa_config.TestEnabled("foo", _cfg={
        "tests": {
          "default": default,
          "foo": False,
          },
        }))

      self.assertTrue(qa_config.TestEnabled("bar", _cfg={
        "tests": {
          "default": default,
          "bar": True,
          },
        }))

  def testEitherWithDefault(self):
    names = qa_config.Either("one")

    self.assertTrue(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        },
      }))

    self.assertFalse(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": False,
        },
      }))

  def testEither(self):
    names = [qa_config.Either(["one", "two"]),
             qa_config.Either("foo"),
             "hello",
             ["bar", "baz"]]

    self.assertTrue(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        },
      }))

    self.assertFalse(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": False,
        },
      }))

    for name in ["foo", "bar", "baz", "hello"]:
      self.assertFalse(qa_config.TestEnabled(names, _cfg={
        "tests": {
          "default": True,
          name: False,
          },
        }))

    self.assertFalse(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        "one": False,
        "two": False,
        },
      }))

    self.assertTrue(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        "one": False,
        "two": True,
        },
      }))

    self.assertFalse(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        "one": True,
        "two": True,
        "foo": False,
        },
      }))

  def testEitherNestedWithAnd(self):
    names = qa_config.Either([["one", "two"], "foo"])

    self.assertTrue(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        },
      }))

    for name in ["one", "two"]:
      self.assertFalse(qa_config.TestEnabled(names, _cfg={
        "tests": {
          "default": True,
          "foo": False,
          name: False,
          },
        }))


if __name__ == "__main__":
  testutils.GanetiTestProgram()

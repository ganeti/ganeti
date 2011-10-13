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


"""Script for testing utils.Mlockall

This test is run in a separate process because it changes memory behaviour.

"""

import unittest

from ganeti import utils
from ganeti import errors

import testutils


# WARNING: The following tests modify the memory behaviour at runtime. Don't
# add unrelated tests here.


class TestMlockallWithCtypes(unittest.TestCase):
  """Whether Mlockall() works if ctypes is present.

  """

  def test(self):
    if utils.ctypes:
      utils.Mlockall()


class TestMlockallWithNoCtypes(unittest.TestCase):
  """Whether Mlockall() raises an error if ctypes is not present.

  """

  def test(self):
    self.assertRaises(errors.NoCtypesError, utils.Mlockall, _ctypes=None)


if __name__ == "__main__":
  testutils.GanetiTestProgram()

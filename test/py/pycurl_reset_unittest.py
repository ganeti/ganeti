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


"""Script for testing for an issue in PycURL"""

import sys
import warnings
import unittest
import textwrap
import pycurl

import testutils


DETAILS = [
  ("PycURL 7.19.0 added a new function named \"reset\" on \"pycurl.Curl\""
   " objects to release all references to other resources. Unfortunately that"
   " version contains a bug with reference counting on the \"None\" singleton,"
   " leading to a crash of the Python interpreter after a certain amount of"
   " performed requests. Your system uses a version of PycURL affected by this"
   " issue. A patch is available at [1]. A detailed description can be found"
   " at [2].\n"),
  "\n",
  ("[1] http://sf.net/tracker/?"
   "func=detail&aid=2893665&group_id=28236&atid=392777\n"),
  "[2] https://bugzilla.redhat.com/show_bug.cgi?id=624559",
  ]


class TestPyCurlReset(unittest.TestCase):
  def test(self):
    start_refcount = sys.getrefcount(None)
    abort_refcount = int(start_refcount * 0.8)

    assert start_refcount > 100

    curl = pycurl.Curl()
    try:
      reset_fn = curl.reset
    except AttributeError:
      pass
    else:
      for i in range(start_refcount * 2):
        reset_fn()
        # The bug can be detected if calling "reset" several times continously
        # reduces the number of references
        if sys.getrefcount(None) < abort_refcount:
          print >>sys.stderr, "#" * 78
          for line in DETAILS:
            print >>sys.stderr, textwrap.fill(line, width=78)
          print >>sys.stderr, "#" * 78
          break


if __name__ == "__main__":
  testutils.GanetiTestProgram()

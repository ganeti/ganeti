#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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

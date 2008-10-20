#!/usr/bin/python
#

# Copyright (C) 2007, 2008 Google Inc.
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


"""Script for unittesting the http module"""


import os
import unittest
import tempfile
import time

from ganeti import http


class HttpLogfileTests(unittest.TestCase):
  """Tests for ApacheLogfile class."""

  class FakeRequest:
    FAKE_ADDRESS = "1.2.3.4"

    def address_string(self):
      return self.FAKE_ADDRESS

  def setUp(self):
    self.tmpfile = tempfile.NamedTemporaryFile()
    self.logfile = http.ApacheLogfile(self.tmpfile)

  def tearDown(self):
    self.tmpfile.close()

  def testFormatLogTime(self):
    self._TestInTimezone(1208646123.0, "Europe/London",
                         "19/Apr/2008:23:02:03 +0000")
    self._TestInTimezone(1208646123, "Europe/Zurich",
                         "19/Apr/2008:23:02:03 +0000")
    self._TestInTimezone(1208646123, "Australia/Sydney",
                         "19/Apr/2008:23:02:03 +0000")

  def _TestInTimezone(self, seconds, timezone, expected):
    """Tests HttpLogfile._FormatLogTime with a specific timezone

    """
    # Preserve environment
    old_TZ = os.environ.get("TZ", None)
    try:
      os.environ["TZ"] = timezone
      time.tzset()
      result = self.logfile._FormatLogTime(seconds)
    finally:
      # Restore environment
      if old_TZ is not None:
        os.environ["TZ"] = old_TZ
      elif "TZ" in os.environ:
        del os.environ["TZ"]
      time.tzset()

    self.assertEqual(result, expected)


  def testLogRequest(self):
    request = self.FakeRequest()
    self.logfile.LogRequest(request, "This is only a %s", "test")


if __name__ == '__main__':
  unittest.main()

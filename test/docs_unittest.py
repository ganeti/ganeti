#!/usr/bin/python
#

# Copyright (C) 2009 Google Inc.
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


"""Script for unittesting documentation"""

import unittest
import re

from ganeti import _autoconf
from ganeti import utils
from ganeti import cmdlib
from ganeti import build
from ganeti.rapi import connector

import testutils


class TestDocs(unittest.TestCase):
  """Documentation tests"""

  @staticmethod
  def _ReadDocFile(filename):
    return utils.ReadFile("%s/doc/%s" %
                          (testutils.GetSourceDir(), filename))

  def testHookDocs(self):
    """Check whether all hooks are documented.

    """
    hooksdoc = self._ReadDocFile("hooks.rst")

    for name in dir(cmdlib):
      obj = getattr(cmdlib, name)

      if (isinstance(obj, type) and
          issubclass(obj, cmdlib.LogicalUnit) and
          hasattr(obj, "HPATH")):
        self._CheckHook(name, obj, hooksdoc)

  def _CheckHook(self, name, lucls, hooksdoc):
    if lucls.HTYPE is None:
      return

    # TODO: Improve this test (e.g. find hooks documented but no longer
    # existing)

    pattern = r"^:directory:\s*%s\s*$" % re.escape(lucls.HPATH)

    self.assert_(re.findall(pattern, hooksdoc, re.M),
                 msg=("Missing documentation for hook %s/%s" %
                      (lucls.HTYPE, lucls.HPATH)))


  def testRapiDocs(self):
    """Check whether all RAPI resources are documented.

    """
    rapidoc = self._ReadDocFile("rapi.rst")

    node_name = "[node_name]"
    instance_name = "[instance_name]"
    group_name = "[group_name]"
    job_id = "[job_id]"

    resources = connector.GetHandlers(re.escape(node_name),
                                      re.escape(instance_name),
                                      re.escape(group_name),
                                      re.escape(job_id))

    titles = []

    prevline = None
    for line in rapidoc.splitlines():
      if re.match(r"^\++$", line):
        titles.append(prevline)

      prevline = line

    prefix_exception = frozenset(["/", "/version", "/2"])

    undocumented = []

    for key, handler in resources.iteritems():
      # Regex objects
      if hasattr(key, "match"):
        self.assert_(key.pattern.startswith("^/2/"),
                     msg="Pattern %r does not start with '^/2/'" % key.pattern)

        found = False
        for title in titles:
          if (title.startswith("``") and
              title.endswith("``") and
              key.match(title[2:-2])):
            found = True
            break

        if not found:
          # TODO: Find better way of identifying resource
          undocumented.append(key.pattern)

      else:
        self.assert_(key.startswith("/2/") or key in prefix_exception,
                     msg="Path %r does not start with '/2/'" % key)

        if ("``%s``" % key) not in titles:
          undocumented.append(key)

    self.failIf(undocumented,
                msg=("Missing RAPI resource documentation for %s" %
                     utils.CommaJoin(undocumented)))


class TestManpages(unittest.TestCase):
  """Manpage tests"""

  @staticmethod
  def _ReadManFile(name):
    return utils.ReadFile("%s/man/%s.rst" %
                          (testutils.GetSourceDir(), name))

  @staticmethod
  def _LoadScript(name):
    return build.LoadModule("scripts/%s" % name)

  def test(self):
    for script in _autoconf.GNT_SCRIPTS:
      self._CheckManpage(script,
                         self._ReadManFile(script),
                         self._LoadScript(script).commands.keys())

  def _CheckManpage(self, script, mantext, commands):
    missing = []

    for cmd in commands:
      pattern = r"^(\| )?\*\*%s\*\*" % re.escape(cmd)
      if not re.findall(pattern, mantext, re.DOTALL | re.MULTILINE):
        missing.append(cmd)

    self.failIf(missing,
                msg=("Manpage for '%s' missing documentation for %s" %
                     (script, utils.CommaJoin(missing))))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
